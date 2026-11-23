"""Local OCR engines and conservative alignment of page-coordinate readings."""

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Reading:
    text: str
    box: tuple[int, int, int, int]
    confidence: float | None
    engine: str


@dataclass(frozen=True)
class Region:
    box: tuple[int, int, int, int]
    primary: tuple[Reading, ...]
    alternative: tuple[Reading, ...]
    status: str
    native: tuple[Reading, ...] = ()


def raster_pages(path: Path, dpi=250):
    """Yield 1-based page numbers and RGB images in original raster coordinates."""
    for number, image, _ in raster_evidence(path, dpi, include_native=False):
        yield number, image


def raster_evidence(path: Path, dpi=250, *, include_native=True):
    from PIL import Image, ImageOps

    if path.suffix.lower() in {".png", ".jpeg", ".jpg", ".tiff", ".tif", ".bmp", ".webp"}:
        with Image.open(path) as image:
            for index in range(getattr(image, "n_frames", 1)):
                image.seek(index)
                yield index + 1, ImageOps.exif_transpose(image).convert("RGB"), ()
        return
    if path.suffix.lower() != ".pdf":
        raise ValueError("Choose a PDF or supported raster image.")
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(path) as document:
        for index in range(len(document)):
            page = document[index]
            try:
                bitmap = page.render(scale=dpi / 72)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    readings = native_pdf_readings(page, bitmap) if include_native else ()
                finally:
                    bitmap.close()
            finally:
                page.close()
            yield index + 1, image, readings


def native_pdf_readings(page, bitmap):
    textpage = page.get_textpage()
    converter = bitmap.get_posconv(page)
    readings = []
    try:
        for index in range(textpage.count_rects()):
            left, bottom, right, top = textpage.get_rect(index)
            text = textpage.get_text_bounded(left, bottom, right, top).strip()
            corners = [converter.to_bitmap(x, y) for x in (left, right) for y in (bottom, top)]
            xs, ys = zip(*corners)
            box = (max(0, min(xs)), max(0, min(ys)), min(bitmap.width, max(xs)), min(bitmap.height, max(ys)))
            if text and box[0] < box[2] and box[1] < box[3]:
                readings.append(Reading(text, box, None, "pdf-text-layer"))
    finally:
        textpage.close()
    return tuple(readings)


def fuse_native(regions, readings):
    """Attach a PDF reading to overlapping OCR evidence or create a review region."""
    from dataclasses import replace

    result = list(regions)
    for reading in readings:
        matches = [i for i, region in enumerate(result) if overlaps(region.box, reading.box)]
        if not matches:
            result.append(Region(reading.box, (), (), "native_only", (reading,)))
            continue
        merged = [result[i] for i in matches]
        boxes = [reading.box, *(region.box for region in merged)]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        combined = replace(merged[0], box=box,
                           primary=tuple(item for region in merged for item in region.primary),
                           alternative=tuple(item for region in merged for item in region.alternative),
                           native=(*[item for region in merged for item in region.native], reading),
                           status="review_with_native")
        result = [region for i, region in enumerate(result) if i not in matches]
        result.append(combined)
    return sorted(result, key=lambda region: (region.box[1], region.box[0]))


class Tesseract:
    def __init__(self, model_dir: Path):
        if not (model_dir / "lit.traineddata").is_file():
            raise ValueError("The local Tesseract Lithuanian language model is missing.")
        self.model_dir = model_dir

    def read(self, image, *, single_cell=False):
        from tesserocr import PSM, RIL, PyTessBaseAPI

        result = []
        mode = PSM.SINGLE_BLOCK if single_cell else PSM.AUTO
        with PyTessBaseAPI(path=str(self.model_dir.resolve()), lang="lit", psm=mode) as api:
            api.SetImage(image)
            api.Recognize()
            iterator = api.GetIterator()
            if iterator:
                while True:
                    box = iterator.BoundingBox(RIL.TEXTLINE)
                    try:
                        content = (iterator.GetUTF8Text(RIL.TEXTLINE) or "").strip() if box else ""
                    except RuntimeError as error:
                        if str(error) != "No text returned":
                            raise
                        content = ""
                    if box and content:
                        result.append(Reading(content, box, iterator.Confidence(RIL.TEXTLINE), "tesseract-lit"))
                    if not iterator.Next(RIL.TEXTLINE):
                        break
        return result


class Paddle:
    def __init__(self, detection_dir: Path, recognition_dir: Path):
        for directory in (detection_dir, recognition_dir):
            if not all((directory / file).is_file()
                       for file in ("inference.json", "inference.pdiparams", "inference.yml")):
                raise ValueError(f"Missing local PP-OCRv6 model files in {directory}.")
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddleocr import PaddleOCR

        self.engine = PaddleOCR(
            text_detection_model_name="PP-OCRv6_medium_det",
            text_recognition_model_name="PP-OCRv6_medium_rec",
            text_detection_model_dir=str(detection_dir.resolve()),
            text_recognition_model_dir=str(recognition_dir.resolve()),
            device="cpu", enable_mkldnn=False,
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def read(self, image):
        import numpy as np

        return [Reading(text, tuple(map(int, box)), float(score), "pp-ocrv6-medium")
                for result in self.engine.predict(np.asarray(image)[:, :, ::-1].copy())
                for text, box, score in zip(result["rec_texts"], result["rec_boxes"], result["rec_scores"])
                if text.strip()]


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def overlaps(a, b):
    intersection = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return area(intersection) >= 0.5 * min(area(a), area(b)) > 0


def align(primary, alternative):
    """Retain both engines' readings, including unmatched lines and split lines."""
    left, right = list(primary), list(alternative)
    regions = []
    while left or right:
        group_a = [left.pop(0)] if left else []
        group_b = [right.pop(0)] if not group_a else []
        while True:
            matches_a = [item for item in left if any(overlaps(item.box, other.box) for other in group_b)]
            matches_b = [item for item in right if any(overlaps(item.box, other.box) for other in group_a)]
            if not matches_a and not matches_b:
                break
            group_a.extend(matches_a)
            group_b.extend(matches_b)
            left = [item for item in left if item not in matches_a]
            right = [item for item in right if item not in matches_b]
        agree = len(group_a) == len(group_b) == 1 and unicodedata.normalize(
            "NFC", group_a[0].text) == unicodedata.normalize("NFC", group_b[0].text)
        boxes = [reading.box for reading in group_a + group_b]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        state = "cross_checked" if agree else "unresolved" if group_a and group_b else "machine_read"
        regions.append(Region(box, tuple(group_a), tuple(group_b), state))
    return sorted(regions, key=lambda region: (region.box[1], region.box[0]))
