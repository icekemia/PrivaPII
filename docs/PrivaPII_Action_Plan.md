# PrivaPII — Technical action plan

19 November 2026 · Draft for feasibility and release planning

PrivaPII is a local-first desktop tool for reviewing and protecting Lithuanian documents. It prepares reviewed exports for use with agents, LLMs and other tools, then restores approved references locally in derived outputs. The first implementation milestone focuses on an observable document-to-restoration workflow with a persistent vault. Later experiments measure whether hybrid detection reduces residual PII. Development and local verification proceed independently of external meetings or access to an independent gold corpus. See the [current implementation and limits](../README.md).

## Scope and privacy boundary

- Run import, OCR, detection, review, export, vault operations and restoration offline on the device. Start with a Windows x64 CPU pilot, then qualify additional platforms against the same test suite.
- Offer two explicit export modes. **Pseudonymize** replaces selected values with reversible references backed by a local vault. **Redact** removes selected values from the export and creates no restoration mapping for those removals.
- Treat pseudonymized exports as personal data where applicable. Redaction can also leave identifying context or combinations of quasi-identifiers. Before external transfer, the professional must assess the resulting content, applicable GDPR and sector obligations, lawful basis, recipient and processor terms, retention and any international transfers. Have a Lithuanian privacy reviewer validate product wording and the intended professional workflow before release. [GDPR, Article 4, Recital 26 and Chapter V](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- Use deliberate file export and reimport for optional remote processing. Ship without telemetry or provider integrations. Token reuse exposes equality within a case, and exported context can still identify people.
- Scope the first pilot to pasted text, TXT and Markdown, including multi-document cases. Qualify searchable PDF, scanned PDF and images next, then DOCX. Enable each format and workflow only after its own release checks pass.

## Architecture and contracts

| Module | Proposed contract | Required behavior |
| --- | --- | --- |
| Ingestion | `ingest(input) → DocumentRevision` | Produce normalized text, page or section boundaries, original span mappings and extraction warnings. Preserve Lithuanian diacritics. Define offsets as half-open Unicode code point indexes. Isolate PDF and OCR workers and bound file size, pages and processing time. |
| Detection | `detect(revision, detectorConfig) → Candidate[]` | Run NUS through a replaceable adapter, local rules and optional verifier. Return original spans, source, model label, policy category, confidence and validation evidence. Pin model, rule and normalization versions. |
| Fusion and linking | `resolve(candidates, caseSnapshot) → ReviewItems` | Resolve overlaps without exposing a partially masked sensitive span. Propagate high-confidence mentions. Require corroboration or user review for person linking across documents. Surface homonyms, OCR uncertainty and conflicts. |
| Policy | `plan(reviewItems, policy, overrides) → TransformPlan` | Evaluate keep, redact, pseudonymize or confirm. Version Standard, Strict, Identity Only and Custom profiles. Support allowlists, denylists and occurrence overrides. Define precedence as occurrence, entity, category, profile. Require confirmation when an override retains a flagged value. |
| Export | `render(plan, revision, caseSnapshot) → Export + Findings` | Check source revision, coalesce spans safely, produce a new file, and scan the exact output and supported hidden channels. Block export if the plan is stale, review is unresolved or output checks fail. Regenerate from saved detections after policy edits. |
| Vault | `commitExport(caseId, revision, bindings) → ManifestRevision` | Commit bindings and provenance transactionally before exposing an export. Pin the manifest to the reviewed export batch. Retry with the same batch ID and publish staged files atomically where the platform supports it. |
| Restoration | `previewRestore(derivedText, caseId, batchId) → Diff + Findings` | Resolve exact tokens against the selected batch locally. Require approval of the current preview before writing a distinct output. Treat imported content as untrusted text and disable HTML, links and active content in previews. |

Keep model-specific labels, user-facing policy categories and rendered placeholder types in a versioned mapping. Cover persons and identity codes, contact and location details, organizations and banking identifiers, and contextual data such as health and family relationships. Track unsupported categories explicitly. Evaluate mixed-language text and foreign identifiers independently before claiming coverage. Checksum failures lower confidence or trigger review for plausible identifiers, especially after OCR.

### Vault and manifest

- **Case** has a random case ID, retention settings and key reference. **DocumentRevision** has a random document ID, immutable revision ID, case ID and local content fingerprint. **Entity** has a random entity ID, case ID, category, canonical value and link status. **Occurrence** has its own ID, entity ID, revision ID, coordinates or text span, original surface form and grammatical case when known.
- **ExportBatch** records the case ID, manifest revision, approved document revisions, policy revision and allowed tokens. **TokenBinding** associates each token with an immutable entity reference and, optionally, one attested surface form. Enforce unique token and case constraints in storage. A batch can explicitly combine approved exports from the same case.
- Prototype an encrypted database with authenticated encryption and a per-case data key protected by the platform keystore. Use encrypted portable backups with a passphrase-derived wrapping key and test recovery before enabling backup in the UI. Keep originals, keys, surface forms, tokens and sensitive paths out of logs. Make retention explicit and test deletion of app-controlled copies, including backup handling. Document OS limitations around temporary storage, backups and physical erasure.
- Keep bindings immutable. A correction that changes a binding's meaning revokes affected exports for restoration and requires regeneration. Store review and audit events with IDs, counts and outcome codes. Exercise vault locking, wrong keys, interrupted writes, migrations and isolation under concurrent edits.

### Placeholder and restoration protocol

1. Prototype the ASCII grammar `[PRIVAPII_V1_<ID>_<CHECK>]`. ID is 26 uppercase Crockford Base32 characters encoding 128 random bits, using a canonical encoding. CHECK is eight uppercase hexadecimal characters encoding CRC-32/ISO-HDLC over the ASCII string `PRIVAPII_V1_<ID>`. Reject noncanonical encodings and retry token generation on a uniqueness violation. The checksum detects accidental corruption. Manifest membership provides the authorization check.
2. Allocate one stable entity token per case. Use the same token across exports for a confirmed entity. A faithful source export may use a separate opaque token bound to an attested surface form when exact morphology is required. Keep entity and surface-form bindings distinct in the manifest. Reserve the token syntax, flag token-shaped strings in source text and require their removal or explicit replacement before exporting.
3. Scan the derived output once and restore only authorized tokens from the selected batch. Preserve intact tokens inside Markdown formatting and support repetition and reordering. Treat unknown, foreign, revoked, malformed and visibly truncated tokens as blocking findings. Use exact matching without case folding, OCR correction, cross-case search or recursive substitution. Report batch tokens absent from the output for review, since summarization can legitimately omit them and complete deletion cannot be inferred reliably.
4. Show an occurrence-level diff before producing a local restored file. A genuine token can be copied into an incorrect sentence by a model or a person. Require the reviewer to check context and attribution. For Lithuanian inflection in new sentences, offer attested forms and an explicit human selection when grammar is uncertain. Preserve the exact original surface form for a faithful round trip.

The threat model covers accidental external disclosure, case mix-ups, homonym merges, altered or replayed tokens, untrusted imports, hidden document content and local vault theft. Keep reidentified outputs clearly marked local in the UI. A compromised endpoint or a user forwarding a restored file remains outside the protection offered by the application.

## Benchmark and model experiments

Obtain licenses and provenance for each dataset, model checkpoint, code package and OCR language asset independently. Record version, redistribution and use conditions, citation duties and alternatives. Review NUS and its NewGenLTU terms and review Rizzo separately. Freeze an evaluation protocol before tuning any model. [NUS application](https://github.com/Faculty-of-Informatics-VDU/nus-lt-pii) · [NUS checkpoint](https://huggingface.co/VytautoDidziojoUniversitetas/NUS-LT-PII-xlm-roberta-large) · [Rizzo PII](https://github.com/Rizzo-AI-Academy/rizzo-pii)

- Build a synthetic Lithuanian regression suite and an independent, lawfully sourced gold set. Stratify by domain, identifier, grammatical case, language mix, format and OCR quality. Keep case, person and template families within one split. Annotate direct identifiers, quasi-identifiers, spans and entity links, with two Lithuanian reviewers and adjudication on critical annotations. Keep gold text and annotated values local. Publish tooling and aggregate results with fixtures cleared for redistribution.
- Compare pinned NUS, NUS plus Lithuanian rules, and NUS plus rules and propagation. Evaluate overlapping spans, diacritics, names with initials, ambiguous declensions, invalid or partial codes, and OCR substitutions. Use the same export policy for comparisons. Tune on development data and run the frozen comparisons on the independent test set.
- Train mmBERT-base and EuroBERT-210m only if the baseline identifies material gaps. Include an equivalent NUS/XLM-R fine-tuning run if licensing and resources permit. Use the same category map and splits. Record seeds, hyperparameters, hardware and wall time. Start with three seeds and a 24 GPU-hour cap per candidate. Test an ensemble only when development errors are complementary and the CPU budget can accommodate it. [mmBERT-base](https://huggingface.co/jhu-clsp/mmBERT-base) · [EuroBERT-210m](https://huggingface.co/EuroBERT/EuroBERT-210m)
- Report exact-span precision, recall and F1 by category, false omissions, case-linking errors and residual exposure. Define document leakage as the share of eligible exported documents containing at least one residual gold item that the selected policy should transform. Report it before review and after the full review workflow. Track direct identifiers, contextual disclosures and deliberately retained categories separately. Include sample counts and confidence intervals, with case-level resampling when reporting paired improvements.

| Provisional pilot gate | Measurement |
| --- | --- |
| Critical direct identifiers | Target ≥99% recall per enabled critical category for text, including names, personal and identity document codes, direct contact details and bank identifiers. Report the 95% lower confidence bound and sample size. A category with sparse evidence requires manual review and no automated coverage claim. |
| Other enabled categories | Target ≥95% recall per category and document the worst subgroups. Assess special-category and contextual disclosure at the document level and require review. |
| Hybrid adoption | Reduce critical omissions and document leakage versus original NUS on the frozen set. Compare paired outcomes and inspect any regressions by category. Record precision and review time as costs. |
| Reviewed exports | Observe zero residual critical items and target ≤1% document leakage under the tested policy. Report a separate case leakage bound. With zero leaking cases, at least 299 independent eligible cases support a one-sided 95% exact upper bound below 1% for case leakage. Keep claims scoped to the tested domains and formats. |
| Restoration | Zero incorrect substitutions and zero foreign or revoked token resolutions in the regression suite. Exercise repeated and reordered tokens, homonyms, grammar, corruption, missing tokens, case isolation, stale previews and unavailable vaults. |
| CPU usability | Provisional targets on an 8 GB Windows CPU-only reference device are p95 ≤15 seconds for a five-page text document and peak memory ≤3 GB. Measure cold and warm runs separately and set an OCR per-page budget from the prototype. |

## Document handling and user workflow

- **PDF with text**. Preserve coordinates during extraction. Prototype reconstruction from sanitized content for the first format release. Qualify any layout-preserving path only after verifying that redacted spans are absent from text layers, streams, attachments, forms, metadata, annotations and incremental revisions.
- **Scans and images**. Benchmark local Lithuanian OCR on tables, stamps, skew and low-resolution scans. Show low-confidence and uncovered areas for visual review. Burn redactions into raster pixels and build a fresh PDF or image from the sanitized raster. Rebuild a text layer only from sanitized content. Inspect output with independent extraction, object inspection, render and OCR tests.
- **DOCX**. Start with a fresh structured export from approved content. Qualify formatting preservation separately by inspecting the exported package and covering headers, footers, comments, tracked changes, properties, embedded media and external relationships. Treat images and unsupported embedded objects as review items.
- **Review and restore**. Open or create a case, ingest documents, inspect coverage warnings, choose a profile, review highlighted spans and grouping decisions, and preview the exact outgoing content. Allow entity merge and split with regeneration. Show retained categories and export findings before confirmation. Import a derived output into the selected case and batch, inspect the diff and grammatical choices, then save locally. Include Lithuanian interface copy in the pilot evaluation. Write project documentation and code comments in English.

## Milestones and dependencies

Estimates below are planning ranges for a small team with one engineer and part-time Lithuanian annotation and privacy review. Re-estimate after feasibility using measured throughput and corpus availability.

| Milestone | Indicative effort | Deliverable and exit check |
| --- | --- | --- |
| M0 · Reconnaissance | 1 week | License and dependency matrix, supported-domain proposal, annotation guide, candidate OCR and desktop stacks, and target-device inventory. Secure lawful benchmark access. |
| M1 · Original NUS benchmark | 2–3 weeks after M0 | Reproducible baseline, frozen split manifest, CPU profile and prioritized critical false negatives. |
| M2 · Vault and restoration proof | 2 weeks, parallel with M1 | Three-document case with shared declined names and distinct homonyms. Restore an output with reordered and repeated references, while rejecting foreign and corrupted tokens. Demonstrate backup recovery and crash consistency. |
| M3 · Hybrid detection | 2–3 weeks after M1 | Local detector API, rule and propagation ablations, paired leakage comparison and regression fixtures. Review M2 and M3 together before committing to the desktop build. |
| M4 · Model decision | 1–2 weeks after M3 if warranted | Document the chosen backbone, improvement and CPU cost. Approve the execution backlog and budget based on the benchmark and vault results. |
| M5 · Text desktop pilot | 3–5 weeks after feasibility approval | Complete offline case workflow from import to approved restoration, signed Windows installer, user guide, automated release checks and findings from professional review. Resolve release-blocking defects. |
| M6 · File-format releases | Re-estimate after pilot | Qualify PDF, OCR and DOCX independently with fixture suites, hidden-content checks and clean-device offline installs. |

## Distribution and release decisions

- Start with a local Python prototype and CLI for feasibility. Select the desktop stack after measuring inference, packaging size, accessibility and update effort. Test ONNX or quantization only against the same leakage and CPU gates.
- Aim to release the original code under a permissive license, subject to dependency review. Ship a free signed Windows installer, checksums, dependency and license inventory, offline documentation and an offline model installation path. Include model weights only when redistribution is verified. Budget signing, maintenance and review separately from the zero price to users.
- Automate unit checks for Lithuanian validators and span mapping, property tests for token parsing and workspace isolation, integration tests for vault and format workflows, and clean-device tests for installation, offline execution and recovery. Verify zero network egress during document workflows. Review parser isolation and dependencies before each format release.
- Require sign-off from the engineering lead on restoration, the Lithuanian reviewers on detection and workflow, and the privacy reviewer on documentation and intended use. Track license clearance, corpus availability, token survival, OCR omissions, morphology and CPU performance as milestone risks. When evidence is weak, restrict the affected format or category and document the review path.

**First implementation cycle.** Assign owners for the license inventory and annotation protocol, pin the NUS baseline, and draft the vault threat model and token contract. Run the baseline and the multi-document restoration proof in parallel. Use their results to prioritize the hybrid rules and decide when the desktop pilot is ready to start.

Platform, thresholds, effort and token format are proposed decisions to validate during feasibility. See the [dependency review](Dependency_Review.md) and [benchmark protocol](Benchmark_Protocol.md) for the initial reconnaissance results.
