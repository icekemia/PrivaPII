# PrivaPII evaluation on NUS validacija

## Corpus and scope

The local Parquet export of the upstream NUS held-out split contains 123 documents and 7,323 annotated spans. Use the observed Parquet counts when comparing PrivaPII runs on this data. The NUS model card reports 7,148 entities for its published evaluation, so treat its published scores and this Parquet run as distinct measurements. [NUS model card](https://huggingface.co/VytautoDidziojoUniversitetas/NUS-LT-PII-xlm-roberta-large/blob/ab8357ffd9563a8035344e85d6b5f3c6a0c8a8e4/README.md)

Parquet SHA-256: `e06b371a1703171a03cfd13180bcb73bbe48ac6a5d58b65c61e78c5e57ed47e6`

Aggregate output counts an annotated span as exposed if any part of it falls outside the union of predicted masks scored against NUS categories. Rule categories absent from the annotation taxonomy are reported separately. There was no human review in the detection measurement.

## Initial rules-only run

| Metric | Result |
| --- | ---: |
| Annotated phone spans matched exactly | 10 of 53 |
| Annotated phone spans left partially or fully exposed | 43 of 53 |
| Annotated personal identifier spans matched exactly | 0 of 4 |
| Documents with at least one partially or fully exposed annotation | 122 of 123 |
| Additional email candidates outside the NUS taxonomy | 26 |
| Additional IBAN candidates outside the NUS taxonomy | 7 |

The email and IBAN counts are detections requiring adjudication. The rules-only run provides a diagnostic for structured identifiers. Paired checkpoint and hybrid results are required to establish incremental detection performance.

## Paired checkpoint run

Both configurations used the pinned NUS checkpoint, the same local Transformers adapter and the same 123 documents. The hybrid configuration added the structured detection rules without changing the checkpoint predictions. The adapter uses first-subword aggregation with a 128-token overlap. Its output boundaries can differ from those of the upstream application.

| Metric | NUS checkpoint | NUS + rules |
| --- | ---: | ---: |
| Exact matches across scored categories | 3,718 | 3,718 |
| Predicted spans in scored categories | 7,248 | 7,250 |
| Exact-span precision | 51.297% | 51.283% |
| Exact-span recall | 50.772% | 50.772% |
| Exact-span F1 | 51.033% | 51.026% |
| Annotated spans partially or fully exposed | 820 | 820 |
| Documents with at least one exposed annotation | 81 of 123 | 81 of 123 |
| Annotated phone spans matched exactly | 20 of 53 | 20 of 53 |
| Annotated phone spans partially or fully exposed | 0 of 53 | 0 of 53 |

The hybrid run added two phone predictions without a gain in exact matches or coverage. It also added 26 email candidates and 7 Lithuanian IBAN candidates outside the scored taxonomy. Measure their incremental coverage against the existing masks and adjudicate them on a separate development set before making a detection claim. The demonstrated product capability is reviewed, case-scoped restoration across documents.

The paired loop took 1,888.9 seconds on an Intel Core i9-8950HK with approximately 16 GB RAM, using CPU PyTorch 2.15.0+cpu and Transformers 4.57.6. The loop runs inference once per document and reuses the predictions for the hybrid configuration. This timing excludes model initialization.

## Multi-document workflow check

The desktop smoke test transformed two actual NUS documents using the gold spans as a substitute for approved findings. It then combined the pseudonymized documents in reverse order and verified exact restoration to the corresponding originals. This exercises export and restoration independently of detection accuracy. Local source text and restored values were excluded from the report.

## Persistent-workspace milestone

The updated desktop workflow was exercised with real NUS inference, a rule-derived email finding, reviewed names, an explicit link between two inflected forms, a profile that left email visible, and exact restoration after closing and reopening the encrypted workspace.

The updated benchmark runner completed a rules-only diagnostic on all 123 documents and an end-to-end paired instrumentation check on one NUS document. Both configurations in the one-document check had 43 exact matches out of 85 gold spans, 32 boundary errors, 10 complete omissions and 12 spans with residual exposure. The NUS inference took 71.34 seconds, rule evaluation and fusion took 0.067 seconds, and the process peak working set was approximately 1.98 GB. The check validates the updated reporting path. The full paired table above reflects the earlier rules configuration.

## Reproduction

Use the setup instructions in the [README](../README.md). Run `python benchmark.py --rules-only` for the diagnostic and `python benchmark.py` for the paired comparison. Use `--limit 2` to check the setup on a smaller input.
