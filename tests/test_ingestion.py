import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ingestion import extract, extract_with_coverage
from ocr import Region, Reading, fuse_native, native_pdf_readings
from privapii import rules


class IngestionTests(unittest.TestCase):
    def test_text_pdf_reports_empty_pages(self):
        writer = PdfWriter()
        page = writer.add_blank_page(100, 100)
        writer.add_blank_page(100, 100)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 10 10 Td (Text fixture) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        image = DecodedStreamObject()
        image.update({NameObject("/Subtype"): NameObject("/Image")})
        page["/Resources"][NameObject("/XObject")] = DictionaryObject({
            NameObject("/Im0"): writer._add_object(image),
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.pdf"
            with path.open("wb") as stream:
                writer.write(stream)
            text, empty = extract(path)
            self.assertIn("Text fixture", text)
            self.assertEqual(empty, 1)
            self.assertEqual(extract_with_coverage(path), (text, 1, (1,)))

    def test_local_structured_ids_and_invalid_checksums(self):
        text = "Įmonės kodas: 123456786; PVM LT 100001919017. Netinka LT100001919018."
        self.assertEqual([(span.label, text[span.start:span.end]) for span in rules(text)], [
            ("PVM", "LT 100001919017"), ("COMPANY_ID", "123456786"),
        ])

    def test_native_layer_is_review_evidence_at_raster_coordinates(self):
        import pypdfium2 as pdfium

        writer = PdfWriter()
        page = writer.add_blank_page(200, 100)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 10 Tf 10 30 Td (Native value) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.pdf"
            with path.open("wb") as stream:
                writer.write(stream)
            with pdfium.PdfDocument(path) as pdf:
                rendered = pdf[0]
                bitmap = rendered.render(scale=2)
                native, = native_pdf_readings(rendered, bitmap)
                bitmap.close()
                rendered.close()
        self.assertEqual(native.text, "Native value")
        self.assertGreaterEqual(native.box[0], 19)
        self.assertGreater(native.box[1], 100)
        original = Reading("OCR value", native.box, .8, "test")
        fused, = fuse_native([Region(native.box, (original,), (), "machine_read")], [native])
        self.assertEqual(fused.status, "review_with_native")
        self.assertEqual(fused.native, (native,))
        self.assertEqual(fuse_native([], [native])[0].status, "native_only")
