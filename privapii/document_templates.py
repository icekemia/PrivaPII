"""Apply reviewed field rules to native-text PDF forms."""

import re
from dataclasses import asdict, dataclass

from .detection import Span, hybrid
from .ingestion import extract_with_coverage
from .policy import ALL_CATEGORIES
from .vault import new_id


@dataclass(frozen=True)
class Field:
    label: str
    category: str
    keep: bool = False
    allow_empty: bool = False

    def __post_init__(self):
        if not self.label.strip() or any(char in self.label for char in ":\r\n"):
            raise ValueError("Select a printed field label before the colon.")
        if self.category not in ALL_CATEGORIES:
            raise ValueError("Choose a supported category.")

    def locations(self, text):
        words = r"[^\S\n]+".join(re.escape(word) for word in self.label.split())
        pattern = rf"^[^\S\n]*{words}[^\S\n]*:[^\S\n]*(?P<value>[^\n]*)$"
        return [(match.start("value"), match.start("value") + len(match["value"].rstrip()))
                for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE)]


@dataclass(frozen=True)
class Template:
    name: str
    heading: str
    fields: tuple[Field, ...]
    version: int = 1

    def __post_init__(self):
        if not self.name.strip() or not self.heading.strip() or "\n" in self.heading:
            raise ValueError("Enter a model name and select one printed heading.")
        labels = [" ".join(field.label.casefold().split()) for field in self.fields]
        if not labels or len(labels) != len(set(labels)) or all(field.keep for field in self.fields):
            raise ValueError("Add unique field labels and at least one field to protect.")

    def matches(self, text):
        return sum(line.strip() == self.heading.strip() for line in text.splitlines()) == 1

    def apply(self, text, detector=hybrid):
        if not self.matches(text):
            raise ValueError("The approved heading is missing or repeated.")
        scoped = []
        errors = []
        for field in self.fields:
            positions = field.locations(text)
            if len(positions) != 1:
                errors.append(f"{field.label}: {'label missing' if not positions else 'label repeated'}")
                continue
            start, end = positions[0]
            if ":" in text[start:end]:
                errors.append(f"{field.label}: more than one colon on the field line")
                continue
            if start == end:
                if not field.allow_empty:
                    errors.append(f"{field.label}: required value is empty")
                continue
            scoped.append((field, Span(start, end, field.category, "manual")))
        if errors:
            raise ValueError("\n".join(errors))
        general = [span for span in detector(text)
                   if not any(rule.start <= span.start and span.end <= rule.end for _, rule in scoped)]
        if any(span.start < rule.end and rule.start < span.end
               for _, rule in scoped for span in general):
            raise ValueError("A finding crosses a field boundary. Review the source and model.")
        spans = sorted(set(general + [span for _, span in scoped]))
        excluded = [spans.index(span) for field, span in scoped if field.keep]
        return spans, excluded

    @classmethod
    def load(cls, record):
        return cls(record["name"], record["heading"], tuple(Field(**item) for item in record["fields"]),
                   record["version"])


def read_form(path):
    if path.suffix.lower() != ".pdf":
        raise ValueError("Choose a PDF with selectable text.")
    text, empty, mixed = extract_with_coverage(path)
    if empty or mixed:
        raise ValueError("Pages without text or with embedded images need separate review.")
    return text


def save_template(workspace, template):
    previous = workspace.document_templates
    workspace.document_templates = {
        **previous, template.name: [*previous.get(template.name, []), asdict(template)],
    }
    try:
        workspace.save()
    except Exception:
        workspace.document_templates = previous
        raise


def check_folders(folders, templates, *, allow_incomplete=False, detector=hybrid):
    ready, issues = [], []
    for folder in folders:
        by_type = {}
        problem = False
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() != ".pdf":
                continue
            try:
                content = read_form(path)
                matches = [template for template in templates if template.matches(content)]
                if len(matches) != 1:
                    raise ValueError("Unknown or ambiguous document model.")
                template = matches[0]
                by_type.setdefault(template.name, []).append((path, content, template))
            except (OSError, ValueError) as error:
                issues.append(f"{folder.name} / {path.name} — {error}")
                problem = True
        candidates = []
        for template in templates:
            files = by_type.get(template.name, [])
            if len(files) != 1:
                issues.append(f"{folder.name} — {template.name}: "
                              f"{'required document missing' if not files else 'multiple matching documents'}")
                problem = True
                continue
            path, content, _ = files[0]
            try:
                spans, excluded = template.apply(content, detector)
                candidates.append((path, content, spans, excluded, template.fields))
            except ValueError as error:
                issues.append(f"{folder.name} / {path.name} — {error}")
                problem = True
        if candidates and (not problem or allow_incomplete):
            ready.append(candidates)
    return ready, issues


def stage_documents(workspace, ready):
    keys = []
    try:
        for path, content, spans, excluded, _ in ready:
            key = new_id()
            keys.append(key)
            workspace.review(key, path.name, content, spans, excluded)
    except Exception:
        for key in keys:
            workspace.documents.pop(key, None)
        raise
    return keys
