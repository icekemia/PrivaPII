"""Extract local document text without modifying source files."""

from pathlib import Path


def extract(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8-sig"), 0
    if suffix != ".pdf":
        raise ValueError("Choose a TXT, Markdown or text-based PDF file.")

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        with path.open("rb") as stream:
            pdf = PdfReader(stream)
            if pdf.is_encrypted:
                raise ValueError("Encrypted PDF files must be unlocked before import.")
            pages = [page.extract_text() or "" for page in pdf.pages]
    except PdfReadError as error:
        raise ValueError("The PDF could not be read.") from error
    if not any(page.strip() for page in pages):
        raise ValueError("This PDF has no extractable text. OCR is not available in this prototype.")
    text = "\n\n".join(pages).replace("\r\n", "\n").replace("\r", "\n")
    return text, sum(not page.strip() for page in pages)
