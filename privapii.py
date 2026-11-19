"""Local text detection, pseudonymization and case-scoped restoration."""

import re
import secrets
import zlib
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, order=True)
class Span:
    start: int
    end: int
    label: str


EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w+])(?:\+370|00370|[08])(?:[ .-]*[0-9]){8}(?!\w)")
PERSONAL = re.compile(r"(?<!\w)[1-6][0-9]{10}(?!\w)")
IBAN = re.compile(r"(?<!\w)LT[0-9]{2}(?:[ -]?[0-9]{4}){4}(?!\w)", re.I)
TOKEN = re.compile(r"\[PRIVAPII_V1_[0-9A-F]{32}_[0-9A-F]{8}\]")
TOKEN_START = re.compile(r"\[?\s*PRIVAPII[_-]", re.I)


def valid_personal_code(value):
    century = 1800 + ((int(value[0]) - 1) // 2) * 100
    try:
        date(century + int(value[1:3]), int(value[3:5]), int(value[5:7]))
    except ValueError:
        return False
    digits = list(map(int, value))
    first = sum(a * b for a, b in zip(digits, (1, 2, 3, 4, 5, 6, 7, 8, 9, 1))) % 11
    second = sum(a * b for a, b in zip(digits, (3, 4, 5, 6, 7, 8, 9, 1, 2, 3))) % 11
    return digits[-1] == (first if first < 10 else second % 10)


def valid_iban(value):
    value = re.sub(r"[ -]", "", value.upper())
    return int(value[4:] + "2129" + value[2:4]) % 97 == 1


def rules(text):
    for pattern, label, validate in (
        (EMAIL, "EMAIL", None), (PHONE, "NUM_PHONE", None),
        (PERSONAL, "ID_PER", valid_personal_code), (IBAN, "IBAN", valid_iban),
    ):
        for match in pattern.finditer(text):
            if validate is None or validate(match.group()):
                yield Span(*match.span(), label)


def hybrid(text, baseline=()):
    spans = set(baseline)
    for candidate in rules(text):
        if not any(
            span.label == candidate.label
            and span.start <= candidate.start and span.end >= candidate.end
            for span in spans
        ):
            spans.add(candidate)
    return sorted(spans)


def canonical_token(body):
    return f"[{body}_{zlib.crc32(body.encode('ascii')):08X}]"


class Case:
    """Ephemeral vault. Each export creates independent surface-form references."""

    def __init__(self):
        self._batches = {}

    def transform(self, text, accepted, *, redact=False):
        if TOKEN_START.search(text):
            raise ValueError("Source contains reserved PrivaPII token syntax.")
        ranges = []
        for span in sorted(set(accepted)):
            if not 0 <= span.start < span.end <= len(text):
                raise ValueError("Invalid review span.")
            if ranges and span.start < ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], max(span.end, ranges[-1][1]))
            else:
                ranges.append((span.start, span.end))
        mapping = {}
        parts = []
        cursor = 0
        for start, end in ranges:
            parts.append(text[cursor:start])
            token = "[REDACTED]"
            if not redact:
                token = canonical_token("PRIVAPII_V1_" + secrets.token_hex(16).upper())
                while token in self._batches or token in mapping:
                    token = canonical_token("PRIVAPII_V1_" + secrets.token_hex(16).upper())
                mapping[token] = text[start:end]
            parts.append(token)
            cursor = end
        parts.append(text[cursor:])
        self._batches.update(mapping)
        return "".join(parts)

    def restore(self, text):
        matches = list(TOKEN.finditer(text))
        if TOKEN_START.search(TOKEN.sub("", text)):
            raise ValueError("Malformed or truncated PrivaPII token.")
        if any(match.group() not in self._batches for match in matches):
            raise ValueError("Unknown, corrupted or foreign token.")
        return TOKEN.sub(lambda match: self._batches[match.group()], text), len(matches)
