"""Local text detection, pseudonymization and case-scoped restoration."""

import re
import secrets
import zlib
from dataclasses import dataclass, field, replace
from datetime import date


@dataclass(frozen=True, order=True)
class Span:
    start: int
    end: int
    label: str
    source: str = field(default="manual", compare=False)
    confidence: float | None = field(default=None, compare=False)
    validation: str | None = field(default=None, compare=False)


EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w+])(?:\+370|00370|[08])(?:[ .-]*[0-9]){8}(?!\w)")
PERSONAL = re.compile(r"(?<!\w)[1-6][0-9]{10}(?!\w)")
IBAN = re.compile(r"(?<!\w)LT[0-9]{2}(?:[ -]?[0-9]{4}){4}(?!\w)", re.I)
PVM = re.compile(r"(?<!\w)LT[ \t]*(?:[0-9]{12}|[0-9]{9})(?!\w)", re.I)
COMPANY = re.compile(r"\b(?:įmonės|įstaigos|juridinio asmens|organizacijos)\s+kodas\s*[:=]?\s*([0-9]{9})(?!\w)", re.I)
TOKEN = re.compile(r"\[PRIVAPII_(?:V1|V2_[A-Z][A-Z0-9_]{0,31})_[0-9A-F]{32}_[0-9A-F]{8}\]")
TOKEN_START = re.compile(r"(?:\[\s*PRIVAPII\b|\bPRIVAPII[_-])", re.I)
DATE_VALUE = r"(?:\d{4}[-.]\d{1,2}[-.]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{4}|\d{4}\s*m\.\s*\S+\s+\d{1,2}\s*d\.)"
DOB = re.compile(r"\b(?:gimimo\s+data|gim\.|gimęs|gimusi)\s*[:=]?\s*(" + DATE_VALUE + r")(?!\d)", re.I)
REFERENCE_NUMBER = r"[0-9]{1,3}(?:\.[0-9]{1,3})*"
STRUCTURAL = (
    re.compile(r"^[ \t]*(" + REFERENCE_NUMBER + r")[.)](?=[ \t]|[^\W\d_]|$)", re.M),
    re.compile(r"\b(" + REFERENCE_NUMBER + r")[ \t]*(?:p\.(?!\w)|punkt\w*\b|papunkt\w*\b)", re.I),
    re.compile(r"\b(?:punkt\w*|papunkt\w*|punto|punti|point|paragraph|section)[ \t]+(" + REFERENCE_NUMBER + r")(?!\w|\.\d|[-/]\d)", re.I),
)


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


def valid_company_code(value):
    digits = list(map(int, value))
    first = sum(i * digit for i, digit in enumerate(digits[:-1], 1)) % 11
    second = sum(i * digit for i, digit in enumerate(digits[:-1], 3)) % 11
    return digits[-1] == (first if first < 10 else second % 10)


def rules(text):
    from stdnum.lt import pvm

    for pattern, label, validate in (
        (EMAIL, "EMAIL", None), (PHONE, "NUM_PHONE", None),
        (PERSONAL, "ID_PER", valid_personal_code), (IBAN, "IBAN", valid_iban),
        (PVM, "PVM", pvm.is_valid), (COMPANY, "COMPANY_ID", valid_company_code),
    ):
        for match in pattern.finditer(text):
            index = 1 if pattern is COMPANY else 0
            if validate is None or validate(match.group(index)):
                yield Span(*match.span(index), label, "rule",
                           validation="checksum passed" if validate else "format matched")


def hybrid(text, baseline=()):
    spans = {span: span for span in baseline}
    for candidate in rules(text):
        if candidate in spans:
            span = spans[candidate]
            spans[candidate] = replace(span, source="nus+rule", validation=candidate.validation)
        elif not any(
            span.label == candidate.label
            and span.start <= candidate.start and span.end >= candidate.end
            for span in spans
        ):
            spans[candidate] = candidate
    return sorted(spans.values())


def review_spans(text, findings):
    """Add explicit birth dates and remove automatic findings over document references."""
    structural = []
    for pattern in STRUCTURAL:
        for match in pattern.finditer(text):
            start, end = match.span()
            if end < len(text) and text[end:end + 1] in {".", ")"}:
                end += 1
            structural.append((start, end))
    structural.sort()
    birth_dates = [Span(*match.span(1), "DOB", "context-rule") for match in DOB.finditer(text)]
    retained = []
    for span in findings:
        start, end = span.start, span.end
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if span.source != "manual" and span.label == "DATE" and any(
            start < birth.end and end > birth.start for birth in birth_dates
        ):
            continue
        if span.source == "manual" or span.label not in {"VALUE", "ID_MISC", "NUM_CAR", "DATE"}:
            retained.append(span)
            continue
        cursor = span.start
        for left, right in structural:
            if right <= cursor or left >= span.end:
                continue
            if cursor < left:
                retain_fragment(retained, span, text, cursor, left)
            cursor = max(cursor, right)
        if cursor == span.start:
            retained.append(span)
        elif cursor < span.end:
            retain_fragment(retained, span, text, cursor, span.end)
    return sorted(set(retained + birth_dates))


def retain_fragment(retained, span, text, start, end):
    value = text[start:end]
    if any(char.isalnum() for char in value):
        retained.append(replace(span, start=start + len(value) - len(value.lstrip()),
                                end=start + len(value.rstrip())))


def canonical_token(body):
    return f"[{body}_{zlib.crc32(body.encode('ascii')):08X}]"


def token_prefix(spans, start, end):
    labels = {span.label for span in spans if start <= span.start and span.end <= end}
    structured = labels & {"DOB", "ID_PER", "EMAIL", "IBAN", "PVM", "COMPANY_ID", "NUM_PHONE"}
    chosen = structured if labels - structured <= {"ID_MISC", "VALUE", "MISC"} and structured else labels
    label = next(iter(chosen)) if len(chosen) == 1 else "MULTI"
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", label):
        label = "MANUAL"
    return f"PRIVAPII_V2_{label}_"


def merged_ranges(text, accepted):
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
    return ranges


def restore_references(text, references):
    matches = list(TOKEN.finditer(text))
    if TOKEN_START.search(TOKEN.sub("", text)):
        raise ValueError("Malformed or truncated PrivaPII token.")
    if any(match.group() not in references for match in matches):
        raise ValueError("Unknown, corrupted or foreign token.")
    return TOKEN.sub(lambda match: references[match.group()], text), len(matches)


class Case:
    """Ephemeral vault. Each export creates independent surface-form references."""

    def __init__(self):
        self._batches = {}

    def transform(self, text, accepted, *, redact=False):
        accepted = tuple(accepted)
        mapping = {}
        parts = []
        cursor = 0
        for start, end in merged_ranges(text, accepted):
            parts.append(text[cursor:start])
            token = "[REDACTED]"
            if not redact:
                prefix = token_prefix(accepted, start, end)
                token = canonical_token(prefix + secrets.token_hex(16).upper())
                while token in self._batches or token in mapping:
                    token = canonical_token(prefix + secrets.token_hex(16).upper())
                mapping[token] = text[start:end]
            parts.append(token)
            cursor = end
        parts.append(text[cursor:])
        self._batches.update(mapping)
        return "".join(parts)

    def restore(self, text):
        return restore_references(text, self._batches)
