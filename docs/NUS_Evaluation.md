# PrivaPII evaluation on NUS validacija

## Corpus and scope

The local Parquet export contains 123 documents and 7,148 annotated spans. This is the upstream NUS held-out split. PrivaPII uses it for reproducible comparison on the same documents, alongside the planned independent benchmark.

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

## Multi-document workflow check

The desktop smoke test transformed two actual NUS documents using the gold spans as a substitute for approved findings. It then combined the pseudonymized documents in reverse order and verified exact restoration to the corresponding originals. This exercises export and restoration independently of detection accuracy. Local source text and restored values were excluded from the report.

## Reproduction

Use the setup instructions in the [README](../README.md) and run `python benchmark.py --rules-only`. Run `python benchmark.py` once the pinned checkpoint is installed to compute the paired comparison. Record exact span counts, uncovered spans and document exposure for both configurations before reporting an improvement.
