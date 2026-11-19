import unittest

from policy import PROFILES, selected_indices
from privapii import Case, Span, canonical_token, restore_references, review_spans


class ContextTests(unittest.TestCase):
    def test_standard_preserves_issue_date_and_reference_but_protects_birth_date(self):
        text = "Išduota 2026-11-16.\n1. Sąlyga. Kaip nurodyta 1 p. ir punkte 1. Gimimo data: 1988-10-09."
        expressions = [("2026-11-16", "DATE"), ("1988-10-09", "DATE"),
                       ("1. Sąlyga", "VALUE"), ("1 p.", "ID_MISC"), ("1. Gimimo", "VALUE")]
        spans = [Span(text.index(value), text.index(value) + len(value.split()[0]), label, "nus")
                 for value, label in expressions]
        reviewed = review_spans(text, spans)
        self.assertEqual({span.label for span in reviewed}, {"DATE", "DOB"})
        protected = [reviewed[index] for index in selected_indices(reviewed, PROFILES["Standard"], set())]
        case = Case()
        output = case.transform(text, protected)
        self.assertIn("Išduota 2026-11-16.", output)
        self.assertIn("1. Sąlyga. Kaip nurodyta 1 p. ir punkte 1.", output)
        self.assertIn("[PRIVAPII_V2_DOB_", output)
        self.assertNotIn("1988-10-09", output)
        self.assertEqual(case.restore(output), (text, 1))
        self.assertEqual(len(selected_indices(reviewed, PROFILES["Strict"], set())), 2)

    def test_legacy_tokens_remain_restorable(self):
        token = canonical_token("PRIVAPII_V1_" + "A" * 32)
        self.assertEqual(restore_references(token, {token: "value"}), ("value", 1))

    def test_numbered_references_do_not_override_a_dotted_year_first_date(self):
        text = "2026.11.16. Documento. Come da punto 1.2."
        date = Span(0, len("2026.11.16"), "DATE", "nus")
        start = text.index("1.2")
        reference = Span(start, start + 3, "ID_MISC", "nus")
        self.assertEqual(review_spans(text, [date, reference]), [date])

    def test_broad_identifier_span_retains_point_reference_and_keeps_other_text_protected(self):
        text = "kaip nurodyta 1 p. X-123"
        start = text.index("1 p.")
        span = Span(start, len(text), "ID_MISC", "nus")
        reviewed = review_spans(text, [span])
        case = Case()
        output = case.transform(text, reviewed)
        self.assertIn("1 p.", output)
        self.assertNotIn("X-123", output)
        self.assertEqual(case.restore(output), (text, 1))

    def test_broad_span_preserves_line_break_before_list_marker(self):
        text = "AB-123\n1. Sąlyga"
        span = Span(0, len("AB-123\n1."), "ID_MISC", "nus")
        case = Case()
        output = case.transform(text, review_spans(text, [span]))
        self.assertIn("\n1. Sąlyga", output)
        self.assertNotIn("AB-123", output)

    def test_typed_token_for_specific_identifier_with_generic_overlap(self):
        case = Case()
        text = "Identifier"
        output = case.transform(text, [Span(0, 10, "ID_MISC"), Span(1, 9, "ID_PER")])
        self.assertTrue(output.startswith("[PRIVAPII_V2_ID_PER_"))
        self.assertEqual(case.restore(output), (text, 1))
