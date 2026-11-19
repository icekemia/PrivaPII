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

    def test_typed_token_for_specific_identifier_with_generic_overlap(self):
        case = Case()
        text = "Identifier"
        output = case.transform(text, [Span(0, 10, "ID_MISC"), Span(1, 9, "ID_PER")])
        self.assertTrue(output.startswith("[PRIVAPII_V2_ID_PER_"))
        self.assertEqual(case.restore(output), (text, 1))
