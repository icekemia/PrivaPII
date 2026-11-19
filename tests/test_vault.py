import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from privapii import Span
from vault import Workspace


class VaultTests(unittest.TestCase):
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
