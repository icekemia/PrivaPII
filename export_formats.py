"""Render outbound formats from the already protected text."""

import re
from pathlib import Path

from privapii import TOKEN

TEXT_FORMATS = {"TXT": ".txt", "Markdown": ".md"}
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


def render_export(text, format_name, source_name):
    if format_name == "TXT":
        return text
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
