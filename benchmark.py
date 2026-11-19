"""Compare aggregate NUS and hybrid metrics without printing source content."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

from nus import NusDetector
from privapii import Span, hybrid


def score(stats, gold, predictions):
    predictions = sorted(set(predictions))
    exact = set(predictions)
    document_leaks = False
    for span in gold:
        stats[span.label]["gold"] += 1
        stats[span.label]["exact"] += span in exact
        covered = span.start
        for prediction in predictions:
            if prediction.start > covered or covered >= span.end:
                break
            covered = max(covered, prediction.end)
        if covered < span.end:
            stats[span.label]["uncovered"] += 1
            document_leaks = True
    for span in predictions:
        stats[span.label]["predicted"] += 1
    return document_leaks


def main():
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/nus-test.parquet"))
    parser.add_argument("--model", type=Path, default=Path("models/nus"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rules-only", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    rows = pq.read_table(args.data, columns=["text", "label"]).to_pylist()[:args.limit]
    if not rows:
        parser.error("Evaluation split is empty")
    detect = None if args.rules_only else NusDetector(args.model)
    modes = ("rules",) if args.rules_only else ("nus", "hybrid")
    labels = {item["label"] for row in rows for item in row["label"]}
    metrics = {
        mode: {label: Counter() for label in sorted(labels)} for mode in modes
    }
    leaks = Counter()
    added_without_gold_labels = Counter()
    started = perf_counter()
    for index, row in enumerate(rows, 1):
        text = row["text"]
        gold = {Span(item["start"], item["end"], item["label"]) for item in row["label"]}
        baseline = detect(text) if detect is not None else []
        enriched = hybrid(text, baseline)
        for span in set(enriched).difference(baseline):
            if span.label not in labels:
                added_without_gold_labels[span.label] += 1
        predictions_by_mode = {"nus": baseline, "hybrid": enriched, "rules": enriched}
        for mode in modes:
            predictions = predictions_by_mode[mode]
            leaks[mode] += score(metrics[mode], gold, [s for s in predictions if s.label in labels])
        if index % 10 == 0 or index == len(rows):
            print(f"Scored {index}/{len(rows)} documents", file=sys.stderr, flush=True)
    for mode in modes:
        for counts in metrics[mode].values():
            for key in ("gold", "exact", "uncovered", "predicted"):
                counts.setdefault(key, 0)
    print(json.dumps({
        "dataset_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "documents": len(rows),
        "seconds": round(perf_counter() - started, 1),
        "documents_with_uncovered_gold": leaks,
        "added_without_gold_labels": added_without_gold_labels,
        "labels": metrics,
    }, indent=2))


if __name__ == "__main__":
    main()
