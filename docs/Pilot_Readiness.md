# PrivaPII Windows pilot readiness

| Order | Work | Status and exit evidence |
| --- | --- | --- |
| 1 | Finish the return workflow | Save restored TXT, Markdown, CSV and Word locally. Compare a return against one or more selected exports to find omissions, repeated, unknown and possibly damaged tokens. |
| 2 | Show extraction coverage | Mixed PDF import routes to OCR review. PDF line review aligns native text and OCR with the same raster coordinates. Word import reports body coverage. Independent mixed-document and OCR acceptance data remain open. |
| 3 | Qualify the reviewed result | The benchmark accepts final review decisions and time and verifies the source digest. Authorized independent documents and human review observations are still needed to measure deployment quality. [Benchmark protocol](Benchmark_Protocol.md) |
| 4 | Protect ongoing work | Authenticated backups, retention reminders and explicit document forgetting with exclusive-token removal are available. Reopen the backup on a second PC for the physical transfer test. |
| 5 | Make setup repeatable | Windows x64 ZIPs use a local wheelhouse and installer script. Model assets stay separate and are checksum verified. Verify installation and recovery on a second clean PC. Review dependency and asset licenses before distributing the build. [Dependency review](Dependency_Review.md) |

The first pilot should cover the complete reviewed text workflow on Windows. Acceptance evidence should include zero incorrect token substitutions in the tested scenarios, a successful backup recovery and a record of residual critical fields after review. Report results by input and export format. Include one native PDF, one mixed PDF and one scanned document before making OCR coverage claims. Keep corpus originals, private findings and vaults local.

## Current verification

The desktop smoke check saved a restored Markdown file, reopened an authenticated backup and restored its token, and routed a mixed PDF to OCR from the import prompt. The setup checker passed in Rules and OCR modes on the development PC. These checks cover dependencies and file hashes. The offline second-PC run will exercise actual engine startup and document workflows.

The current six-document synthetic check protected all ten annotated sensitive fields and retained all fourteen annotated dates and clause references. It restored all sixteen token occurrences in the combined Markdown result, including repeated excerpts. This is a regression check. The independent pilot collection and reviewed-output measurement remain separate work.

The mixed-page smoke check processed a local one-page document and associated native text with 32 review regions. No region was confirmed automatically. Both Windows packages installed from their wheelhouses in fresh, isolated environments on the development PC. The complete package verified the model hashes, ran NUS and both OCR engines offline on a synthetic scan, and restored a confirmed value after reopening the encrypted vault. Each OCR engine transcribed two of the three synthetic lines exactly. The local suite passed 63 tests. Physical-PC transfer, production-domain measurements and distribution clearance remain separate gates.

Before the pilot, use separate backups when transferring work between devices. Test restoration using a copy and its passphrase. Define how long each workspace and its backups are kept, and who can access them. The active-vault forget action does not reach copies outside that vault.
