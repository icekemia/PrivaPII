import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from PIL import Image, ImageDraw

from export_formats import parse_csv, render_export, restore_csv
from ocr import Reading, Region
from ocr_review import Review, export_review
from pdf_redaction import review_masks
from raster_tables import RasterTable, find_grids
from vault import Workspace


class RasterTableTests(unittest.TestCase):
    @unittest.skipUnless(find_spec("cv2"), "OpenCV is installed with the OCR dependencies")
    def test_finds_a_complete_grid_and_rejects_a_missing_divider(self):
        page = Image.new("RGB", (480, 260), "white")
        draw = ImageDraw.Draw(page)
        for x in (40, 180, 420):
            draw.line((x, 40, x, 220), fill="black", width=3)
        for y in (40, 120, 220):
            draw.line((40, y, 420, y), fill="black", width=3)
        grid, = find_grids(page, 4)
        self.assertEqual(grid.shape, (2, 2))
        self.assertEqual(grid.page, 4)
        self.assertEqual(len(list(grid.cells())), 4)
        draw.rectangle((175, 127, 185, 211), fill="white")
        self.assertEqual(find_grids(page, 4), [])

    def test_verified_cells_restore_and_unreviewed_cells_stay_masked(self):
        page = Image.new("RGB", (420, 240), "white")
        grid = RasterTable(1, (20, 140, 260, 400), (10, 100, 230))
        decisions = [("keep", "Data"), ("keep", "Vardas"), ("keep", "Pastabos"),
                     ("keep", "2026-11-16"), ("protect", 'Ona, "Austėja"'), ("mask", None)]
        reviews = []
        for (row, column, box), (action, verified) in zip(grid.cells(), decisions):
            reading = Reading("Machine reading", box, 0.95, "paddle")
            reviews.append(Review(1, page.size, Region(box, (reading,), (), "machine_read"),
                                  ("PER",) if action == "protect" else (),
                                  action, verified, (row, column)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.sqlite"
            passphrase = "table OCR test passphrase"
            vault = Workspace(path, passphrase, create=True)
            tsv = export_review(vault, Path("scan.pdf"), "fixture", 250, reviews)
            reopened = Workspace(path, passphrase)
            document = next(iter(reopened.documents.values()))
            csv = render_export(tsv, "CSV", document["name"], document["text"])
            restored, count = restore_csv(csv, reopened.restore)
            self.assertEqual(count, 1)
            self.assertEqual(parse_csv(restored), [["Data", "Vardas", "Pastabos"],
                             ["2026-11-16", 'Ona, "Austėja"', "[REDACTED]"]])
            self.assertNotIn("Machine reading", csv)
            self.assertEqual(document["ocr"]["regions"][-2]["cell"], [1, 1])
            self.assertEqual(document["ocr"]["regions"][-2]["verification_status"], "human_verified")
            self.assertEqual(review_masks({1: page}, reviews), {1: [(140, 100, 260, 230), (260, 100, 400, 230)]})

    def test_merged_cell_uses_full_pdf_mask_and_single_csv_value(self):
        page = Image.new("RGB", (420, 240), "white")
        grid = RasterTable(1, (20, 140, 260, 400), (10, 100, 230), ((1, 0, 1, 1),))
        decisions = [("keep", "First"), ("keep", "Second"), ("keep", "Date"),
                     ("protect", "Merged confidential value"), ("continuation", None),
                     ("keep", "2026-11-16")]
        reviews = []
        for (row, column, box), (action, verified) in zip(grid.cells(), decisions):
            reviews.append(Review(1, page.size, Region(box, (), (), "unresolved"),
                                  action=action, verified=verified, cell=(row, column),
                                  merged_anchor=(1, 0) if action == "continuation" else None))
        self.assertEqual(review_masks({1: page}, reviews), {1: [(20, 100, 260, 230)]})
        with tempfile.TemporaryDirectory() as directory:
            vault = Workspace(Path(directory) / "workspace.sqlite", "merged table test password", create=True)
            protected = export_review(vault, Path("scan.pdf"), "fixture", 250, reviews)
            document = next(iter(vault.documents.values()))
            csv = render_export(protected, "CSV", document["name"], document["text"])
            self.assertEqual(parse_csv(restore_csv(csv, vault.restore)[0])[1],
                             ["Merged confidential value", "", "2026-11-16"])
        with self.assertRaises(ValueError):
            RasterTable(1, grid.columns, grid.rows, ((1, 0, 1, 1), (1, 1, 1, 2)))

    def test_vertical_merge_keeps_other_cells_independent(self):
        grid = RasterTable(1, (0, 30, 60), (0, 40, 80), ((0, 0, 1, 0),))
        self.assertEqual(list(grid.cells())[:2], [(0, 0, (0, 0, 30, 80)), (0, 1, (30, 0, 60, 40))])
