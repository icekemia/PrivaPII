import tempfile
import unittest
from pathlib import Path

from export_formats import render_export
from privapii import TOKEN, Span
from vault import Workspace


class ExportFormatTests(unittest.TestCase):
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
