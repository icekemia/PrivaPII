# Local OCR review

PrivaPII opens a review window for scanned PDFs and raster images from an unlocked desktop workspace. It runs PP-OCRv6 Medium and Tesseract with the Lithuanian `tessdata_best` model on the CPU. The reviewer sees the original crop and both machine readings. Disagreement, agreement and human verification are separate states.

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

## Review a scan in the app

Open or create a workspace and choose **Review scan**. Select a PDF or image. The OCR engines run in the background, and the review window opens when the local analysis finishes. Click **Finish** to save review evidence and authorized references to the workspace. Choose TXT or Markdown, inspect the exact preview and choose **Save reviewed file**. The same workspace can restore that file through **Restore derived text**.

Regions explicitly marked **Pseudonymize verified** stay protected when regenerating a text export under another category profile. **Toggle exclusion** on the specific finding to retain it intentionally.

### Export a visually redacted PDF

From the reviewed export preview, choose **Review PDF masks**. Regions marked **Mask** or **Pseudonymize verified** start with padded black masks. Inspect the full page with **Fit / full size** and add masks by dragging over any remaining visual content that needs protection. Confirm each page, then choose **Save new redacted PDF**. Drawing or undoing a mask clears that page's confirmation.

The PDF writer creates one lossless image per page from already-masked pixels. The source text layer, annotations, form objects, embedded attachments and source metadata are discarded during reconstruction. The PDF is irreversible and image-only. Use TXT or Markdown for a reversible file paired with the encrypted workspace. Manual page masks apply to the PDF alone. Review every page for sensitive content missed by both engines, including text outside recognized regions.

## Launch the standalone reviewer

```powershell
.venv/Scripts/python.exe ocr_review.py local/scan.pdf --workspace local/scan.sqlite --output local/scan_reviewed.txt --create
```

Remove `--create` to use an existing workspace. Every recognized region defaults to **Mask**. Use the crop as the source of truth. Type its exact transcription to keep it as text or pseudonymize the region with a restorable reference. A matching OCR pair and a checksum result can inform review. Only a human-confirmed transcription becomes restorable. OCR readings, coordinates, source digest, and review decisions are retained inside the encrypted workspace. Open the workspace in `app.py` to restore authorized references.

The standalone reviewer exports plain text. It approximates reading order by region position. The OCR workflow rasterizes each PDF page, including mixed pages, while regular document import uses the native text layer. Native-text coordinate fusion, automated page completeness checks and table reconstruction remain open. Text positions can shift when a recognized region spans multiple OCR lines. Compare both outputs with the visual original before sharing.

## Verification

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe ocr_smoke.py
```

The smoke test renders three synthetic Lithuanian lines as a scanned PDF, runs both engines and tests a human-verified value through export and vault reopening. It denies DNS resolution and connections through Python's socket audit events. This checks the Python inference path with local assets. It does not monitor network activity inside native libraries.

On the local Windows CPU, both engines returned three lines and matched two lines exactly. The comparison identified two disagreements and one agreement. The measured OCR times were 38.18 seconds for PP-OCRv6 Medium and 0.65 seconds for Tesseract, excluding model initialization. Each engine ran once on a single synthetic page. Use a larger, stratified corpus before drawing speed or accuracy conclusions.
