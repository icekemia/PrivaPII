import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from privapii.batch_export import Batch
from privapii.document_templates import Field, Template, check_folders, read_form, save_template, stage_documents
from privapii.export_formats import parse_csv
from privapii.policy import ALL_CATEGORIES
from privapii.vault import Workspace


class DocumentTemplateTests(unittest.TestCase):
    def test_native_pdf_is_classified_and_a_blank_page_blocks_it(self):
        writer = PdfWriter()
        page = writer.add_blank_page(200, 100)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 10 70 Td (Account v1) Tj 0 -20 Td (Code: QA884) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        model = Template("account", "Account v1", (Field("Code", "ID_MISC"),))
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "account.pdf"
            writer.write(pdf)
            text = read_form(pdf)
            spans, _ = model.apply(text, detector=lambda _: ())
            self.assertEqual(text[spans[0].start:spans[0].end], "QA884")
            writer.add_blank_page(200, 100)
            writer.write(pdf)
            with self.assertRaisesRegex(ValueError, "without text"):
                read_form(pdf)

    def test_five_forms_require_complete_clients_and_restore_three_custom_fields(self):
        models = (
            Template("application", "Application v1", (Field("Gimimo data", "DOB"),
                                                       Field("Dokumento data", "DATE", keep=True))),
            Template("account", "Account v1", (Field("Kliento kodas", "ID_MISC"),)),
            Template("contract", "Contract v1", (Field("Pasirasantis asmuo", "PER"),)),
            Template("notice", "Notice v1", (Field("Reference", "ID_MISC"),)),
            Template("statement", "Statement v1", (Field("Reference", "ID_MISC"),)),
        )
        forms = (
            "Application v1\nGimimo data: 1968-04-07\nDokumento data: 2026-01-02",
            "Account v1\nKliento kodas: customer-QA884",
            "Contract v1\nPasirasantis asmuo: Ąžuolui Žvirbliui",
            "Notice v1\nReference: notice-Z6",
            "Statement v1\nReference: statement-P2",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete, blocked = root / "complete", root / "blocked"
            complete.mkdir()
            blocked.mkdir()
            for index, form in enumerate(forms):
                (complete / f"{index}.pdf").write_text(form, encoding="utf-8")
                altered = form.replace("Kliento kodas:", "Unexpected heading:")
                (blocked / f"{index}.pdf").write_text(altered, encoding="utf-8")
            with patch("privapii.document_templates.read_form", lambda path: path.read_text(encoding="utf-8")):
                groups, issues = check_folders((complete, blocked), models, detector=lambda _: ())
                partial, _ = check_folders((blocked,), models, allow_incomplete=True, detector=lambda _: ())
            self.assertEqual([len(group) for group in groups], [5])
            self.assertEqual([len(group) for group in partial], [4])
            self.assertIn("Kliento kodas: label missing", issues[0])
            password = "document template test passphrase"
            workspace = Workspace(root / "review.sqlite", password, create=True)
            for model in models:
                save_template(workspace, model)
            keys = stage_documents(workspace, groups[0])
            batch = Batch(workspace, keys, ALL_CATEGORIES, "TXT", groups=dict.fromkeys(keys, 1))
            for index, _ in enumerate(keys):
                batch.approve(index, True)
            output = root / "ready.zip"
            batch.write(output)
            with ZipFile(output) as archive:
                self.assertTrue(all(name.startswith("client-001/document-") for name in archive.namelist()))
                contents = [archive.read(name).decode() for name in archive.namelist()]
            for private in ("1968-04-07", "customer-QA884", "Ąžuolui Žvirbliui"):
                self.assertNotIn(private, "\n".join(contents))
            self.assertIn("2026-01-02", contents[0])
            reopened = Workspace(workspace.path, password)
            self.assertEqual([reopened.restore(text)[0] for text in contents], list(forms))
            self.assertEqual(Template.load(reopened.document_templates["application"][-1]), models[0])
            self.assertNotIn("1968-04-07", str(reopened.document_templates))
            projections = {key: [field for field in model.fields if field.label == "Dokumento data"]
                           for key, model in zip(keys, models)}
            csv_batch = Batch(workspace, keys, ALL_CATEGORIES, "CSV", projections=projections,
                              groups=dict.fromkeys(keys, 1))
            for index, _ in enumerate(keys):
                csv_batch.approve(index, True)
            csv_output = root / "fields.zip"
            csv_batch.write(csv_output)
            with ZipFile(csv_output) as archive:
                self.assertEqual(archive.namelist(), ["fields.csv"])
                rows = parse_csv(archive.read("fields.csv").decode())
            self.assertEqual(rows[1:], [["client-001", "document-001", "Dokumento data", "2026-01-02"]])

    def test_unknown_versions_and_repeated_or_empty_fields_block(self):
        model = Template("account", "Account v1", (Field("Code", "ID_MISC"),))
        for text, message in (
            ("Account v2\nCode: value", "heading"),
            ("Account v1\nCode:", "empty"),
            ("Account v1\nCode: A Other: B", "more than one colon"),
            ("Account v1\nCode: A\nCode: B", "repeated"),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                model.apply(text)
