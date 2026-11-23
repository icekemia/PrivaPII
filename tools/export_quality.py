"""Measure what a reviewed export protects, preserves and restores."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from .benchmark import development_rows
from privapii.export_formats import render_export
from privapii.nus import NusDetector
from privapii.policy import PROFILES, selected_indices
from privapii.detection import TOKEN, Span, hybrid, merged_ranges, review_spans
from privapii.vault import Workspace, new_id

FIXTURE = Path("tests/fixtures/export_quality.json")


def coverage(start, end, masks):
    return sum(max(0, min(right, end) - max(left, start)) for left, right in masks)


def reviewed_decisions(path, rows):
    entries = json.loads(path.read_text(encoding="utf-8"))["documents"]
    if len(entries) != len(rows):
        raise ValueError("Each benchmark document needs one reviewed decision record.")
    results = []
    for row, entry in zip(rows, entries):
        text = row["text"]
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if entry["text_sha256"] != digest:
            raise ValueError("A review record refers to a different document revision.")
        seconds = entry["review_seconds"]
        if not isinstance(seconds, (int, float)) or not 0 <= seconds < float("inf"):
            raise ValueError("Review duration must be finite and nonnegative.")
        spans = [Span(item["start"], item["end"], item["label"]) for item in entry["protected"]]
        merged_ranges(text, spans)
        results.append((spans, seconds))
    return results


def evaluate(rows, detector, directory, *, decisions=None):
    password = "synthetic export quality passphrase"
    path = directory / "quality.sqlite"
    vault = Workspace(path, password, create=True)
    accuracy = {}
    documents = Counter()
    combined, expected = [], []
    for index, row in enumerate(rows):
        text = row["text"]
        if decisions is None:
            findings = review_spans(text, hybrid(text, detector(text)))
            indices = selected_indices(findings, PROFILES["Standard"], set())
        else:
            findings, seconds = decisions[index]
            indices = list(range(len(findings)))
            documents["review_seconds"] += seconds
        masks = merged_ranges(text, [findings[index] for index in indices])
        doc_id = new_id()
        vault.review(doc_id, "synthetic.pdf", text, findings)
        protected = vault.transform(doc_id, indices)
        markdown = render_export(protected, "Markdown", "synthetic.pdf")
        restored, count = vault.restore(markdown)
        documents["documents"] += 1
        documents["tokens"] += count
        documents["token_sequence_mismatches"] += TOKEN.findall(markdown) != TOKEN.findall(protected)
        documents["text_roundtrip_mismatches"] += vault.restore(protected)[0] != text
        expected_markdown = render_export(text, "Markdown", "synthetic.pdf")
        documents["markdown_roundtrip_mismatches"] += restored != expected_markdown
        document_leaks = document_loses_content = False
        for item in row["label"]:
            span = Span(item["start"], item["end"], item["label"])
            counts = accuracy.setdefault(span.label, Counter())
            counts["gold"] += 1
            covered = coverage(span.start, span.end, masks)
            if span.label.startswith("KEEP_"):
                lost = bool(covered)
                counts["preserved"] += not lost
                counts["obscured"] += lost
                document_loses_content |= lost
            else:
                leaked = covered != span.end - span.start
                counts["protected"] += not leaked
                counts["partially_exposed"] += leaked and covered > 0
                counts["fully_exposed"] += not covered
                document_leaks |= leaked
        documents["documents_with_exposure"] += document_leaks
        documents["documents_losing_preserved_content"] += document_loses_content
        combined.append(markdown)
        expected.append(expected_markdown)

    # Simulate a derived Markdown response that reorders and repeats excerpts.
    reordered = "\n\n".join([*reversed(combined), combined[0]])
    wanted = "\n\n".join([*reversed(expected), expected[0]])
    reopened = Workspace(path, password)
    recovered, count = reopened.restore(reordered)
    return {
        "workflow": "reviewed" if decisions is not None else "automatic",
        "documents": dict(documents),
        "categories": accuracy,
        "combined_restoration": {
            "matches_expected_markdown": recovered == wanted,
            "restored_tokens": count,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--model", type=Path, default=Path("models/nus"))
    parser.add_argument("--reviewed-decisions", type=Path,
                        help="Measure the actual reviewed spans and review durations.")
    args = parser.parse_args()
    rows = list(development_rows(args.fixture))
    if not rows:
        parser.error("The export quality fixture is empty.")
    with TemporaryDirectory() as directory:
        if args.reviewed_decisions:
            try:
                decisions = reviewed_decisions(args.reviewed_decisions, rows)
            except (OSError, ValueError, TypeError, KeyError) as error:
                parser.error(str(error))
            result = evaluate(rows, None, Path(directory), decisions=decisions)
        else:
            result = evaluate(rows, NusDetector(args.model), Path(directory))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
