import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from batch_export import Batch
from policy import PROFILES
from privapii import TOKEN, Span
from vault import Workspace


class BatchExportTests(unittest.TestCase):
    def test_review_gate_and_local_restoration(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            password = "batch restoration password"
            vault = Workspace(folder / "case.sqlite", password, create=True)
            for key, text in (("a", "Jonas Petraitis"), ("b", "Jono Petraičio")):
                vault.review(key, f"Personal folder {key}.txt", text, [Span(0, len(text), "PER")])
            entity = vault.documents["a"]["occurrences"][0]["entity"]
            vault.link("b", 0, entity)
            vault.save()
            batch = Batch(vault, ["a", "b"], PROFILES["Standard"], "Markdown", link_person_forms=True)
            self.assertEqual(vault.references, {})
            path = folder / "reviewed.zip"
            batch.approve(0, True)
            with self.assertRaises(ValueError):
                batch.write(path)
            self.assertFalse(path.exists())
            batch.approve(1, True)
            batch.write(path)
            with ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ["document-001.md", "document-002.md"])
                one, two = [archive.read(name).decode("utf-8") for name in archive.namelist()]
            self.assertTrue(TOKEN.fullmatch(one))
            self.assertTrue(one.startswith(f"[PRIVAPII_V3_PER_{entity.upper()}_"))
            self.assertTrue(two.startswith(f"[PRIVAPII_V3_PER_{entity.upper()}_"))
            reopened = Workspace(vault.path, password)
            self.assertEqual(reopened.restore(f"{two}\n{one}"),
                             ("Jono Petraičio\nJonas Petraitis", 2))
            with self.assertRaises(FileExistsError):
                batch.write(path)

    def test_concurrent_workspace_change_cannot_publish_unregistered_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            password = "batch concurrency password"
            vault = Workspace(path / "case.sqlite", password, create=True)
            vault.review("a", "name.txt", "Jonas", [Span(0, 5, "PER")])
            vault.save()
            batch = Batch(vault, ["a"], {"PER"}, "TXT")
            batch.approve(0, True)
            Workspace(vault.path, password).save()
            target = path / "out.zip"
            with self.assertRaisesRegex(ValueError, "changed"):
                batch.write(target)
            self.assertFalse(target.exists())
            self.assertFalse(vault.references)
