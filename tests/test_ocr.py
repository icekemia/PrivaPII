import tempfile
import unittest
from pathlib import Path

from ocr import Reading, align
from ocr_review import Review, export_review
from vault import Workspace


class OcrTests(unittest.TestCase):
    def test_preserves_disagreement_and_unmatched_readings(self):
        original = Reading("Ąžuolas 1000", (0, 0, 120, 20), 0.98, "paddle")
        alternate = Reading("Ažuolas 1O00", (5, 2, 125, 21), 98, "tesseract")
        extra = Reading("Skiltis", (0, 30, 80, 45), 93, "tesseract")
        first, second = align([original], [alternate, extra])
        self.assertEqual(first.status, "unresolved")
        self.assertEqual(first.box, (0, 0, 125, 21))
        self.assertEqual(first.alternative, (alternate,))
        self.assertEqual(second.status, "machine_read")

    def test_groups_split_lines_without_losing_either_reading(self):
        left = [Reading("A", (0, 0, 20, 10), .98, "paddle"),
                Reading("B", (24, 0, 40, 10), .98, "paddle")]
        right = [Reading("A B", (0, 0, 40, 10), 98, "tesseract")]
        region, = align(left, right)
        self.assertEqual(region.primary, tuple(left))
        self.assertEqual(region.alternative, tuple(right))
        self.assertEqual(region.status, "unresolved")

    def test_only_verified_values_get_restoration_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.sqlite"
            password = "test passphrase for OCR"
            vault = Workspace(path, password, create=True)
            a = Reading("Ažuolas 123", (0, 0, 100, 20), 0.8, "paddle")
            b = Reading("Ažuolas 123", (0, 0, 100, 20), 95, "tesseract")
            region = align([a], [b])[0]
            self.assertEqual(region.status, "cross_checked")
            masked = Review(1, (400, 400), region, ("PER",))
            verified = Review(2, (400, 400), region, ("PER",), "protect", "Ąžuolas 123")
            output = export_review(vault, Path("fixture.pdf"), "fixture", 250, [masked, verified])
            reopened = Workspace(path, password)
            self.assertEqual(reopened.restore(output), ("[REDACTED]\nĄžuolas 123", 1))
            self.assertNotIn("Ažuolas", output)
            document_id, document = next(iter(reopened.documents.items()))
            self.assertEqual(document["ocr"]["regions"][1]["verification_status"], "human_verified")
            self.assertEqual(document["ocr"]["regions"][1]["occurrence_id"], document["occurrences"][0]["id"])
            reopened.review(document_id, document["name"], document["text"], [])
            self.assertIn("ocr", reopened.documents[document_id])

    def test_blocks_authorizing_empty_or_multiline_transcription(self):
        region = align([Reading("123", (0, 0, 20, 20), .8, "paddle")], [])[0]
        for value in (None, " ", "one\ntwo"):
            with self.assertRaises(ValueError):
                export_review(None, Path("fixture.pdf"), "fixture", 250,
                              [Review(1, (100, 100), region, action="protect", verified=value)])
