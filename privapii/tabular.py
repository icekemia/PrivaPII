"""Find protected spans inside TSV cells without consuming table separators."""

import re
from pathlib import Path

from .export_formats import table_rows
from .detection import DATE_VALUE, Span

BIRTH_COLUMNS = {"gimimo data", "gim. data", "date of birth", "birth date"}
DATE_COLUMNS = {"data", "išdavimo data", "dokumento data", "date", "issue date", "document date"}
SAFE_HEADERS = BIRTH_COLUMNS | DATE_COLUMNS | {
    "vardas", "pavardė", "vardas ir pavardė", "kontaktas", "telefonas", "el. paštas",
    "asmens kodas", "iban",
}


def detect_table(text, detector):
    headers = table_rows(text, Path("table.tsv"))[0]
    findings, offset = [], 0
    header = True
    for raw in text.splitlines(keepends=True):
        line = raw.removesuffix("\n").removesuffix("\r")
        if line:
            start = offset
            for column, cell in enumerate(line.split("\t")):
                heading = headers[column].strip().casefold()
                if (not header and heading in BIRTH_COLUMNS | DATE_COLUMNS
                        and re.fullmatch(DATE_VALUE, cell.strip(), re.I)):
                    first = start + len(cell) - len(cell.lstrip())
                    end = start + len(cell.rstrip())
                    label = "DOB" if heading in BIRTH_COLUMNS else "DATE"
                    findings.append(Span(first, end, label, "table-header-rule"))
                elif cell.strip() and (not header or heading not in SAFE_HEADERS):
                    for span in detector(cell):
                        findings.append(Span(start + span.start, start + span.end, span.label,
                                             span.source, span.confidence, span.validation))
                start += len(cell) + 1
            header = False
        offset += len(raw)
    return findings
