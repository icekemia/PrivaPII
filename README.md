# PrivaPII

PrivaPII is an offline desktop prototype for reviewing and pseudonymizing Lithuanian documents and restoring references in derived text from multiple documents.

## Run the prototype

From the project folder on Windows with Python 3.11 and Tk installed:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe app.py
```

Rules mode detects Lithuanian phone formats, email addresses and checksum-valid personal, company, VAT and Lithuanian IBAN identifiers. Company-code detection requires a matching Lithuanian field label, and VAT detection requires the LT prefix. A reviewer can mark additional spans. With the evaluation dependencies and a complete local checkpoint, the default **NUS + rules** mode combines both detectors. Use **NUS only** to compare on the same text.

1. Select **Create workspace** and save the vault under the ignored `vault/` directory or outside the repository. Choose a passphrase. Use **Import document** to open TXT, Markdown or text-based PDF files, or paste text into a new document.
2. Select **Detect** and review the highlighted findings. Mark missed spans, correct categories, and link mentions of the same entity explicitly if appropriate. Use **Categories and profiles** to select groups or individual categories and save a named profile. Use **Toggle exclusion** to retain specific occurrences. Policy changes use the current findings without running NUS again.
3. Choose **Pseudonymize** for reversible references or **Redact** for text removal in the output. Inspect the exact preview for residual identifiers before saving or copying it.
4. Review and export another document in the same workspace. Combine or reorder the pseudonymized passages and paste them into **Restore derived text**, or import derived TXT or Markdown files. You can lock the workspace or close PrivaPII, then reopen the workspace with its passphrase and restore the same references. Review the attribution and Lithuanian grammar before reusing the restored text.

The workspace stores an authenticated AES-GCM snapshot in SQLite. The passphrase derives the key locally with scrypt. If the passphrase is lost, the workspace cannot be recovered. Temporary mode keeps references in memory only. Linking is manual and scoped to the workspace. Confirmed identical surface forms can reuse a token, while different inflections have distinct tokens tied to the same entity. Previously generated references remain valid for their original surface forms after regrouping. Workspace files contain encrypted originals even when an output is redacted. Pseudonymized exports can retain identifying context.

The prototype exports plain text. The desktop PDF import extracts the text layer and reports empty pages. A [separate local OCR review workflow](docs/OCR.md) supports scanned PDFs and raster images. PDF redaction and layout preservation, Word import, automatic identity resolution and passphrase recovery remain outside this milestone.

NUS finding scores describe model confidence and have not been calibrated as probabilities of correctness. Rule findings report the format or checksum check performed. Review the extraction and the selected findings for omissions before exporting.

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

See the [demo guide](docs/Demo_Guide.md), [action plan](docs/PrivaPII_Action_Plan.md), [benchmark protocol](docs/Benchmark_Protocol.md) and [dependency review](docs/Dependency_Review.md).
