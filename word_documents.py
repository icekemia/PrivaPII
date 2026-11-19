"""Read visible Word body text and write fresh documents from reviewed text."""

from dataclasses import dataclass
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def word_tag(name):
    return f"{{{NS}}}{name}"


def child(element, name):
    return element.find(word_tag(name)) if element is not None else None


def value(element, default=None):
    return element.get(word_tag("val"), default) if element is not None else default


def hidden_properties(properties):
    flags = [child(properties, name) for name in ("vanish", "webHidden")]
    return any(flag is not None and value(flag) not in {"0", "false", "off"} for flag in flags)


class Visibility:
    def __init__(self, root):
        self.styles = {}
        self.defaults = {}
        self.default_hidden = False
        if root is not None:
            defaults = child(child(child(root, "docDefaults"), "rPrDefault"), "rPr")
            self.default_hidden = hidden_properties(defaults)
            self.styles = {element.get(word_tag("styleId")): element
                           for element in root.findall(word_tag("style"))}
            self.defaults = {element.get(word_tag("type")): identifier
                             for identifier, element in self.styles.items()
                             if element.get(word_tag("default")) in {"1", "true", "on"}}

    def chain(self, identifier):
        visited = set()
        while identifier in self.styles and identifier not in visited:
            style = self.styles[identifier]
            yield style
            visited.add(identifier)
            identifier = value(child(style, "basedOn"))

    def hidden(self, identifier):
        return any(hidden_properties(child(style, "rPr")) for style in self.chain(identifier))


def paragraph_text(paragraph, visibility):
    parts = []
    style = value(child(child(paragraph, "pPr"), "pStyle"), visibility.defaults.get("paragraph"))
    if visibility.default_hidden or visibility.hidden(style):
        return ""

    def read(element):
        tag = element.tag
        if tag in {word_tag(name) for name in ("del", "moveFrom", "drawing", "object", "pict", "pPr", "rPr")}:
            return
        if tag == word_tag("r"):
            properties = child(element, "rPr")
            style = value(child(properties, "rStyle"), visibility.defaults.get("character"))
            if hidden_properties(properties) or visibility.hidden(style):
                return
        if tag == word_tag("t"):
            parts.append(element.text or "")
        elif tag == word_tag("tab"):
            parts.append("\t")
        elif tag in {word_tag("br"), word_tag("cr")}:
            parts.append("\n")
        else:
            for nested in element:
                read(nested)

    read(paragraph)
    return "".join(parts)


def blocks(container):
    for element in container:
        if element.tag in {word_tag("p"), word_tag("tbl")}:
            yield element
        elif element.tag in {word_tag(name) for name in ("sdt", "sdtContent", "ins", "moveTo")}:
            yield from blocks(element)


class Numbering:
    def __init__(self, root):
        self.abstract, self.instances, self.counters = {}, {}, {}
        if root is None:
            return
        for abstract in root.findall(word_tag("abstractNum")):
            levels = {}
            for level in abstract.findall(word_tag("lvl")):
                levels[int(level.get(word_tag("ilvl"), "0"))] = (
                    value(child(level, "numFmt"), "decimal"),
                    value(child(level, "lvlText"), "%1."),
                    int(value(child(level, "start"), "1")),
                )
            self.abstract[abstract.get(word_tag("abstractNumId"))] = levels
        for instance in root.findall(word_tag("num")):
            overrides = {}
            for override in instance.findall(word_tag("lvlOverride")):
                start = child(override, "startOverride")
                if start is not None:
                    overrides[int(override.get(word_tag("ilvl"), "0"))] = int(value(start))
            abstract_id = value(child(instance, "abstractNumId"))
            self.instances[instance.get(word_tag("numId"))] = self.abstract.get(abstract_id, {}), overrides

    def prefix(self, paragraph, visibility):
        paragraph_properties = child(paragraph, "pPr")
        identifier = value(child(paragraph_properties, "pStyle"), visibility.defaults.get("paragraph"))
        properties = [child(paragraph_properties, "numPr")]
        properties.extend(child(child(style, "pPr"), "numPr") for style in visibility.chain(identifier))
        number_id = next((value(child(item, "numId")) for item in properties if child(item, "numId") is not None), None)
        level = int(next((value(child(item, "ilvl")) for item in properties if child(item, "ilvl") is not None), "0"))
        levels, overrides = self.instances.get(number_id, ({}, {}))
        if level not in levels:
            return ""
        format_name, template, start = levels[level]
        counters = self.counters.setdefault(number_id, {})
        counters[level] = counters.get(level, overrides.get(level, start) - 1) + 1
        for nested in tuple(counters):
            if nested > level:
                del counters[nested]
        if format_name == "bullet":
            return "• "
        if format_name not in {"decimal", "decimalZero"}:
            return ""
        for index in range(9):
            kind, _, initial = levels.get(index, ("decimal", "", 1))
            item = counters.get(index, overrides.get(index, initial))
            label = f"{item:02d}" if kind == "decimalZero" else str(item)
            template = template.replace(f"%{index + 1}", label)
        return template + " "


@dataclass(frozen=True)
class WordTable:
    number: int
    rows: tuple[tuple[str, ...], ...]

    def tsv(self):
        return "\n".join("\t".join(row) for row in self.rows)


def read_word(path):
    try:
        with ZipFile(path) as archive:
            members = set(archive.namelist())
            root = ET.fromstring(archive.read("word/document.xml"))
            numbering = Numbering(ET.fromstring(archive.read("word/numbering.xml"))
                                  if "word/numbering.xml" in members else None)
            visibility = Visibility(ET.fromstring(archive.read("word/styles.xml"))
                                    if "word/styles.xml" in members else None)
    except (BadZipFile, KeyError, ET.ParseError, ValueError, RuntimeError) as error:
        raise ValueError("The Word document could not be read.") from error
    body = child(root, "body")
    if body is None:
        raise ValueError("The Word file does not contain a supported document body.")
    return body, numbering, visibility


def read_rows(table, visibility):
    rows = []
    rectangular = True
    for row in table.findall(word_tag("tr")):
        values = []
        for cell in row.findall(word_tag("tc")):
            properties = child(cell, "tcPr")
            if (value(child(properties, "gridSpan"), "1") != "1"
                    or child(properties, "vMerge") is not None or child(properties, "hMerge") is not None
                    or any(nested.tag == word_tag("tbl") for nested in blocks(cell))):
                rectangular = False
            elements = []
            for item in blocks(cell):
                if item.tag == word_tag("p"):
                    elements.append(paragraph_text(item, visibility))
                else:
                    nested_rows, _ = read_rows(item, visibility)
                    elements.extend(" ".join(nested) for nested in nested_rows)
            values.append(" ".join(" ".join(elements).split()))
        rows.append(tuple(values))
    rectangular = (rectangular and len(rows) >= 2 and len(rows[0]) >= 2
                   and all(len(row) == len(rows[0]) for row in rows))
    return tuple(rows), rectangular


def extract_word(path):
    body, numbering, visibility = read_word(path)
    parts = []
    for element in blocks(body):
        if element.tag == word_tag("p"):
            parts.append(numbering.prefix(element, visibility) + paragraph_text(element, visibility))
        else:
            rows, _ = read_rows(element, visibility)
            parts.extend("\t".join(row) for row in rows)
    return "\n".join(parts)


def extract_word_tables(path):
    body, _, visibility = read_word(path)
    tables = []
    number = 0
    for element in blocks(body):
        if element.tag == word_tag("tbl"):
            number += 1
            rows, rectangular = read_rows(element, visibility)
            if rectangular:
                tables.append(WordTable(number, rows))
    return tables


CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
RELATIONSHIPS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def append_paragraph(container, text):
    paragraph = ET.SubElement(container, word_tag("p"))
    run = ET.SubElement(paragraph, word_tag("r"))
    for index, segment in enumerate(text.split("\t")):
        if index:
            ET.SubElement(run, word_tag("tab"))
        ET.SubElement(run, word_tag("t"), {XML_SPACE: "preserve"}).text = segment


def write_word(stream, text, rows=None):
    document = ET.Element(word_tag("document"))
    body = ET.SubElement(document, word_tag("body"))
    if rows is None:
        for line in text.split("\n"):
            append_paragraph(body, line)
    else:
        table = ET.SubElement(body, word_tag("tbl"))
        properties = ET.SubElement(table, word_tag("tblPr"))
        ET.SubElement(properties, word_tag("tblW"), {word_tag("w"): "0", word_tag("type"): "auto"})
        grid = ET.SubElement(table, word_tag("tblGrid"))
        width = str(9000 // len(rows[0]))
        for _ in rows[0]:
            ET.SubElement(grid, word_tag("gridCol"), {word_tag("w"): width})
        for row in rows:
            tr = ET.SubElement(table, word_tag("tr"))
            for cell in row:
                tc = ET.SubElement(tr, word_tag("tc"))
                cell_properties = ET.SubElement(tc, word_tag("tcPr"))
                ET.SubElement(cell_properties, word_tag("tcW"), {word_tag("w"): width, word_tag("type"): "dxa"})
                for line in cell.split("\n"):
                    append_paragraph(tc, line)
    payload = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELATIONSHIPS)
        archive.writestr("word/document.xml", payload)
