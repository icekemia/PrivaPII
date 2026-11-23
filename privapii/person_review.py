"""Review evidence for person links within a single workspace."""

import unicodedata
from collections import defaultdict
from dataclasses import dataclass


def normalized(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


ENDINGS = {
    "as": ("o", "ui", "ą"),
    "is": ("io", "iui", "į"),
    "ys": ("io", "iui", "į"),
    "us": ("aus", "ui", "ų"),
    "ė": ("ės", "ei", "ę"),
    "a": ("os", "ai", "ą"),
}


def inflected_words(word):
    for ending, alternatives in ENDINGS.items():
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            stem = word[:-len(ending)]
            if ending in {"is", "ys"} and stem.endswith(("t", "d")):
                palatal = stem[:-1] + ("č" if stem.endswith("t") else "dž")
                return (palatal + alternatives[0], palatal + alternatives[1], stem + alternatives[2])
            return tuple(stem + ending for ending in alternatives)
    return ()


def name_variants(value):
    words = value.split()
    if len(words) != 2 or not all(word.isalpha() for word in words):
        return ()
    first, last = map(inflected_words, words)
    # Both parts must be attested in the same grammatical case.
    return tuple(" ".join(parts) for parts in zip(first, last))


@dataclass(frozen=True)
class Mention:
    occurrence_id: str
    entity_id: str
    document_name: str
    value: str
    context: str
    spelling_candidate: bool
    inflection_candidate: bool
    candidate_ids: tuple[str, ...]


def person_mentions(documents):
    entries = []
    spellings = defaultdict(list)
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
            spelling = normalized(value.strip(" \t\r\n.,;:"))
            spellings[spelling].append(occurrence)
            entries.append((occurrence, document["name"], value, context, spelling))
    inflections = defaultdict(set)
    for spelling in spellings:
        for variant in set(name_variants(spelling)) & spellings.keys():
            inflections[spelling].add(variant)
            inflections[variant].add(spelling)

    def related(item, spellings_to_check):
        return {other["id"] for spelling in spellings_to_check for other in spellings[spelling]
                if item["entity"] != other["entity"]}

    def mention(item, name, value, context, spelling):
        identical = related(item, [spelling])
        declined = related(item, inflections.get(spelling, ()))
        return Mention(item["id"], item["entity"], name, value, context,
                       bool(identical), bool(declined), tuple(sorted(identical | declined)))

    return [
        mention(item, name, value, context, spelling)
        for item, name, value, context, spelling in entries
    ]
