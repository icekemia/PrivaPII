# PrivaPII

PrivaPII is an offline desktop prototype for reviewing and pseudonymizing Lithuanian text and restoring references in derived text from multiple documents.

## Run the prototype

From the project folder on Windows with Python 3.11 and Tk installed:

```powershell
python app.py
```

The standard-library mode detects Lithuanian phone formats, checksum-valid personal codes and Lithuanian IBANs, and email addresses. A reviewer can mark additional spans. In hybrid mode, the same rules augment the local NUS checkpoint.

1. Paste or open a UTF-8 TXT or Markdown document. Select **Detect**, inspect the highlighted findings and mark any missed spans by selecting text and choosing **Mark selected text**.
2. Select the findings to transform. Choose **Pseudonymize** for reversible references or **Redact** to remove the selected text from the export. Inspect the exact preview before saving or copying it.
3. Review and export a second document in the same window. Combine or reorder the pseudonymized passages, then paste them into **Restore derived text** and preview the restoration locally. Review the attribution and Lithuanian grammar.

The restoration vault is in memory. Keep the same application window and case open until the demonstration is complete. Each export uses fresh references and preserves the original surface form. The prototype has no cross-document entity linking, persistent vault, OCR, PDF or Word support. Pseudonymized exports may retain identifying context and must be reviewed.

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
python -m unittest discover -s tests -v
```

The paired run compares the NUS checkpoint through PrivaPII's offline adapter with the same adapter plus rules. It measures exact annotated spans and annotated text that would remain partially or fully exposed. New rule types outside the NUS taxonomy are counted separately and need adjudication. The upstream evaluation split is useful for relative comparison and remains distinct from the planned independent benchmark.

See the [demo guide](docs/Demo_Guide.md), [action plan](docs/PrivaPII_Action_Plan.md), [benchmark protocol](docs/Benchmark_Protocol.md) and [dependency review](docs/Dependency_Review.md).
