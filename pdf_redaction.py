"""Build a fresh, image-only PDF from reviewed and masked page rasters."""

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)


def clamp_box(box, size, padding=0):
    x0, y0, x1, y1 = box
    width, height = size
    if x0 >= x1 or y0 >= y1:
        raise ValueError("The redaction area must have positive width and height.")
    clipped = (max(0, x0 - padding), max(0, y0 - padding),
               min(width, x1 + padding), min(height, y1 + padding))
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        raise ValueError("The redaction area falls outside its page.")
    return clipped


def masked_page(image, boxes):
    from PIL import ImageDraw

    raster = image.convert("RGB")
    draw = ImageDraw.Draw(raster)
    for box in boxes:
        x0, y0, x1, y1 = clamp_box(box, raster.size)
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill="black")
    return raster


def review_masks(pages, reviews, padding=12):
    result = {number: [] for number in pages}
    for item in reviews:
        if item.action in {"protect", "mask"}:
            image = pages[item.page]
            result[item.page].append(clamp_box(item.region.box, image.size, padding))
        elif item.action != "keep":
            raise ValueError("Unknown OCR review action.")
    return result


def write_redacted_pdf(stream, pages, masks, *, dpi):
    """Write only sanitized RGB bytes and minimal drawing commands to a new PDF."""
    if not pages or dpi <= 0 or pages.keys() != masks.keys():
        raise ValueError("Each output page needs a mask set and a valid resolution.")
    writer = PdfWriter()
    writer.metadata = None
    for number in sorted(pages):
        raster = masked_page(pages[number], masks[number])
        width, height = (dimension * 72 / dpi for dimension in raster.size)
        page = writer.add_blank_page(width, height)
        image = DecodedStreamObject()
        image.set_data(raster.tobytes())
        image.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(raster.width),
            NameObject("/Height"): NumberObject(raster.height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        })
        compressed = image.flate_encode()
        compressed.update({key: value for key, value in image.items() if key != "/Length"})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({
                NameObject("/Im0"): writer._add_object(compressed),
            }),
        })
        drawing = DecodedStreamObject()
        drawing.set_data(f"q {width:.6f} 0 0 {height:.6f} 0 0 cm /Im0 Do Q\n".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(drawing)
    writer.write(stream)
