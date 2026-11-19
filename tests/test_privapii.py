import unittest
from collections import Counter

from benchmark import score, summarize
from privapii import Case, Span, TOKEN, hybrid


class CaseTests(unittest.TestCase):
    def test_restores_reordered_and_repeated_surface_forms(self):
        case = Case()
        first = case.transform("Jonas", [Span(0, 5, "PER")])
        second = case.transform("Jono", [Span(0, 4, "PER")])
        self.assertEqual(case.restore(f"**{second}** {first} {first}"), ("**Jono** Jonas Jonas", 3))

    def test_rejects_foreign_and_corrupted_tokens(self):
        case = Case()
        token = case.transform("Jonas", [Span(0, 5, "PER")])
        with self.assertRaises(ValueError):
            Case().restore(token)
        with self.assertRaises(ValueError):
            case.restore(token[:-2])
        with self.assertRaises(ValueError):
            case.restore(token + " [PRIVAPII")

    def test_overlap_redacts_entire_union_without_mapping(self):
        case = Case()
        value = case.transform("abcdef", [Span(0, 3, "PER"), Span(2, 5, "LOC")], redact=True)
        self.assertEqual(value, "[REDACTED]f")
        self.assertIsNone(TOKEN.search(value))
        self.assertEqual(case.restore(value), (value, 0))

    def test_rules_add_uncovered_phone_without_duplicate(self):
        text = "Tel. +370 612 34567"
        expected = Span(5, len(text), "NUM_PHONE")
        self.assertEqual(hybrid(text), [expected])
        self.assertEqual(hybrid(text, [expected]), [expected])

    def test_leakage_counts_partial_masks_and_contiguous_coverage(self):
        gold = {Span(1, 4, "PER")}
        stats = {"PER": Counter()}
        self.assertTrue(score(stats, gold, [Span(1, 2, "PER"), Span(3, 4, "PER")]))
        self.assertFalse(score(stats, gold, [Span(0, 2, "PER"), Span(2, 4, "PER")]))
        self.assertEqual(stats["PER"]["uncovered"], 1)

    def test_benchmark_distinguishes_boundaries_wrong_labels_and_misses(self):
        gold = {Span(0, 4, "PER"), Span(7, 9, "PER"), Span(11, 13, "PER")}
        stats = {"PER": Counter(), "LOC": Counter()}
        score(stats, gold, [Span(0, 3, "PER"), Span(7, 9, "LOC")])
        report = summarize(stats["PER"])
        self.assertEqual(report["boundary_errors"], 1)
        self.assertEqual(report["wrong_label_overlaps"], 1)
        self.assertEqual(report["complete_omissions"], 1)
        self.assertEqual(report["false_negatives"], 3)


if __name__ == "__main__":
    unittest.main()
