import tempfile
import unittest
from pathlib import Path

from person_review import name_variants, person_mentions
from privapii import Span
from vault import Workspace


class PersonReviewTests(unittest.TestCase):
    def test_matching_spelling_flags_homonyms_and_explicit_links_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "people.sqlite"
            password = "workspace person review passphrase"
            vault = Workspace(path, password, create=True)
            for key, value in (("first", "Jonas Petraitis"), ("form", "Jono Petraičio"),
                               ("homonym", "Jonas Petraitis")):
                vault.review(key, f"{key}.txt", value, [Span(0, len(value), "PER")])
            mentions = person_mentions(vault.documents)
            first, form, homonym = mentions
            self.assertTrue(first.spelling_candidate and homonym.spelling_candidate)
            self.assertFalse(form.spelling_candidate)
            self.assertTrue(form.inflection_candidate)
            self.assertEqual(set(form.candidate_ids), {first.occurrence_id, homonym.occurrence_id})
            self.assertEqual(len({item.entity_id for item in mentions}), 3)
            previous = vault.transform("form", [0], link_person_forms=True)
            self.assertEqual(vault.link_people([form.occurrence_id], first.occurrence_id), 1)
            reopened = Workspace(path, password)
            first, form, homonym = person_mentions(reopened.documents)
            self.assertEqual(first.entity_id, form.entity_id)
            self.assertNotEqual(first.entity_id, homonym.entity_id)
            self.assertEqual(reopened.restore(previous), ("Jono Petraičio", 1))
            export = reopened.transform("form", [0], link_person_forms=True)
            self.assertTrue(export.startswith(f"[PRIVAPII_V3_PER_{first.entity_id.upper()}_"))

    def test_candidates_require_both_parts_in_the_same_case(self):
        self.assertEqual(name_variants("jonas petraitis"),
                         ("jono petraičio", "jonui petraičiui", "joną petraitį"))
        self.assertEqual(name_variants("rūta mintytė"),
                         ("rūtos mintytės", "rūtai mintytei", "rūtą mintytę"))
        self.assertNotIn("jono petraičiui", name_variants("jonas petraitis"))
        self.assertEqual(name_variants("j. petraitis"), ())

    def test_rejects_unknown_or_non_person_occurrences_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Workspace(Path(directory) / "people.sqlite", "review validation passphrase", create=True)
            vault.review("a", "sample.txt", "Jonas 2026", [Span(0, 5, "PER"), Span(6, 10, "DATE")])
            person, date = vault.documents["a"]["occurrences"]
            with self.assertRaises(ValueError):
                vault.link_people([date["id"]], person["id"])
            with self.assertRaises(ValueError):
                vault.link_people([person["id"]], "unknown")
