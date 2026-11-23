# PrivaPII benchmark and annotation protocol

Draft · 19 November 2026

## Scope and collection

Start with Lithuanian administrative correspondence and professional case notes in plain text. Use synthetic fixtures for software regression and a separately sourced, independently annotated collection for performance estimates. Include Lithuanian name declensions, shared cases, homonyms, mixed-language passages and partial identifiers. Track healthcare, OCR, embedded objects and other formats as separate evaluation strata before enabling them in the product.

Approve the data source, lawful basis, reviewers, retention, storage and aggregate reporting rules before collecting real text. Keep originals, annotations and split manifests within the approved local data directory. Publish only cleared synthetic fixtures, the protocol and aggregate results with small-cell suppression where needed. Exclude the upstream NUS corpus and copies or close variants of its examples from the independent collection.

## Annotation and adjudication

1. Assign opaque case and document IDs. Preserve the source revision and normalize line endings and Unicode to NFC for annotation. Use half-open offsets over Unicode code points and verify that recorded spans match the normalized text. Keep the coordinate mapping for transformations of original-format documents.
2. Mark each mention with a policy category, start and end, and optional entity ID. Start with person name, personal code, identity document number, date of birth, address, phone, email, bank account and organization identifier. Add separate tags for organization names, case references, sensitive health or family context, and combinations of quasi-identifiers. Allow overlapping spans where categories describe different risks. Record combined contextual disclosures with grouped evidence spans.
3. Include the full displayed identifier and internal separators. Exclude surrounding punctuation and adjacent labels. Mark names in their original inflected form, including initials when they belong to the mention. Mark plausible truncated and invalid identifiers with an uncertainty flag. Link across documents only with evidence beyond a matching name, and label unresolved links as uncertain. Record organization mentions separately from personal identities.
4. Two Lithuanian reviewers label critical spans and entity links independently without model predictions. A designated adjudicator resolves disagreements and records rule changes, including treatment of ambiguous spans. Run a small calibration batch before freezing guidelines and keep hard cases in regression fixtures. Report agreement before adjudication and the number of unresolved items.
5. Split by connected groups of case, known person and source template. Keep repeated or near-duplicate documents together. Use development data for rule and threshold changes, a separate training split when needed, and a held-out evaluation split for the final comparison. Version the local split manifest and record changes and evaluation runs.

## Evaluation procedure

Use the same local annotated fixture for automatic and reviewed comparisons. For the reviewed pass, record the final protected spans and time spent reviewing each document. Create a local JSON file with a `documents` array ordered like the fixture. Each record has `text_sha256` for the UTF-8 text after fixture markers are removed, `review_seconds`, and a `protected` array of `start`, `end` and `label` values. Use zero-based half-open Python character offsets. A document digest must match before scoring.

```powershell
.venv/Scripts/python.exe export_quality.py --fixture local/pilot-fixture.json
.venv/Scripts/python.exe export_quality.py --fixture local/pilot-fixture.json --reviewed-decisions local/pilot-review.json
```

Keep document text and span records in the ignored local directory. Publish only aggregate results. The reviewed runner scores the supplied decisions and does not run inference again.

- Run in order an independently cleared local rules baseline, original NUS if cleared, then the hybrid configuration with rules and propagation ablations. Keep normalization, policy and data fixed for comparisons. Record commit, checkpoint revision, rule version, runtime version, machine, seed and run ID. Save sanitized aggregate results and keep detailed error samples local.
- Compute exact-span precision, recall and F1 by category. Separately count false omissions, partial masks and incorrect cross-document links. Score output leakage against the fixed policy. A document leaks if an item selected for transformation can still be recovered from the exact export. Report deliberately retained disclosures and contextual identification separately.
- Measure leakage both after automated transformation and after the review workflow. Record reviewer time, cases needing correction and unresolved findings. Report eligible document and independent case counts plus paired case-level confidence intervals for system comparisons. For the release gate, align the unit with the claim. A zero-leak result across 299 independent cases supports an upper 95% one-sided exact bound below 1% on the **case** leakage rate. Report the document rate separately and account for case clustering.
- Include matched negatives such as company identifiers, non-sensitive date references, name-like organizations and near-valid structured identifiers. Report results by document domain, category, grammatical variation and extraction quality. Record cold and warm CPU timing and peak memory.

## Entry criteria

Engineering owns the reproducible runner and synthetic regressions. The Lithuanian annotation lead owns the guidelines, calibration and adjudication. The data owner and privacy reviewer approve collection and evaluation scope. Before an independent benchmark, secure a cleared corpus, assign both reviewers, freeze the splits and record permitted models. Synthetic fixtures can support implementation and regression testing before those inputs are available.
