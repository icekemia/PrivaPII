"""Compare aggregate NUS and hybrid metrics without printing source content."""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

from privapii.nus import NusDetector
from privapii.detection import Span, hybrid

ANNOTATION = re.compile(r"\[\[([A-Z_]+)\|([^\]]+)\]\]")


def development_rows(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    for annotated in fixture["documents"]:
        parts, labels, cursor, offset = [], [], 0, 0
        for match in ANNOTATION.finditer(annotated):
            plain = annotated[cursor:match.start()]
            label, value = match.groups()
            offset += len(plain)
            labels.append({"start": offset, "end": offset + len(value), "label": label})
            parts.extend((plain, value))
            offset += len(value)
            cursor = match.end()
        parts.append(annotated[cursor:])
        yield {"text": "".join(parts), "label": labels}


def score(stats, gold, predictions):
    predictions = sorted(set(predictions))
    exact = set(predictions)
    document_leaks = False
    for span in gold:
        counts = stats[span.label]
        counts["gold"] += 1
        counts["exact"] += span in exact
        if span not in exact:
            overlaps = [item for item in predictions
                        if item.start < span.end and item.end > span.start]
            if any(item.label == span.label for item in overlaps):
                counts["boundary_errors"] += 1
            elif overlaps:
                counts["wrong_label_overlaps"] += 1
            else:
                counts["complete_omissions"] += 1
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


def summarize(counts):
    gold, predicted, exact = (counts[key] for key in ("gold", "predicted", "exact"))
    precision = exact / predicted if predicted else 0
    recall = exact / gold if gold else 0
    return {
        **{key: counts[key] for key in (
            "gold", "predicted", "exact", "uncovered", "boundary_errors",
            "wrong_label_overlaps", "complete_omissions",
        )},
        "false_negatives": gold - exact,
        "false_positives": predicted - exact,
        "precision": precision,
        "recall": recall,
        "f1": 2 * exact / (predicted + gold) if predicted + gold else 0,
        "f2": 5 * exact / (predicted + 4 * gold) if predicted + gold else 0,
    }


def process_peak_rss():
    if sys.platform == "win32":
        import psutil

        return psutil.Process().memory_info().peak_wset
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def main():
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/nus-test.parquet"))
    parser.add_argument("--model", type=Path, default=Path("models/nus"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--development", type=Path, help="Read a synthetic annotated JSON fixture.")
    parser.add_argument("--compare-boundaries", action="store_true", help="Compare NUS decoders on development data.")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.compare_boundaries and (not args.development or args.rules_only):
        parser.error("--compare-boundaries requires --development and NUS inference")
    dataset = args.development or args.data
    if args.development:
        rows = list(development_rows(dataset))[:args.limit]
    else:
        rows = pq.read_table(dataset, columns=["text", "label"]).to_pylist()[:args.limit]
    if not rows:
        parser.error("Evaluation split is empty")
    load_started = perf_counter()
    detect = None if args.rules_only else NusDetector(args.model)
    load_seconds = perf_counter() - load_started
    modes = ("rules",) if args.rules_only else ("nus", "hybrid")
    if args.compare_boundaries:
        modes += ("nus_centered", "hybrid_centered")
    labels = {item["label"] for row in rows for item in row["label"]}
    metrics = {
        mode: {label: Counter() for label in sorted(labels)} for mode in modes
    }
    leaks = Counter()
    added_without_gold_labels = Counter()
    nus_seconds = rules_seconds = 0
    centered_seconds = 0
    started = perf_counter()
    for index, row in enumerate(rows, 1):
        text = row["text"]
        gold = {Span(item["start"], item["end"], item["label"]) for item in row["label"]}
        before = perf_counter()
        baseline = detect(text) if detect is not None else []
        nus_seconds += perf_counter() - before
        before = perf_counter()
        enriched = hybrid(text, baseline)
        rules_seconds += perf_counter() - before
        for span in set(enriched).difference(baseline):
            if span.label not in labels:
                added_without_gold_labels[span.label] += 1
        predictions_by_mode = {"nus": baseline, "hybrid": enriched, "rules": enriched}
        if args.compare_boundaries:
            before = perf_counter()
            centered = detect.centered(text)
            centered_seconds += perf_counter() - before
            predictions_by_mode.update(nus_centered=centered, hybrid_centered=hybrid(text, centered))
        for mode in modes:
            predictions = predictions_by_mode[mode]
            leaks[mode] += score(metrics[mode], gold, [s for s in predictions if s.label in labels])
        if index % 10 == 0 or index == len(rows):
            print(f"Scored {index}/{len(rows)} documents", file=sys.stderr, flush=True)
    micro = {}
    for mode, categories in metrics.items():
        counts = Counter()
        for category in categories.values():
            counts.update(category)
        micro[mode] = summarize(counts)
    print(json.dumps({
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "split": "synthetic_development" if args.development else "parquet",
        "documents": len(rows),
        "seconds": round(perf_counter() - started, 1),
        "model_load_seconds": round(load_seconds, 3),
        "nus_inference_seconds": round(nus_seconds, 3),
        "centered_inference_seconds": round(centered_seconds, 3) if args.compare_boundaries else None,
        "hybrid_rule_and_fusion_seconds": round(rules_seconds, 3),
        "process_peak_rss_bytes": process_peak_rss(),
        "documents_with_uncovered_gold": leaks,
        "added_without_gold_labels": added_without_gold_labels,
        "micro": micro,
        "labels": {mode: {label: summarize(counts) for label, counts in categories.items()}
                   for mode, categories in metrics.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
