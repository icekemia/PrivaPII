# PrivaPII setup and verification

## Source checkout

From the project folder on Windows with Python 3.11 x64 and Tk:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe check_setup.py --mode rules
.venv/Scripts/python.exe app.py
```

After setup, **Start-PrivaPII.cmd** runs the app from the project directory. Use `Start-PrivaPII.cmd --check` for a basic check.

## Local NUS setup

Install optional inference dependencies:

```powershell
.venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r requirements-evaluation.txt
```

For a pilot configuration authorized to use the checkpoint, place `config.json`, `tokenizer.json`, `tokenizer_config.json` and `model.safetensors` from the [pinned NUS revision](https://huggingface.co/VytautoDidziojoUniversitetas/NUS-LT-PII-xlm-roberta-large/tree/ab8357ffd9563a8035344e85d6b5f3c6a0c8a8e4) in `models/nus/`. Check all pinned asset hashes with:

```powershell
.venv/Scripts/python.exe check_setup.py --mode nus
```

OCR requires the [separate OCR setup](OCR.md#setup). Use `check_setup.py --mode ocr` after installing the engines and assets. See the [dependency and license review](Dependency_Review.md) for the scope of approved pilot use and external distribution decisions.

## Build a Windows pilot package

```powershell
.venv/Scripts/python.exe build_windows_pilot.py --mode rules
.venv/Scripts/python.exe build_windows_pilot.py --mode ocr
```

The build downloads wheels and writes a ZIP and SHA-256 sidecar to `dist/`. Install from the extracted package with **Setup-PrivaPII.cmd**. Model files are installed separately.

## Run tests and benchmarks

Place the [NUS validacija Parquet export](https://huggingface.co/datasets/VytautoDidziojoUniversitetas/NUS-LT-PII-corpus/resolve/refs%2Fconvert%2Fparquet/validacija/test/0000.parquet) in `data/nus-test.parquet` for the paired NUS evaluation. Keep original data and detailed findings local.

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe benchmark.py --rules-only
.venv/Scripts/python.exe benchmark.py
.venv/Scripts/python.exe export_quality.py
```

See the [benchmark protocol](Benchmark_Protocol.md), [evaluation results](NUS_Evaluation.md), [action plan](PrivaPII_Action_Plan.md) and [pilot readiness](Pilot_Readiness.md).
