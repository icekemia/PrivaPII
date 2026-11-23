import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from privapii.export_formats import parse_csv, render_export, restore_csv
from privapii.pdf_tables import complete_grid, extract_pdf_tables
from privapii.policy import PROFILES, selected_indices
from privapii.detection import Case, Span, rules
from privapii.tabular import detect_table


def write_table_pdf(path):
    writer = PdfWriter()
    page = writer.add_blank_page(360, 240)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    content = DecodedStreamObject()
    commands = [f"{x} 100 m {x} 160 l S" for x in (20, 130, 240, 350)]
    commands += [f"20 {y} m 350 {y} l S" for y in (100, 130, 160)]
    rows = (("Data", "Gimimo data", "Kontaktas"),
            ("2026-11-16", "1988-10-09", "fixture@example.org"))
    for cells, y in zip(rows, (145, 115)):
        commands += [f"BT /F1 10 Tf {x} {y} Td ({cell}) Tj ET"
                     for cell, x in zip(cells, (24, 134, 244))]
    commands.append("BT /F1 10 Tf 20 200 Td (Text outside the grid) Tj ET")
    content.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as stream:
        writer.write(stream)


class PdfTableTests(unittest.TestCase):
    def test_digital_table_extraction_and_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.pdf"
            write_table_pdf(path)
            table, = extract_pdf_tables(path)
        self.assertEqual(table.page, 1)
        expected = [["Data", "Gimimo data", "Kontaktas"],
                    ["2026-11-16", "1988-10-09", "fixture@example.org"]]
        self.assertEqual([list(row) for row in table.rows], expected)
        text = table.tsv()
        def noisy_detector(cell):
            if cell in {"Gimimo data", "2026-11-16"}:
                return [Span(0, len(cell), "ID_MISC", "nus")]
            return list(rules(cell))

        spans = detect_table(text, noisy_detector)
        indices = selected_indices(spans, PROFILES["Standard"], set())
        self.assertEqual([spans[index].label for index in indices], ["DOB", "EMAIL"])
        case = Case()
        outbound = render_export(case.transform(text, [spans[index] for index in indices]),
                                 "CSV", "table.tsv", text)
        self.assertNotIn("1988-10-09", outbound)
        self.assertNotIn("fixture@example.org", outbound)
        self.assertIn("2026-11-16", outbound)
        self.assertEqual(parse_csv(outbound)[0], expected[0])
        restored, count = restore_csv(outbound, lambda cell, _: case.restore(cell))
        self.assertEqual(count, 2)
        self.assertEqual(parse_csv(restored), expected)

    def test_rejects_merged_and_misaligned_cells(self):
        first = SimpleNamespace(cells=((0, 0, 10, 10), (10, 0, 20, 10)))
        merged = SimpleNamespace(cells=((0, 10, 20, 20), None))
        misaligned = SimpleNamespace(cells=((0, 10, 15, 20), (15, 10, 20, 20)))
        self.assertFalse(complete_grid([first, merged]))
        self.assertFalse(complete_grid([first, misaligned]))
