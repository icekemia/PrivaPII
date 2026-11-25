"""Prepare reviewed exports and save an archive without source filenames."""

import re
from dataclasses import dataclass
from zipfile import ZIP_DEFLATED, ZipFile

from .export_formats import TEXT_FORMATS, csv_text, parse_csv, render_export
from .export_review import Residual, inspect_export, retained_identifiers
from .policy import selected_indices
from .detection import Span

BATCH_FORMATS = ("TXT", "Markdown")
FIELD_HEADER = ("client_id", "document_id", "field", "value")


def field_rows(text, fields, client_id, document_id):
    rows = []
    for field in fields:
        locations = field.locations(text)
        if len(locations) != 1:
            raise ValueError(f"Could not isolate the exported field {field.label}.")
        start, end = locations[0]
        value = text[start:end]
        if field.label.lstrip().startswith(("=", "+", "-", "@")) or (
            value.lstrip().startswith(("=", "+", "-", "@"))
            and not re.fullmatch(r"[+-][0-9]+(?:[.,][0-9]+)?", value)
        ):
            raise ValueError(f"{field.label}: value or label may be interpreted as a spreadsheet formula.")
        rows.append((client_id, document_id, field.label, value))
    return rows


@dataclass(frozen=True)
class BatchItem:
    source_name: str
    archive_name: str
    text: str
    token_count: int
    residuals: tuple[Residual, ...]


class Batch:
    def __init__(self, workspace, document_ids, categories, kind, *,
                 link_person_forms=False, groups=None, projections=None):
        formats = (*BATCH_FORMATS, "CSV") if projections else BATCH_FORMATS
        if kind not in formats or not document_ids or len(set(document_ids)) != len(document_ids):
            raise ValueError("Select distinct documents and a supported archive format.")
        self.workspace = workspace
        self.revision = workspace.revision
        self.staged = {}
        self.approved = set()
        self.kind = kind
        items = []
        for index, key in enumerate(document_ids, 1):
            document = workspace.documents[key]
            source, name = document["text"], document["name"]
            spans = [Span(item["start"], item["end"], item["label"], item.get("source", "manual"))
                     for item in document["occurrences"]]
            excluded = {spans[item] for item in document["excluded"]}
            selected = selected_indices(spans, categories, excluded)
            protected, pending = workspace.plan_transform(
                key, selected, link_person_forms=link_person_forms, staged=self.staged,
            )
            self.staged.update(pending)
            document_id = f"document-{index:03d}"
            client_id = f"client-{groups[key]:03d}" if groups else ""
            if kind == "CSV":
                rows = field_rows(protected, projections[key], client_id, document_id)
                rendered = csv_text([FIELD_HEADER, *rows])
                expected = "\n".join(row[-1] for row in rows)
            else:
                rendered = render_export(protected, kind, name)
                expected = protected
            retained = retained_identifiers(source, spans, selected)
            count, findings = inspect_export(rendered, kind, expected, retained)
            filename = f"{document_id}.csv" if kind == "CSV" else f"{document_id}{TEXT_FORMATS[kind]}"
            if client_id:
                filename = f"{client_id}/{filename}"
            items.append(BatchItem(name, filename,
                                   rendered, count, tuple(findings)))
        self.items = tuple(items)

    def approve(self, index, approved):
        if not 0 <= index < len(self.items):
            raise ValueError("Select a document in this batch.")
        if approved:
            self.approved.add(index)
        else:
            self.approved.discard(index)

    def write(self, path):
        if len(self.approved) != len(self.items):
            raise ValueError("Confirm every document before creating the archive.")
        if self.workspace.revision != self.revision:
            raise ValueError("The workspace changed. Prepare the archive again.")
        if path.suffix.lower() != ".zip":
            raise ValueError("Choose a .zip filename.")
        created = False
        try:
            with path.open("xb") as stream:
                created = True
                self.workspace.commit_references(self.staged)
                self.revision = self.workspace.revision
                with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
                    if self.kind == "CSV":
                        rows = [row for item in self.items for row in parse_csv(item.text)[1:]]
                        archive.writestr("fields.csv", csv_text([FIELD_HEADER, *rows]).encode("utf-8"))
                    else:
                        for item in self.items:
                            archive.writestr(item.archive_name, item.text.encode("utf-8"))
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
