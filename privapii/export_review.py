"""Local review of structured identifiers still present in a rendered export."""

import re
from collections import Counter
from dataclasses import dataclass

from .export_formats import parse_csv
from .detection import TOKEN, TOKEN_START, rules

MARKDOWN_ESCAPE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])")


@dataclass(frozen=True)
class Residual:
    category: str
    value: str
    intentionally_retained: bool


def retained_identifiers(source, findings, selected):
    accepted = set(selected)
    kept = [span for index, span in enumerate(findings) if index not in accepted]
    protected = [findings[index] for index in accepted]
    return Counter(
        (item.label, source[item.start:item.end])
        for item in rules(source)
        if any(span.start <= item.start and item.end <= span.end for span in kept)
        and not any(span.start < item.end and span.end > item.start for span in protected)
    )


def retained_transcriptions(texts):
    return Counter((span.label, text[span.start:span.end]) for text in texts for span in rules(text))


def inspect_export(rendered, kind, original_export, retained=()):
    expected = TOKEN.findall(original_export)
    tokens = TOKEN.findall(rendered)
    if tokens != expected or TOKEN_START.search(TOKEN.sub(" ", rendered)):
        raise ValueError("This format altered the restoration tokens. Choose another format.")

    if kind == "CSV":
        chunks = (cell for row in parse_csv(rendered) for cell in row)
    elif kind == "Markdown":
        chunks = (MARKDOWN_ESCAPE.sub(r"\1", rendered),)
    else:
        chunks = (rendered,)
    candidates = []
    for chunk in chunks:
        text = TOKEN.sub(" ", chunk)
        for span in rules(text):
            candidates.append((span.label, text[span.start:span.end]))
    visible_counts = Counter(candidates)
    known = dict(retained)
    return len(tokens), [
        Residual(category, value, visible_counts[(category, value)] <= known.get((category, value), 0))
        for category, value in candidates
    ]
