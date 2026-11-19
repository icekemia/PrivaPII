"""Extract reviewable rectangular tables from native PDF ruling lines."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PdfTable:
    page: int
    number: int
    rows: tuple[tuple[str, ...], ...]

    def tsv(self):
        return "\n".join("\t".join(row) for row in self.rows)


def complete_grid(rows):
    if len(rows) < 2 or len(rows[0].cells) < 2 or any(
        len(row.cells) != len(rows[0].cells) or any(cell is None for cell in row.cells) for row in rows
    ):
        return False
    columns = [(cell[0], cell[2]) for cell in rows[0].cells]
    close = lambda one, two: abs(one - two) <= 1
    if any(not close(left[1], right[0]) for left, right in zip(columns, columns[1:])):
        return False
    previous_bottom = None
    for row in rows:
        top, bottom = row.cells[0][1], row.cells[0][3]
        if previous_bottom is not None and not close(top, previous_bottom):
            return False
        if any(not (close(cell[0], column[0]) and close(cell[2], column[1])
                    and close(cell[1], top) and close(cell[3], bottom))
               for cell, column in zip(row.cells, columns)):
            return False
        previous_bottom = bottom
    return True


def extract_pdf_tables(path):
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError

    result = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for number, candidate in enumerate(page.find_tables(), 1):
                    if not complete_grid(candidate.rows):
                        continue
                    raw = candidate.extract()
                    if any(cell is None for row in raw for cell in row):
                        continue
                    rows = tuple(tuple(" ".join(cell.split()) for cell in row) for row in raw)
                    if any(cell for row in rows for cell in row):
                        result.append(PdfTable(page.page_number, number, rows))
                page.close()
    except PDFPasswordIncorrect as error:
        raise ValueError("Unlock the PDF before extracting tables.") from error
    except PDFSyntaxError as error:
        raise ValueError("The PDF could not be read.") from error
    return result
