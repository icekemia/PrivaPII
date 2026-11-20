"""Review evidence for person links within a single workspace."""

import unicodedata
from collections import defaultdict
from dataclasses import dataclass


def normalized(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


@dataclass(frozen=True)
class Mention:
    occurrence_id: str
    entity_id: str
    document_name: str
    value: str
    context: str
    spelling_candidate: bool


def person_mentions(documents):
    entries = []
    spelling_groups = defaultdict(set)
    for document in documents.values():
        text = document["text"]
        for occurrence in document["occurrences"]:
            if occurrence["label"] != "PER":
                continue
            start, end = occurrence["start"], occurrence["end"]
            value = text[start:end]
            left = text[max(0, start - 32):start]
            right = text[end:min(len(text), end + 32)]
            context = " ".join(f"{left} ‹{value}› {right}".split())
            spelling = normalized(value)
            spelling_groups[spelling].add(occurrence["entity"])
            entries.append((occurrence, document["name"], value, context, spelling))
    return [
        Mention(item["id"], item["entity"], name, value, context, len(spelling_groups[spelling]) > 1)
        for item, name, value, context, spelling in entries
    ]
