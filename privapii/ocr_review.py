"""Review local OCR readings against image crops and export a protected TXT."""

import argparse
import hashlib
import tkinter as tk
import unicodedata
from dataclasses import asdict, dataclass, replace
from getpass import getpass
from pathlib import Path
from tkinter import messagebox, ttk

from .nus import NusDetector
from .ocr import Paddle, Region, Tesseract, align, fuse_native, raster_evidence
from .tabular import detect_table
from .detection import Span, hybrid, review_spans, rules
from .vault import Workspace, new_id


@dataclass
class Review:
    page: int
    size: tuple[int, int]
    region: Region
    categories: tuple[str, ...] = ()
    action: str = "mask"
    verified: str | None = None
    cell: tuple[int, int] | None = None
    merged_anchor: tuple[int, int] | None = None


def find_categories(reviews, detector):
    inputs = [" ".join(reading.text for reading in (item.region.primary or item.region.alternative or item.region.native))
              for item in reviews]
    text = "\n".join(inputs)
    spans = review_spans(text, hybrid(text, detector(text)))
    offset = 0
    for item, content in zip(reviews, inputs):
        labels = {span.label for span in spans
                  if span.start < offset + len(content) and span.end > offset}
        for reading in (*item.region.alternative, *item.region.native):
            labels.update(span.label for span in rules(reading.text))
        item.categories = tuple(sorted(labels))
        offset += len(content) + 1


class ScanProcessor:
    """Reuse local recognition engines across a sequence of document imports."""

    def __init__(self, model_dir):
        self.paddle = Paddle(model_dir / "PP-OCRv6_medium_det", model_dir / "PP-OCRv6_medium_rec")
        self.tesseract = Tesseract(model_dir / "tesseract")

    def read(self, source, dpi, detector):
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        pages, reviews = {}, []
        for page, image, native in raster_evidence(source, dpi):
            pages[page] = image
            regions = fuse_native(align(self.paddle.read(image), self.tesseract.read(image)), native)
            if not regions:
                regions = [Region((0, 0, image.width, image.height), (), (), "unresolved")]
            items = [Review(page, image.size, region) for region in regions]
            find_categories(items, detector)
            reviews.extend(items)
        if not reviews:
            raise ValueError("No pages were available for review.")
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("The source changed during OCR. Import it again.")
        return pages, reviews, digest

    def read_table(self, image, table, detector):
        from PIL import ImageOps

        reviews, drafts = [], []
        for row, column, box in table.cells():
            merged = table.merge_at(row, column)
            if merged and (row, column) != merged[:2]:
                reviews.append(Review(table.page, image.size, Region(box, (), (), "merged_continuation"),
                                      action="continuation", cell=(row, column), merged_anchor=merged[:2]))
                drafts.append("")
                continue
            left, top, right, bottom = box
            crop = ImageOps.expand(image.crop((left + 3, top + 3, right - 3, bottom - 3)),
                                   border=8, fill="white")

            def position(readings):
                placed = []
                for reading in readings:
                    x0, y0, x1, y1 = reading.box
                    translated = (max(left, left + x0 - 5), max(top, top + y0 - 5),
                                  min(right, left + x1 - 5), min(bottom, top + y1 - 5))
                    if translated[0] < translated[2] and translated[1] < translated[3]:
                        placed.append(replace(reading, box=translated))
                return tuple(placed)

            primary = position(self.paddle.read(crop))
            alternate = position(self.tesseract.read(crop, single_cell=True))
            draft = " ".join(" ".join(item.text.split()) for item in primary)
            other = " ".join(" ".join(item.text.split()) for item in alternate)
            if primary and alternate:
                agreed = unicodedata.normalize("NFC", draft) == unicodedata.normalize("NFC", other)
                status = "cross_checked" if agreed else "unresolved"
            else:
                status = "machine_read" if primary or alternate else "unresolved"
            labels = {span.label for span in rules(other)}
            reviews.append(Review(table.page, image.size, Region(box, primary, alternate, status),
                                  tuple(sorted(labels)), cell=(row, column)))
            drafts.append(draft or other)

        width = table.shape[1]
        text = "\n".join("\t".join(drafts[i:i + width]) for i in range(0, len(drafts), width))
        candidates = detect_table(text, lambda cell: review_spans(cell, hybrid(cell, detector(cell))))
        offset = 0
        for item, draft in zip(reviews, drafts):
            detected = {span.label for span in candidates if span.start < offset + len(draft) and span.end > offset}
            item.categories = tuple(sorted(detected | set(item.categories)))
            offset += len(draft) + 1
        return reviews


def export_review(workspace, source, source_digest, dpi, reviews):
    parts, approved, offset = [], [], 0
    table = bool(reviews and reviews[0].cell is not None)
    if any((item.cell is not None) != table for item in reviews):
        raise ValueError("Cell review and line review must be exported separately.")
    if table:
        height = max(item.cell[0] for item in reviews) + 1
        width = max(item.cell[1] for item in reviews) + 1
        expected = [(row, column) for row in range(height) for column in range(width)]
        if ([item.cell for item in reviews] != expected or min(height, width) < 2
                or len({item.page for item in reviews}) != 1):
            raise ValueError("The reviewed cells do not form a complete table.")
        by_cell = {item.cell: item for item in reviews}
        for item in reviews:
            if (item.action == "continuation") != (item.merged_anchor is not None):
                raise ValueError("A merged continuation must point to its reviewed anchor.")
            if item.merged_anchor is not None:
                anchor = by_cell.get(item.merged_anchor)
                x0, y0, x1, y1 = item.region.box
                if (anchor is None or anchor.merged_anchor is not None
                        or not (anchor.region.box[0] <= x0 and anchor.region.box[1] <= y0
                                and anchor.region.box[2] >= x1 and anchor.region.box[3] >= y1)):
                    raise ValueError("A merged cell is outside the area covered by its anchor.")
    for index, item in enumerate(reviews):
        line = "[REDACTED]"
        if item.action in {"keep", "protect"}:
            if (not item.verified or not item.verified.strip()
                    or any(char in item.verified for char in "\n\r")
                    or (table and "\t" in item.verified)):
                raise ValueError("A kept or restorable region needs a verified single-line transcription.")
            line = item.verified
            if item.action == "protect":
                label = item.categories[0] if len(item.categories) == 1 else "MANUAL"
                approved.append(Span(offset, offset + len(line), label, "ocr-human-verified"))
        elif item.action in {"empty", "continuation"} and table:
            line = ""
        elif item.action != "mask":
            raise ValueError("Unknown OCR review action.")
        parts.append(line)
        offset += len(line)
        if index + 1 < len(reviews):
            parts.append("\t" if table and reviews[index + 1].cell[0] == item.cell[0] else "\n")
            offset += 1
    document_id = new_id()
    name = f"{source.stem}_p{reviews[0].page}_table.tsv" if table else source.name
    workspace.review(document_id, name, "".join(parts), approved)
    document = workspace.documents[document_id]
    document["ocr"] = {"source_sha256": source_digest, "dpi": dpi, "regions": []}
    occurrences = iter(document["occurrences"])
    for item in reviews:
        record = asdict(item)
        record["verification_status"] = item.region.status if item.action in {"mask", "continuation"} else "human_verified"
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
            *((("Keep empty", lambda: self.decide("empty")),) if reviews[0].cell is not None else ()),
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
        margin = 0 if item.cell is not None else 12
        image = page.crop((max(0, left - margin), max(0, top - margin),
                           min(page.width, right + margin), min(page.height, bottom + margin)))
        image.thumbnail((900, 400))
        self.photo = ImageTk.PhotoImage(image)
        self.crop.configure(image=self.photo)
        primary = " / ".join(reading.text for reading in region.primary) or "—"
        alternative = " / ".join(reading.text for reading in region.alternative) or "—"
        native = "\nPDF text layer: " + " / ".join(reading.text for reading in region.native) if region.native else ""
        labels = ", ".join(item.categories) or "—"
        position = f" · row {item.cell[0] + 1}, column {item.cell[1] + 1}" if item.cell is not None else ""
        if item.merged_anchor is not None:
            row, column = item.merged_anchor
            position += f" · continues row {row + 1}, column {column + 1}"
        self.details.set(
            f"Region {self.index + 1}/{len(self.reviews)} · page {item.page} · {region.status} · {item.action}\n"
            f"PP-OCRv6: {primary}\nTesseract: {alternative}{native}\nPossible categories: {labels}{position}"
        )
        self.value.set(item.verified or "")
        self.entry.focus_set()

    def move(self, delta):
        self.index = max(0, min(self.index + delta, len(self.reviews) - 1))
        self.show()

    def decide(self, action):
        value = self.value.get()
        item = self.reviews[self.index]
        if item.merged_anchor is not None:
            messagebox.showinfo("Merged cell", "Review the merged region from its top-left cell.")
            return
        if action in {"keep", "protect"} and not value.strip():
            messagebox.showerror("Transcription required", "Enter the value verified against the image.")
            return
        item.action, item.verified = action, value if action in {"keep", "protect"} else None
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
    processor = ScanProcessor(args.model_dir)
    pages, reviews, digest = processor.read(args.source, args.dpi, NusDetector(args.model_dir / "nus"))
    root = tk.Tk()
    review = Reviewer(root, pages, reviews)
    root.mainloop()
    if review.confirmed:
        output = export_review(workspace, args.source, digest, args.dpi, reviews)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output)


if __name__ == "__main__":
    main()
