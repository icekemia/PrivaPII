"""Render outbound formats from the already protected text."""

import csv
import re
from io import StringIO
from pathlib import Path

from .detection import TOKEN

TEXT_FORMATS = {"TXT": ".txt", "Markdown": ".md", "CSV": ".csv", "Word": ".docx"}
NUMBERED = re.compile(r"^([ \t]*)([0-9]{1,3}(?:\.[0-9]{1,3})*)([.)])(?=\s|[^\W\d_]|$)")
SECTION = re.compile(r"^(?:[IVXLCDM]+|[0-9]{1,3})[ \t]+(?:SKYRIUS|DALIS)(?=$|[ \t:–—-])")
MARKDOWN_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()<>#|!~])")


def escape_markdown(text):
    parts, offset = [], 0
    for match in TOKEN.finditer(text):
        parts.append(MARKDOWN_PUNCTUATION.sub(r"\\\1", text[offset:match.start()]))
        parts.append(match.group())
        offset = match.end()
    parts.append(MARKDOWN_PUNCTUATION.sub(r"\\\1", text[offset:]))
    return "".join(parts)


def rectangular(rows):
    if not rows or len(rows[0]) < 2 or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("The table must have equally wide rows and at least two columns.")
    return rows


def table_rows(text, source_name):
    lines = text.strip("\r\n").splitlines()
    if Path(source_name).suffix.lower() in {".md", ".markdown"}:
        if (len(lines) < 3 or any(not (line.strip().startswith("|") and line.strip().endswith("|"))
                                 or r"\|" in line for line in lines)):
            raise ValueError("CSV export requires one complete Markdown pipe table.")
        rows = rectangular([tuple(cell.strip() for cell in line.strip()[1:-1].split("|"))
                            for line in lines])
        if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
            raise ValueError("The Markdown table needs a header separator.")
        return [rows[0], *rows[2:]]
    if len(lines) < 2 or any("\t" not in line for line in lines):
        raise ValueError("CSV export requires one complete tab-separated table.")
    return rectangular([tuple(line.split("\t")) for line in lines])


def csv_text(rows):
    output = StringIO(newline="")
    csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL).writerows(rows)
    return output.getvalue()


def parse_csv(text):
    try:
        return rectangular(list(csv.reader(StringIO(text, newline=""), strict=True)))
    except csv.Error as error:
        raise ValueError("The derived CSV is invalid.") from error


def restore_csv(text, restore, overrides=None):
    rows = parse_csv(text)
    output, offset = [], 0
    overrides = overrides or {}
    for row in rows:
        restored_row = []
        for cell in row:
            size = len(TOKEN.findall(cell))
            local = {index - offset: form for index, form in overrides.items()
                     if offset <= index < offset + size}
            restored, count = restore(cell, local)
            if count != size:
                raise ValueError("Some CSV references could not be restored.")
            restored_row.append(restored)
            offset += count
        output.append(restored_row)
    if any(index < 0 or index >= offset for index in overrides):
        raise ValueError("A selected CSV occurrence is no longer present.")
    return csv_text(output), offset


def render_export(text, format_name, source_name, source_text=None):
    if format_name == "TXT":
        return text
    if format_name == "CSV":
        if source_text is None:
            raise ValueError("CSV export requires the reviewed source table.")
        original = table_rows(source_text, source_name)
        protected = table_rows(text, source_name)
        if (len(original) != len(protected) or len(original[0]) != len(protected[0])
                or TOKEN.findall(text) != [token for row in protected for cell in row
                                          for token in TOKEN.findall(cell)]):
            raise ValueError("The export no longer matches the source table structure.")
        return csv_text(protected)
    if format_name != "Markdown":
        raise ValueError("Unknown export format.")
    if Path(source_name).suffix.lower() in {".md", ".markdown"}:
        return text

    lines = text.split("\n")
    rendered = []
    for index, plain in enumerate(lines):
        if not plain.strip():
            rendered.append("")
            continue
        if SECTION.match(plain.strip()):
            if rendered and rendered[-1]:
                rendered.append("")
            rendered.extend(("## " + escape_markdown(plain.strip()), ""))
            continue
        numbered = NUMBERED.match(plain)
        if numbered:
            indent, number, punctuation = numbered.groups()
            line = escape_markdown(indent + number) + "\\" + punctuation
            line += escape_markdown(plain[numbered.end():]).rstrip()
        else:
            line = escape_markdown(plain).rstrip()
            if re.match(r"^ {0,3}(?:[-+](?:[ \t]|$)|-{3,}$|={1,}$)", line):
                position = len(line) - len(line.lstrip())
                line = line[:position] + "\\" + line[position:]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if next_line.strip() and not SECTION.match(next_line.strip()):
            line += "  "
        rendered.append(line)
    return "\n".join(rendered)
