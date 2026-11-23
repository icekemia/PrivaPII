import unittest

from privapii.export_formats import csv_text, render_export
from privapii.export_review import inspect_export, retained_identifiers, retained_transcriptions
from privapii.detection import Case, Span, rules


class ExportReviewTests(unittest.TestCase):
    def test_duplicate_values_need_review_if_only_one_occurrence_was_retained(self):
        email = "test_name@example.org"
        source = f"{email}\n{email}"
        findings = list(rules(source))[:1]
        retained = retained_identifiers(source, findings, [])
        markdown = render_export(source, "Markdown", "sample.pdf")
        count, residuals = inspect_export(markdown, "Markdown", source, retained)
        self.assertEqual(count, 0)
        self.assertEqual([(item.value, item.intentionally_retained) for item in residuals],
                         [(email, False), (email, False)])
        self.assertTrue(inspect_export(email, "TXT", email, retained)[1][0].intentionally_retained)

    def test_checks_csv_cells_and_ignores_token_bodies(self):
        value = "+370 612 34567"
        case = Case()
        token = case.transform(value, [Span(0, len(value), "NUM_PHONE")])
        original = f"Phone,Context\n{token},{value}"
        table = csv_text([["Phone", "Context"], [token, value]])
        count, residuals = inspect_export(table, "CSV", original, retained_transcriptions([value]))
        self.assertEqual(count, 1)
        self.assertEqual([(item.category, item.intentionally_retained) for item in residuals],
                         [("NUM_PHONE", True)])

    def test_rejects_lost_or_damaged_restoration_tokens(self):
        token = Case().transform("Name", [Span(0, 4, "PER")])
        for altered in ("Name", token[:-1], token + " [PRIVAPII_V2_"):
            with self.assertRaises(ValueError):
                inspect_export(altered, "TXT", token)
