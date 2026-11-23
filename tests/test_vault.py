import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from privapii import Span
from export_formats import render_export
from vault import Workspace


class VaultTests(unittest.TestCase):
    def test_retention_reminder_and_forgetting_only_exclusive_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.sqlite"
            password = "retention test passphrase"
            vault = Workspace(path, password, create=True)
            for key in ("first", "second"):
                vault.review(key, key + ".txt", "Jonas", [Span(0, 5, "PER")])
            entity = vault.documents["first"]["occurrences"][0]["entity"]
            vault.link("second", 0, entity)
            shared = vault.transform("first", [0])
            self.assertEqual(vault.transform("second", [0]), shared)
            vault.review("private", "third.txt", "Rūta", [Span(0, 4, "PER")])
            exclusive = vault.transform("private", [0])
            vault.set_retention_review("2026-12-01")
            self.assertEqual(vault.forget_document("first"), 0)
            self.assertEqual(vault.forget_document("private"), 1)
            reopened = Workspace(path, password)
            self.assertEqual(reopened.retention_review_on, "2026-12-01")
            self.assertEqual(set(reopened.documents), {"second"})
            self.assertEqual(reopened.restore(shared), ("Jonas", 1))
            with self.assertRaises(ValueError):
                reopened.restore(exclusive)
    def test_verified_encrypted_backup_reopens_and_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            password = "backup acceptance password"
            vault = Workspace(folder / "source.sqlite", password, create=True)
            vault.review("sample", "sample.txt", "Jonas", [Span(0, 5, "PER")])
            token = vault.transform("sample", [0])
            backup = folder / "backup.sqlite"
            vault.backup(backup)
            reopened = Workspace(backup, password)
            self.assertEqual(reopened.restore(token), ("Jonas", 1))
            self.assertNotIn(b"Jonas", backup.read_bytes())
            with self.assertRaises(FileExistsError):
                vault.backup(backup)
            Workspace(vault.path, password).save()
            stale = folder / "stale.sqlite"
            with self.assertRaisesRegex(ValueError, "changed"):
                vault.backup(stale)
            self.assertFalse(stale.exists())
    def test_linked_tokens_and_local_occurrence_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.sqlite"
            password = "linked variant test password"
            vault = Workspace(path, password, create=True)
            nominative, genitive = "Jonas Petraitis", "Jono Petraičio"
            for key, value in (("one", nominative), ("two", genitive), ("homonym", nominative)):
                vault.review(key, f"{key}.md", value, [Span(0, len(value), "PER")])
            entity = vault.documents["one"]["occurrences"][0]["entity"]
            vault.link("two", 0, entity)
            unlinked = vault.transform("one", [0])
            self.assertTrue(unlinked.startswith("[PRIVAPII_V2_PER_"))
            first, second, homonym = (
                vault.transform(key, [0], link_person_forms=True) for key in ("one", "two", "homonym")
            )
            prefix = f"[PRIVAPII_V3_PER_{entity.upper()}_"
            self.assertTrue(first.startswith(prefix))
            self.assertTrue(second.startswith(prefix))
            self.assertFalse(homonym.startswith(prefix))
            self.assertNotEqual(first, second)
            self.assertEqual(vault.transform("one", [0], link_person_forms=True), first)
            reopened = Workspace(path, password)
            text = render_export(f"**{second}** {first} {first} {homonym}", "Markdown", "source.md")
            self.assertEqual(reopened.restore(text), (f"**{genitive}** {nominative} {nominative} {nominative}", 4))
            self.assertEqual(reopened.restore(text, {1: genitive}),
                             (f"**{genitive}** {genitive} {nominative} {nominative}", 4))
            self.assertEqual(reopened.forms_by_occurrence(unlinked), {0: (nominative, genitive)})
            for invalid in ({3: genitive}, {0: "Invented form"}):
                with self.assertRaises(ValueError):
                    reopened.restore(text, invalid)
            with self.assertRaises(ValueError):
                reopened.restore(text + " [PRIVAPII_V3_PER_")
            reopened.link("two", 0, reopened.documents["homonym"]["occurrences"][0]["entity"])
            self.assertEqual(reopened.forms_by_occurrence(text), {})
            self.assertEqual(reopened.restore(second), (genitive, 1))

    def test_linked_forms_homonyms_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.sqlite"
            password = "local test passphrase"
            vault = Workspace(path, password, create=True)
            for key, text in (("a", "Jonas Petraitis"), ("b", "Jono Petraičio"), ("c", "Jonas Petraitis")):
                vault.review(key, key, text, [Span(0, len(text), "PER")])
            entity = vault.documents["a"]["occurrences"][0]["entity"]
            vault.link("b", 0, entity)
            one, two, homonym = (vault.transform(key, [0]) for key in ("a", "b", "c"))
            self.assertNotEqual(one, homonym)
            self.assertEqual(vault.transform("a", [0]), one)
            reopened = Workspace(path, password)
            self.assertEqual(reopened.documents["b"]["occurrences"][0]["entity"], entity)
            self.assertEqual(reopened.restore(f"**{two}** {one} {two}"),
                             ("**Jono Petraičio** Jonas Petraitis Jono Petraičio", 3))
            self.assertNotIn(b"Jonas Petraitis", path.read_bytes())
            with self.assertRaises(ValueError):
                Workspace(path, "wrong local password")
            foreign = Workspace(Path(directory) / "foreign.sqlite", password, create=True)
            with self.assertRaises(ValueError):
                foreign.restore(one)
            with self.assertRaises(ValueError):
                reopened.restore(one[:-1])
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE vault SET payload = zeroblob(length(payload))")
            with self.assertRaises(ValueError):
                Workspace(path, password)
