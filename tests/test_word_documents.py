import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from privapii.ingestion import extract
from privapii.detection import Span, TOKEN
from privapii.vault import Workspace
from privapii.word_documents import NS, extract_word, extract_word_tables, write_word


class WordDocumentTests(unittest.TestCase):
    def test_visible_body_preserves_list_numbers_and_omits_hidden_content(self):
        document = f"""<w:document xmlns:w="{NS}"><w:body>
            <w:p><w:r><w:t>Visible </w:t></w:r>
              <w:r><w:rPr><w:vanish/></w:rPr><w:t>HIDDEN_VALUE</w:t></w:r>
              <w:r><w:rPr><w:rStyle w:val="Inherited"/></w:rPr><w:t>STYLE_HIDDEN_VALUE</w:t></w:r>
              <w:del><w:r><w:delText>DELETED_VALUE</w:delText></w:r></w:del>
              <w:r><w:instrText>FIELD_CODE</w:instrText></w:r>
              <w:ins><w:r><w:t>prašymas</w:t></w:r></w:ins></w:p>
            <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr></w:pPr>
              <w:r><w:t>Pirmas</w:t></w:r></w:p>
            <w:p><w:pPr><w:pStyle w:val="NumberedFromStyle"/></w:pPr>
              <w:r><w:t>Kaip nurodyta 3 p.</w:t></w:r></w:p>
            </w:body></w:document>"""
        numbering = f"""<w:numbering xmlns:w="{NS}"><w:abstractNum w:abstractNumId="0">
            <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
            </w:abstractNum><w:num w:numId="2"><w:abstractNumId w:val="0"/>
            <w:lvlOverride w:ilvl="0"><w:startOverride w:val="3"/></w:lvlOverride>
            </w:num></w:numbering>"""
        styles = f"""<w:styles xmlns:w="{NS}">
            <w:style w:styleId="Hidden"><w:rPr><w:vanish/></w:rPr></w:style>
            <w:style w:styleId="Inherited"><w:basedOn w:val="Hidden"/></w:style>
            <w:style w:styleId="NumberedFromStyle"><w:pPr><w:numPr><w:numId w:val="2"/></w:numPr></w:pPr></w:style>
            </w:styles>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.docx"
            with ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document)
                archive.writestr("word/numbering.xml", numbering)
                archive.writestr("word/styles.xml", styles)
                archive.writestr("word/header1.xml", "HEADER_VALUE")
            self.assertEqual(extract(path), ("Visible prašymas\n3. Pirmas\n4. Kaip nurodyta 3 p.", 0))

    def test_fresh_word_package_and_restoration(self):
        original = "Vardas: Ąžuolas Žukas\nData: 2026-11-16\n"
        value = "Ąžuolas Žukas"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            password = "word output test password"
            path = root / "vault.sqlite"
            vault = Workspace(path, password, create=True)
            start = original.index(value)
            vault.review("word", "source.docx", original, [Span(start, start + len(value), "PER")])
            protected = vault.transform("word", [0])
            target = root / "out.docx"
            with target.open("wb") as stream:
                write_word(stream, protected)
            with ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()),
                                 {"[Content_Types].xml", "_rels/.rels", "word/document.xml"})
                self.assertNotIn(value.encode("utf-8"), archive.read("word/document.xml"))
            extracted = extract_word(target)
            self.assertEqual(TOKEN.findall(extracted), TOKEN.findall(protected))
            self.assertEqual(Workspace(path, password).restore(extracted), (original, 1))

    def test_word_table_preserves_rows_and_columns(self):
        rows = [["Data", "Kontaktas"], ["2026-11-16", 'Ona, "Austėja"']]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.docx"
            with path.open("wb") as stream:
                write_word(stream, "", rows)
            table, = extract_word_tables(path)
            self.assertEqual(table.rows, tuple(tuple(row) for row in rows))
            self.assertEqual(extract_word(path), table.tsv())
