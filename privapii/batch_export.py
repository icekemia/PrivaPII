"""Prepare reviewed exports and save an archive without source filenames."""

from dataclasses import dataclass
from zipfile import ZIP_DEFLATED, ZipFile

from .export_formats import TEXT_FORMATS, render_export
from .export_review import Residual, inspect_export, retained_identifiers
from .policy import selected_indices
from .detection import Span

BATCH_FORMATS = ("TXT", "Markdown")


@dataclass(frozen=True)
class BatchItem:
    source_name: str
    archive_name: str
    text: str
    token_count: int
    residuals: tuple[Residual, ...]


class Batch:
    def __init__(self, workspace, document_ids, categories, kind, *, link_person_forms=False):
        if kind not in BATCH_FORMATS or not document_ids or len(set(document_ids)) != len(document_ids):
            raise ValueError("Select distinct documents and a supported archive format.")
        self.workspace = workspace
        self.revision = workspace.revision
        self.staged = {}
        self.approved = set()
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
            rendered = render_export(protected, kind, name)
            retained = retained_identifiers(source, spans, selected)
            count, findings = inspect_export(rendered, kind, protected, retained)
            items.append(BatchItem(name, f"document-{index:03d}{TEXT_FORMATS[kind]}",
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
                    for item in self.items:
                        archive.writestr(item.archive_name, item.text.encode("utf-8"))
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
