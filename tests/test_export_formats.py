import tempfile
import unittest
from pathlib import Path

from export_formats import parse_csv, render_export, restore_csv
from privapii import TOKEN, Span
from vault import Workspace


class ExportFormatTests(unittest.TestCase):
    def test_markdown_table_csv_round_trip_preserves_quoted_values(self):
        original = '| Data | Vardas |\n| --- | --- |\n| 2026-11-16 | Ona, "Austėja" |'
        value = 'Ona, "Austėja"'
        start = original.index(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.sqlite"
            password = "csv restoration sample"
            vault = Workspace(path, password, create=True)
            vault.review("table", "source.md", original, [Span(start, start + len(value), "PER")])
            masked = vault.transform("table", [0])
            exported = render_export(masked, "CSV", "source.md", original)
            self.assertEqual(TOKEN.findall(exported), TOKEN.findall(masked))
            self.assertEqual(parse_csv(exported)[1][0], "2026-11-16")
            restored, count = restore_csv(exported, Workspace(path, password).restore)
            self.assertEqual(count, 1)
            self.assertEqual(parse_csv(restored), [["Data", "Vardas"], ["2026-11-16", value]])

    def test_csv_rejects_unverifiable_structure(self):
        tsv = "Date\tName\n2026-11-16\tJonas"
        self.assertEqual(parse_csv(render_export(tsv, "CSV", "source.tsv", tsv))[1],
                         ["2026-11-16", "Jonas"])
        for broken in ("Date\tName\n2026-11-16 Jonas", "Date\tName", "Date\tName\nno separator"):
            with self.assertRaises(ValueError):
                render_export(broken, "CSV", "source.tsv", tsv)
        with self.assertRaises(ValueError):
            render_export("Prose", "CSV", "source.pdf", "Prose")
        with self.assertRaises(ValueError):
            parse_csv('"unterminated,field')

    def test_csv_form_override_targets_one_cell(self):
        from privapii import Case

        case = Case()
        token = case.transform("Jonas", [Span(0, 5, "PER")])

        def restore(cell, overrides):
            restored, count = case.restore(cell)
            return overrides.get(0, restored), count

        result, count = restore_csv(f'A,B\n{token},{token}', restore, {1: 'Jono, „forma“'})
        self.assertEqual(parse_csv(result), [["A", "B"], ["Jonas", "Jono, „forma“"]])
        self.assertEqual(count, 2)

    def test_preserves_existing_markdown_and_plain_text(self):
        content = "# Sąlygos\n\n3. Pirmas\n7. Antras\n"
        self.assertEqual(render_export(content, "TXT", "fixture.pdf"), content)
        self.assertEqual(render_export(content, "Markdown", "fixture.Markdown"), content)

    def test_formats_extracted_text_with_literal_clause_numbers(self):
        text = "I SKYRIUS\n3. Sąlyga\n3.2) Kita sąlyga\n7. Žr. 3.2 p.\n"
        formatted = render_export(text, "Markdown", "fixture.pdf")
        self.assertEqual(formatted, "## I SKYRIUS\n\n3\\. Sąlyga  \n"
                         "3.2\\) Kita sąlyga  \n7\\. Žr. 3.2 p.\n")

    def test_reordered_markdown_tokens_restore_from_reopened_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.sqlite"
            password = "markdown restoration sample"
            vault = Workspace(path, password, create=True)
            protected = []
            for key, line in (("a", "3. Austėja"), ("b", "7. Jono")):
                vault.review(key, f"{key}.pdf", line, [Span(3, len(line), "PER")])
                masked = vault.transform(key, [0])
                formatted = render_export(masked, "Markdown", f"{key}.pdf")
                self.assertEqual(TOKEN.findall(formatted), TOKEN.findall(masked))
                protected.append(formatted)
            derived = "\n\n".join(reversed(protected))
            self.assertEqual(Workspace(path, password).restore(derived),
                             ("7\\. Jono\n\n3\\. Austėja", 2))
