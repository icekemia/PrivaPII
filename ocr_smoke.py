"""Exercise both installed OCR engines and the verified vault on a synthetic scan."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from nus import NusDetector
from ocr import Paddle, Tesseract, align, raster_pages
from ocr_review import Review, export_review, find_categories
from vault import Workspace

LINES = (
    "Kontaktinis asmuo: Ąžuolas Žukas",
    "PVM: LT 100001919017",
    "El. paštas: demo@example.org",
)


def deny_network(event, _args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("The OCR smoke test attempted to access a network.")


def main():
    from PIL import Image, ImageDraw, ImageFont

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", default="C:/Windows/Fonts/arial.ttf")
    parser.add_argument("--models", type=Path, default=Path("models"))
    args = parser.parse_args()
    sys.addaudithook(deny_network)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        image = Image.new("RGB", (1300, 350), "white")
        font = ImageFont.truetype(args.font, 46)
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(LINES):
            draw.text((55, 35 + index * 92), line, font=font, fill="black")
        pdf = root / "synthetic_scan.pdf"
        image.save(pdf, resolution=150)
        _, raster = next(raster_pages(pdf))
        model = args.models
        paddle = Paddle(model / "PP-OCRv6_medium_det", model / "PP-OCRv6_medium_rec")
        tesseract = Tesseract(model / "tesseract")
        readings = []
        for engine in (paddle, tesseract):
            started = perf_counter()
            result = engine.read(raster)
            if not result:
                raise RuntimeError(f"{type(engine).__name__} returned no OCR lines.")
            exact = sum(any(reading.text == line for reading in result) for line in LINES)
            print(f"{type(engine).__name__}: {len(result)} lines, {exact}/{len(LINES)} exact, "
                  f"{perf_counter() - started:.2f} seconds", flush=True)
            readings.append(result)
        regions = align(*readings)
        print("Region states:", ", ".join(region.status for region in regions), flush=True)
        reviews = [Review(1, raster.size, region) for region in regions]
        find_categories(reviews, NusDetector(model / "nus"))
        selected = next(item for item in reviews if "PVM" in item.categories)
        selected.action, selected.verified = "protect", LINES[1]
        path = root / "workspace.sqlite"
        password = "synthetic-test passphrase"
        vault = Workspace(path, password, create=True)
        output = export_review(vault, pdf, "synthetic", 250, reviews)
        assert "100001919017" not in output and "example.org" not in output
        restored, count = Workspace(path, password).restore(output)
        assert count == 1 and LINES[1] in restored and "example.org" not in restored
        print("Verified OCR-to-vault restoration passed.")


if __name__ == "__main__":
    main()
