# Local OCR review

PrivaPII has a separate review window for scanned PDFs and raster images. It runs PP-OCRv6 Medium and Tesseract with the Lithuanian `tessdata_best` model on the CPU. The reviewer sees the original crop and both machine readings. Disagreement, agreement and human verification are separate states.

## Setup

Install CPU PyTorch and the evaluation dependencies according to the [README](../README.md). Then install the OCR dependencies:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-ocr.txt
```

Place the three inference files `inference.json`, `inference.pdiparams` and `inference.yml` for each Paddle model in the corresponding ignored directory:

- `models/PP-OCRv6_medium_det/`. [Detection revision](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det/tree/8e0f56fb2ef86b461d99cfc7ac5c137738985f61)
- `models/PP-OCRv6_medium_rec/`. [Recognition revision](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec/tree/e5a92bcbc5cc1b494628e458d267778f0704fd7c)
- `models/tesseract/lit.traineddata`. Expected SHA-256 `7d47a118f60509408e1dae2dd967d7c553a770e57390fedf8e7af07a192fefe3`. [Lithuanian tessdata_best revision](https://github.com/tesseract-ocr/tessdata_best/blob/e12c65a915945e4c28e237a9b52bc4a8f39a0cec/lit.traineddata)

The local NUS checkpoint remains in `models/nus/`. The runner takes local model directories explicitly, disables Paddle's remote model source check and uses neither cloud OCR nor automatic model installation.

## Review a scan

```powershell
.venv/Scripts/python.exe ocr_review.py local/scan.pdf --workspace local/scan.sqlite --output local/scan_reviewed.txt --create
```

Remove `--create` to use an existing workspace. Every recognized region defaults to **Mask**. Use the crop as the source of truth. Type its exact transcription to keep it as text or pseudonymize the region with a restorable reference. A matching OCR pair and a checksum result can inform review. Only a human-confirmed transcription becomes restorable. OCR readings, coordinates, source digest, and review decisions are retained inside the encrypted workspace. Open the workspace in `app.py` to restore authorized references.

The export is plain text. It approximates reading order by region position. The OCR workflow rasterizes each PDF page, including mixed pages, while the regular desktop import still uses the native text layer. OCR review has no native-text coordinate fusion, page completeness guarantee, table reconstruction, or image and PDF redaction. Text positions can shift when a recognized region spans multiple OCR lines. Compare both outputs with the visual original before sharing.

## Verification

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe ocr_smoke.py
```

The smoke test renders three synthetic Lithuanian lines as a scanned PDF, runs both engines and tests a human-verified value through export and vault reopening. It denies DNS resolution and connections through Python's socket audit events. This checks the Python inference path with local assets. It does not monitor network activity inside native libraries.

On the local Windows CPU, both engines returned three lines and matched two lines exactly. The comparison identified two disagreements and one agreement. The measured OCR times were 38.18 seconds for PP-OCRv6 Medium and 0.65 seconds for Tesseract, excluding model initialization. Each engine ran once on a single synthetic page. Use a larger, stratified corpus before drawing speed or accuracy conclusions.
