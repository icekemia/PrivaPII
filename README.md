# PrivaPII

PrivaPII is an offline desktop prototype for reviewing and pseudonymizing Lithuanian documents and restoring references in derived text from multiple documents.

## Run the prototype

From the project folder on Windows with Python 3.11 and Tk installed:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe app.py
```

After setup, **Start-PrivaPII.cmd** opens the app from the project folder. Run `.venv/Scripts/python.exe check_setup.py --mode ocr` to check installed dependencies and pinned asset checksums for the complete local configuration. Use `--mode nus` or `--mode rules` for smaller configurations.

Rules mode detects Lithuanian phone formats, email addresses and checksum-valid personal, company, VAT and Lithuanian IBAN identifiers. Company-code detection requires a matching Lithuanian field label, and VAT detection requires the LT prefix. A reviewer can mark additional spans. With the evaluation dependencies and a complete local checkpoint, the default **NUS + rules** mode combines both detectors. Use **NUS only** to compare on the same text.

1. Select **Create workspace** and save the vault under the ignored `vault/` directory or outside the repository. Choose a passphrase. Use **Import document** to open TXT, TSV, Markdown, DOCX or text-based PDF files, or paste text into a new document.
2. Select **Detect** and review the highlighted findings. Mark missed spans, correct categories, and link mentions of the same entity explicitly if appropriate. Use **Categories and profiles** to select groups or individual categories and save a named profile. Use **Toggle exclusion** to retain specific occurrences. Policy changes use the current findings without running NUS again.
3. Choose **Pseudonymize** for reversible references. **Redact irreversibly** is available for permanent text removal in the output. Inspect the exact preview for residual identifiers before saving or copying it.
4. Review and export another document in the same workspace. Combine or reorder the pseudonymized passages and paste them into **Restore derived text**, or import derived TXT or Markdown files. You can lock the workspace or close PrivaPII, then reopen the workspace with its passphrase and restore the same references. Review the attribution and Lithuanian grammar before reusing the restored text.

Use **Compare tokens** to compare the return with selected original pseudonymized exports. Check missing references against the requested transformation. Use **Save restored file** for TXT, Markdown, CSV or Word. Restored files contain original values.

The workspace stores an authenticated AES-GCM snapshot in SQLite. The passphrase derives the key locally with scrypt. If the passphrase is lost, the workspace cannot be recovered. Temporary mode keeps references in memory only. Linking is manual and scoped to the workspace. Confirmed identical surface forms can reuse a token, while different inflections have distinct tokens tied to the same entity. Previously generated references remain valid for their original surface forms after regrouping. Workspace files contain encrypted originals even when an output is redacted. Pseudonymized exports can retain identifying context.

Use **Backup** in an unlocked workspace to save a separate encrypted copy after the current review is committed. Open the backup as a workspace with the same passphrase. Keep the backup and passphrase available separately when moving to another PC.

**Import document** extracts the native PDF text layer and reports empty and mixed pages. For a single mixed PDF, use the prompt to open OCR review directly from an unlocked workspace. **Review scan** also processes scanned PDFs and raster images with [local OCR](docs/OCR.md). That workflow offers reversible text exports and an optional irreversible, image-only PDF with reviewed pixel masks. Automatic identity resolution and passphrase recovery remain outside this milestone.

NUS finding scores describe model confidence and have not been calibrated as probabilities of correctness. Rule findings report the format or checksum check performed. Review the extraction and the selected findings for omissions before exporting.

The **Standard** profile keeps generic dates, times, durations and quantities available for analysis. The review rules recognize complete written Lithuanian dates, including the optional `mėn.` marker, and protect explicit dates of birth as a separate category. Use **Strict** or a custom profile when dates and quantities in the surrounding context could identify someone. Automatic review preserves recognized list numbering and point references. It can extend a single detected name component to an adjacent capitalized word on the same line when other findings do not conflict. Review these suggestions against the source.

Pseudonymized output uses typed references such as `[PRIVAPII_V2_PER_…]` with opaque identifiers. The encrypted workspace stores the exact value and its source. Keep the reference intact when sharing text for analysis or transformation. Previously exported V1 references remain valid in the workspace that created them.

**Save reviewed export** offers UTF-8 TXT and Markdown. Choose the format and inspect the exact file contents before saving. Markdown documents retain their source markup. For extracted text, Markdown adds recognized Lithuanian section headings and preserves explicit clause numbers as literal labels to prevent renderer renumbering. The formatter preserves token strings and does not reconstruct source PDF tables or complex layouts.

The preview checks the selected text format locally for structured identifiers that are still visible, including email, phone numbers, Lithuanian personal and company codes, VAT numbers and IBANs. It distinguishes values retained by review from candidates needing attention, and reports the count of intact restoration tokens. Names, addresses, context and visual PDF regions still require review in the respective preview.

### Workspace archives

In an unlocked workspace, choose **Export workspace ZIP**, select the documents and choose TXT or Markdown. **Prepare previews** applies the active profile to saved findings and occurrence exclusions. Inspect and confirm each file in the dropdown. If a file needs changes, close the archive preview, update that document and prepare the archive again. Changing the selection or format clears prior confirmations.

The ZIP contains only the reviewed exports, named `document-001`, `document-002` and so on. The original filenames and workspace stay local. Token bindings are committed to the vault before the archive contents are written. Extract returned text or Markdown files and import them in **Restore derived text** to restore them from the same workspace.

**CSV** is also available when both the source and the protected output contain one complete rectangular Markdown pipe table or one tab-separated table. The preview checks row and column counts and token order. The Markdown table must have an explicit header separator and simple cells.

Use **Import table → Digital PDF** or **Import table → Word document** to extract a complete rectangular table. Select the table, inspect the grid, then import it as a separate TSV document. Native PDF tables need visible ruling lines and a text layer. The import normalizes whitespace within cells. Detection runs cell by cell. Under the Standard profile, an explicit birth-date column such as `Gimimo data` is protected, while ordinary dates in columns such as `Išdavimo data` remain visible.

Use **Review scan → Table cells** for scans, images, borderless tables and tables with merged cells. Confirm a proposed grid or draw row and column guides. Declare merged areas on the reviewed grid. The two local OCR engines read each cell and show their transcriptions alongside the original crop. After review, export reversible CSV or review the masks for an irreversible PDF. Each import covers one table on one page. [Scanned table instructions](docs/OCR.md#review-and-export-a-scanned-table)

Import a single derived CSV in **Restore derived text** to select CSV mode. PrivaPII restores values by cell and serializes the table with quoting. Inspect the restored preview and use **Save restored file** to create a local file containing the original values.

### Word documents

DOCX import covers visible body paragraphs, table text, common decimal numbering and bullets, including numbering inherited through paragraph styles. Original formatting, headers, footers, comments, images and other package content are outside this import scope. Use **Import table → Word document** to keep a complete rectangular table as a separate CSV-compatible document.

Choose **Word** in the export preview to build a fresh `.docx` from reviewed text. A verified tabular export becomes a Word table. Export builds a new package from the preview, with document content and the required package relationships. To restore a returned DOCX, import it in **Restore derived text** and choose **Save restored file**. The restored DOCX contains original values and is written locally.

### Linked person forms

Choose **Review people** in an unlocked workspace to see saved person mentions, source context and their entity IDs together. **Candidates only** highlights identical spellings and possible genitive, dative or accusative variants across different entity IDs. **Show candidate matches** narrows the view to the selected mention and its matches. Inflection suggestions compare attested two-part names against a limited set of Lithuanian nominative patterns, with both parts matching the same case. Other forms can be found by name fragment or document name. Set one mention as the target, select the other mentions and confirm the link after checking the source context. The target remains available while you filter. Regenerate exports to expose the updated links.

To correct a group, select a mention and choose **Show entity mentions**. Select the mentions belonging to a different person and choose **Split selected mentions**. The selected mentions receive one new entity ID, and at least one mention must stay with the original ID. Previously exported tokens still restore their recorded values. Regenerate linked exports to share the corrected grouping.

In an unlocked workspace, use **Link entity** to confirm that two reviewed person mentions refer to the same person. Enable **Expose linked person IDs** before pseudonymizing if the recipient needs to group the forms across documents. The option is off when opening a workspace. A linked token has the structure `[PRIVAPII_V3_PER_<entity>_<form>_<check>]`. The entity segment is shared by confirmed mentions in the workspace, while the form segment distinguishes their recorded spellings and inflections. The recipient can group by the entity segment and should return the full token unchanged. Enabling this option makes the association visible to the recipient.

**Preview local restoration** uses each token's recorded form. **Choose verified person form** lets you select an occurrence and substitute another recorded form for the same currently linked person. Selections apply only to the current preview and are cleared when the derived text changes. Choose the form that fits the new sentence. PrivaPII offers recorded alternatives and leaves grammatical selection to the reviewer.

## NUS evaluation

Set up the optional evaluation stack in a virtual environment:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r requirements-evaluation.txt
```

Use the [pinned NUS checkpoint](https://huggingface.co/VytautoDidziojoUniversitetas/NUS-LT-PII-xlm-roberta-large/tree/ab8357ffd9563a8035344e85d6b5f3c6a0c8a8e4). Place its `config.json`, `tokenizer.json`, `tokenizer_config.json` and `model.safetensors` in `models/nus/`. The expected SHA-256 of the weights is `cd229d1cf1b39c59486fafef0b876024e63eaba591f058916df657433ebd03f5`.

Place the [NUS validacija Parquet export](https://huggingface.co/datasets/VytautoDidziojoUniversitetas/NUS-LT-PII-corpus/resolve/refs%2Fconvert%2Fparquet/validacija/test/0000.parquet) at `data/nus-test.parquet`. The evaluation runner reads it locally and prints aggregate counts. The corpus and checkpoint directories are ignored by Git.

```powershell
.venv/Scripts/python.exe app.py
.venv/Scripts/python.exe benchmark.py --rules-only
.venv/Scripts/python.exe benchmark.py
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

The paired run compares the NUS checkpoint through PrivaPII's offline adapter with the same adapter plus rules. It reports exact precision, recall, F1 and F2, boundary errors, complete omissions, partial or full exposure, inference timing and peak working-set memory. New rule types outside the NUS taxonomy are counted separately and need adjudication. Reserve the upstream evaluation split for fixed comparisons and use separate development data to tune future rules.

See the [pilot readiness plan](docs/Pilot_Readiness.md), [demo guide](docs/Demo_Guide.md), [action plan](docs/PrivaPII_Action_Plan.md), [benchmark protocol](docs/Benchmark_Protocol.md) and [dependency review](docs/Dependency_Review.md).
