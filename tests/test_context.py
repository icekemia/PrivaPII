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

    def test_automatic_cross_line_finding_preserves_markdown_line_break(self):
        from export_formats import render_export

        text = "Asmuo: Jonas Petraitis\nPranešimas"
        span = Span(text.index("Jonas"), len(text), "PER", "nus")
        case = Case()
        export = case.transform(text, review_spans(text, [span]))
        markdown = render_export(export, "Markdown", "fixture.pdf")
        self.assertIn("  \n", markdown)
        self.assertEqual(case.restore(markdown)[0], render_export(text, "Markdown", "fixture.pdf"))

    def test_written_document_date_survives_split_automatic_findings(self):
        text = "Nr. AB-12\n2026 m. lapkričio mėn. 16 d.\nSąlygos"
        year = text.index("2026")
        spans = [Span(4, year + 4, "ID_MISC", "nus"),
                 Span(year + 5, text.index("\nSąlygos"), "DATE", "nus")]
        reviewed = review_spans(text, spans)
        selected = selected_indices(reviewed, PROFILES["Standard"], set())
        output = Case().transform(text, [reviewed[index] for index in selected])
        self.assertIn("\n2026 m. lapkričio mėn. 16 d.", output)
        self.assertNotIn("AB-12", output)

    def test_single_surname_span_expands_to_the_adjacent_given_name(self):
        text = "Kontaktas: Austėja Varnaitė, prašymas."
        start = text.index("Varnaitė")
        reviewed = review_spans(text, [Span(start, start + len("Varnaitė,"), "PER", "nus")])
        self.assertEqual(text[reviewed[0].start:reviewed[0].end], "Austėja Varnaitė")
        case = Case()
        output = case.transform(text, reviewed)
        self.assertNotIn("Austėja", output)
        self.assertNotIn("Varnaitė", output)
        self.assertIn(", prašymas.", output)
        self.assertEqual(case.restore(output), (text, 1))

    def test_name_expansion_preserves_an_independently_detected_location(self):
        text = "Vilnius Austėja"
        location, person = Span(0, 7, "LOC", "nus"), Span(8, len(text), "PER", "nus")
        self.assertEqual(review_spans(text, [location, person]), [location, person])

    def test_split_date_label_does_not_hide_given_name_from_name_expansion(self):
        text = "2026 m. lapkričio mėn. 16 d.\nJono Petraičio,"
        date_span = Span(5, text.index(" Petraičio"), "DATE", "nus")
        person = Span(text.index("Petraičio"), len(text), "PER", "nus")
        findings = review_spans(text, [date_span, person])
        self.assertEqual([text[s.start:s.end] for s in findings],
                         ["2026 m. lapkričio mėn. 16 d.", "Jono Petraičio"])

    def test_typed_token_for_specific_identifier_with_generic_overlap(self):
        case = Case()
        text = "Identifier"
        output = case.transform(text, [Span(0, 10, "ID_MISC"), Span(1, 9, "ID_PER")])
        self.assertTrue(output.startswith("[PRIVAPII_V2_ID_PER_"))
        self.assertEqual(case.restore(output), (text, 1))
