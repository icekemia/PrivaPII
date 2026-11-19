import tempfile
import unittest
from pathlib import Path

from benchmark import development_rows
from export_quality import evaluate
from privapii import Span


class ExportQualityTests(unittest.TestCase):
    def test_fixture_marks_both_privacy_and_retention_expectations(self):
        fixture = Path(__file__).parent / "fixtures/export_quality.json"
        rows = list(development_rows(fixture))
        labels = {span["label"] for row in rows for span in row["label"]}
        self.assertTrue({"PER", "DOB", "KEEP_DATE", "KEEP_REFERENCE"} <= labels)
        self.assertEqual(len(rows), 6)

    def test_successful_restoration_still_reports_a_missed_identifier(self):
        text = "1. Kontaktas: Jonas Petraitis."
        name = text.index("Jonas")
        row = {
            "text": text,
            "label": [{"start": 0, "end": 2, "label": "KEEP_REFERENCE"},
                      {"start": name, "end": len(text) - 1, "label": "PER"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            report = evaluate([row], lambda _: [], Path(directory))
        self.assertEqual(report["categories"]["PER"]["fully_exposed"], 1)
        self.assertEqual(report["categories"]["KEEP_REFERENCE"]["preserved"], 1)
        self.assertEqual(report["documents"]["documents_with_exposure"], 1)
        self.assertTrue(report["combined_restoration"]["matches_expected_markdown"])

    def test_reports_partial_exposure_and_overmasking_separately(self):
        text = "Jonas\nPetraitis\nIšduota 2026-11-16."
        date = text.index("2026")
        row = {"text": text, "label": [
            {"start": 0, "end": len("Jonas\nPetraitis"), "label": "PER"},
            {"start": date, "end": len(text) - 1, "label": "KEEP_DATE"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            report = evaluate(
                [row], lambda _: [Span(0, 5, "PER", "nus"), Span(date, date + 4, "ID_MISC", "nus")],
                Path(directory),
            )
        self.assertEqual(report["categories"]["PER"]["partially_exposed"], 1)
        self.assertEqual(report["categories"]["KEEP_DATE"]["obscured"], 1)
