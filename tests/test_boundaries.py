import unittest
from pathlib import Path

from tools.benchmark import development_rows
from privapii.nus import decode_centered
from privapii.detection import Span


class BoundaryTests(unittest.TestCase):
    def test_centered_tag_wins_and_continuations_keep_word_end(self):
        text = "Jono Petraičio"
        words = {
            0: {(0, 4): [(0, 4, "O", .9, 1), (0, 4, "B-PER", .8, 100)]},
            1: {
                (4, 9): [(4, 9, "I-PER", .7, 95)],
                (9, len(text)): [(9, len(text), "O", .9, 96)],
            },
        }
        self.assertEqual(decode_centered(text, words), [Span(0, len(text), "PER")])

    def test_development_fixture_offsets_preserve_diacritics(self):
        path = Path(__file__).parent / "fixtures/lithuanian_development.json"
        rows = list(development_rows(path))
        first = rows[0]
        self.assertEqual(
            [first["text"][item["start"]:item["end"]] for item in first["label"]],
            ["Austėja Varnaitė", "Gabrieliui Šalnai"],
        )
        self.assertTrue(any(not row["label"] for row in rows))
