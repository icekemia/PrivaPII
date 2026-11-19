"""Review local OCR readings against image crops and export a protected TXT."""

import argparse
import hashlib
import tkinter as tk
from dataclasses import asdict, dataclass
from getpass import getpass
from pathlib import Path
from tkinter import messagebox, ttk

from nus import NusDetector
from ocr import Paddle, Region, Tesseract, align, raster_pages
from privapii import Span, hybrid, rules
from vault import Workspace, new_id


@dataclass
class Review:
    page: int
    size: tuple[int, int]
    region: Region
    categories: tuple[str, ...] = ()
    action: str = "mask"
    verified: str | None = None


def find_categories(reviews, detector):
    inputs = [" ".join(reading.text for reading in (item.region.primary or item.region.alternative))
              for item in reviews]
    text = "\n".join(inputs)
    spans = hybrid(text, detector(text))
    offset = 0
    for item, content in zip(reviews, inputs):
        labels = {span.label for span in spans
                  if span.start < offset + len(content) and span.end > offset}
        for reading in item.region.alternative:
            labels.update(span.label for span in rules(reading.text))
        item.categories = tuple(sorted(labels))
        offset += len(content) + 1


def export_review(workspace, source, source_digest, dpi, reviews):
    parts, approved, offset = [], [], 0
    for item in reviews:
        line = "[REDACTED]"
        if item.action in {"keep", "protect"}:
            if not item.verified or not item.verified.strip() or "\n" in item.verified or "\r" in item.verified:
                raise ValueError("A kept or restorable region needs a verified single-line transcription.")
            line = item.verified
            if item.action == "protect":
                label = item.categories[0] if len(item.categories) == 1 else "MANUAL"
                approved.append(Span(offset, offset + len(line), label, "ocr-human-verified"))
        elif item.action != "mask":
            raise ValueError("Unknown OCR review action.")
        parts.append(line)
        offset += len(line) + 1
    document_id = new_id()
    workspace.review(document_id, source.name, "\n".join(parts), approved)
    document = workspace.documents[document_id]
    document["ocr"] = {"source_sha256": source_digest, "dpi": dpi, "regions": []}
    occurrences = iter(document["occurrences"])
    for item in reviews:
        record = asdict(item)
        record["verification_status"] = "human_verified" if item.verified and item.action != "mask" else item.region.status
        if item.action == "protect":
            occurrence = next(occurrences)
            record.update(occurrence_id=occurrence["id"], entity_id=occurrence["entity"])
        document["ocr"]["regions"].append(record)
    try:
        return workspace.transform(document_id, list(range(len(approved))))
    except Exception:
        workspace.documents.pop(document_id)
        raise


class Reviewer:
    def __init__(self, root, pages, reviews):
        self.root, self.pages, self.reviews = root, pages, reviews
        self.index = 0
        self.confirmed = False
        self.value = tk.StringVar()
        self.details = tk.StringVar()
        root.title("PrivaPII · OCR review")
        ttk.Label(root, textvariable=self.details, wraplength=880).pack(padx=12, pady=6)
        self.crop = ttk.Label(root)
        self.crop.pack(padx=12, pady=6)
        ttk.Label(root, text="Transcribe the crop exactly before choosing a verified action.").pack()
        self.entry = ttk.Entry(root, textvariable=self.value, width=105)
        self.entry.pack(padx=12, pady=6)
        bar = ttk.Frame(root, padding=6)
        bar.pack()
        for caption, action in (
            ("Previous", lambda: self.move(-1)), ("Mask", lambda: self.decide("mask")),
            ("Keep verified", lambda: self.decide("keep")),
            ("Pseudonymize verified", lambda: self.decide("protect")),
            ("Next", lambda: self.move(1)), ("Finish", self.finish),
        ):
            ttk.Button(bar, text=caption, command=action).pack(side="left", padx=3)
        self.show()

    def show(self):
        from PIL import ImageTk

        item = self.reviews[self.index]
        region = item.region
        page = self.pages[item.page]
        left, top, right, bottom = region.box
        image = page.crop((max(0, left - 12), max(0, top - 12),
                           min(page.width, right + 12), min(page.height, bottom + 12)))
        image.thumbnail((900, 400))
        self.photo = ImageTk.PhotoImage(image)
        self.crop.configure(image=self.photo)
        primary = " / ".join(reading.text for reading in region.primary) or "—"
        alternative = " / ".join(reading.text for reading in region.alternative) or "—"
        labels = ", ".join(item.categories) or "—"
        self.details.set(
            f"Region {self.index + 1}/{len(self.reviews)} · page {item.page} · {region.status} · {item.action}\n"
            f"PP-OCRv6: {primary}\nTesseract: {alternative}\nPossible categories: {labels}"
        )
        self.value.set(item.verified or "")
        self.entry.focus_set()

    def move(self, delta):
        self.index = max(0, min(self.index + delta, len(self.reviews) - 1))
        self.show()

    def decide(self, action):
        value = self.value.get()
        if action != "mask" and not value.strip():
            messagebox.showerror("Transcription required", "Enter the value verified against the image.")
            return
        item = self.reviews[self.index]
        item.action, item.verified = action, value if action != "mask" else None
        self.move(1)

    def finish(self):
        if messagebox.askyesno("Finish local OCR review", "Export reviewed regions and mask every other recognized region?"):
            self.confirmed = True
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--model-dir", type=Path, default=Path("models"))
    parser.add_argument("--dpi", type=int, default=250, choices=range(150, 401, 50))
    args = parser.parse_args()
    if args.output.exists() or args.output.suffix.lower() != ".txt":
        parser.error("--output must be a new .txt file")
    if args.output.resolve() == args.workspace.resolve():
        parser.error("The text export and workspace must use different paths")
    passphrase = getpass("Workspace passphrase: ")
    if args.create and getpass("Confirm passphrase: ") != passphrase:
        parser.error("Passphrases do not match")
    workspace = Workspace(args.workspace, passphrase, create=args.create)
    paddle = Paddle(args.model_dir / "PP-OCRv6_medium_det", args.model_dir / "PP-OCRv6_medium_rec")
    tesseract = Tesseract(args.model_dir / "tesseract")
    detector = NusDetector(args.model_dir / "nus")
    pages, reviews = {}, []
    with args.source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    for page, image in raster_pages(args.source, args.dpi):
        pages[page] = image
        regions = align(paddle.read(image), tesseract.read(image))
        if not regions:
            regions = [Region((0, 0, image.width, image.height), (), (), "unresolved")]
        items = [Review(page, image.size, region) for region in regions]
        find_categories(items, detector)
        reviews.extend(items)
    if not reviews:
        parser.error("No pages were available for review")
    root = tk.Tk()
    review = Reviewer(root, pages, reviews)
    root.mainloop()
    if review.confirmed:
        output = export_review(workspace, args.source, digest, args.dpi, reviews)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output)


if __name__ == "__main__":
    main()
