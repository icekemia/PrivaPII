import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

from ocr import Reading, align, raster_pages
from ocr_review import Review
from pdf_redaction import clamp_box, review_masks, write_redacted_pdf


class PdfRedactionTests(unittest.TestCase):
    def test_discards_source_objects_and_replaces_sensitive_pixels(self):
        dpi = 72
        original = Image.new("RGB", (100, 80), (240, 230, 180))
        original.paste((220, 20, 25), (10, 20, 30, 40))
        raw = BytesIO()
        write_redacted_pdf(raw, {1: original}, {1: []}, dpi=dpi)
        source = PdfWriter(clone_from=raw)
        source.add_metadata({"/Title": "PRIVATE_METADATA_MARKER"})
        source.add_attachment("PRIVATE_ATTACHMENT_MARKER.txt", b"PRIVATE_ATTACHMENT_CONTENT")
        page = source.pages[0]
        source.add_annotation(0, Text(rect=(70, 10, 80, 20), text="PRIVATE_ANNOTATION_MARKER"))
        source.root_object[NameObject("/AcroForm")] = DictionaryObject({
            NameObject("/Fields"): ArrayObject(),
        })
        page["/Resources"][NameObject("/Font")] = DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        })
        content = DecodedStreamObject()
        content.set_data(page.get_contents().get_data() +
                         b"BT /F1 10 Tf 3 Tr 5 15 Td (PRIVATE_STREAM_MARKER) Tj ET\n")
        page[NameObject("/Contents")] = source._add_object(content)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, output_path = root / "input.pdf", root / "output.pdf"
            with input_path.open("wb") as stream:
                source.write(stream)
            self.assertIn("PRIVATE_STREAM_MARKER", PdfReader(input_path).pages[0].extract_text())
            pages = dict(raster_pages(input_path, dpi))
            with output_path.open("wb") as stream:
                write_redacted_pdf(stream, pages, {1: [(10, 20, 30, 40)]}, dpi=dpi)
            out = PdfReader(output_path)
            self.assertEqual(out.pages[0].extract_text(), "")
            self.assertIsNone(out.metadata)
            self.assertEqual(dict(out.attachments), {})
            self.assertNotIn("/Annots", out.pages[0])
            self.assertNotIn("/AcroForm", out.root_object)
            self.assertNotIn(b"PRIVATE_STREAM_MARKER", out.pages[0].get_contents().get_data())
            self.assertEqual(len(out.pages[0].images), 1)
            raster = out.pages[0].images[0].image
            self.assertEqual(raster.crop((10, 20, 30, 40)).getextrema(), ((0, 0),) * 3)
            self.assertEqual(raster.getpixel((9, 19)), (240, 230, 180))
            self.assertEqual(pages[1].getpixel((15, 25)), (220, 20, 25))

    def test_mask_policy_pads_protected_and_unresolved_regions_only(self):
        page = Image.new("RGB", (60, 60))
        reading = Reading("Example", (0, 2, 20, 10), 0.99, "test")
        region, = align([reading], [])
        reviews = [Review(1, page.size, region), Review(2, page.size, region, action="protect"),
                   Review(3, page.size, region, action="keep")]
        self.assertEqual(review_masks({1: page, 2: page, 3: page}, reviews),
                         {1: [(0, 0, 32, 22)], 2: [(0, 0, 32, 22)], 3: []})
        with self.assertRaises(ValueError):
            clamp_box((100, 100, 130, 140), page.size)
