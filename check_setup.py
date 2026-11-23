"""Check local PrivaPII dependencies and pinned model assets without downloading."""

import argparse
import hashlib
import importlib.util
from pathlib import Path

BASE = ("tkinter", "cryptography", "pypdf", "pdfplumber", "stdnum")
NER = ("torch", "transformers", "safetensors")
OCR = ("paddleocr", "paddle", "tesserocr", "PIL", "pypdfium2", "cv2")
NUS_ASSETS = {
    "nus/config.json": "7031717bfd3b98b93a46b184b0af0e7aab1a00d295c66f78e196675db3d1cf20",
    "nus/tokenizer.json": "7a5451f31fe3f899dcd75ec2ad93f415528c9b5f58bb7a5a1c6dd5884fb56257",
    "nus/tokenizer_config.json": "c019e3e4f7f901adf680dde303c7d964de86675a13e089bcc0f614d3fce75333",
    "nus/model.safetensors": "cd229d1cf1b39c59486fafef0b876024e63eaba591f058916df657433ebd03f5",
}
OCR_ASSETS = {
    "PP-OCRv6_medium_det/inference.json": "0f1a7ec35da36173529c7a60238b7f7919e3831929c3f700ad90ad4896adecd5",
    "PP-OCRv6_medium_det/inference.pdiparams": "85218d2e3d98f5a21c58b4220627be923a97aee5db3cc71f39536ab31ac53960",
    "PP-OCRv6_medium_det/inference.yml": "7298d5ead546584af2504d03355f881ac7a7bc0eb1e282d3e159277c1d0af871",
    "PP-OCRv6_medium_rec/inference.json": "0b2e25e990bd072f1bf77d59d67d508bce6c4bd44af6624e0fb27d6da2cd00e8",
    "PP-OCRv6_medium_rec/inference.pdiparams": "1b01c79a914587933f615569e75de54f2e638ebb5d3f3b3c1b38c24ede8c7319",
    "PP-OCRv6_medium_rec/inference.yml": "991b700facf5b50a7de193468207d5f4255b538dde0d312ae3b7c7a9b6873129",
    "tesseract/lit.traineddata": "7d47a118f60509408e1dae2dd967d7c553a770e57390fedf8e7af07a192fefe3",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("rules", "nus", "ocr"), default="rules")
    parser.add_argument("--models", type=Path, default=Path("models"))
    args = parser.parse_args()
    modules = BASE + (NER if args.mode != "rules" else ()) + (OCR if args.mode == "ocr" else ())
    assets = dict(NUS_ASSETS) if args.mode != "rules" else {}
    if args.mode == "ocr":
        assets.update(OCR_ASSETS)
    problems = [f"Missing Python module: {name}" for name in modules if importlib.util.find_spec(name) is None]
    if "tkinter" in modules and importlib.util.find_spec("tkinter") is not None:
        import tkinter

        try:
            tkinter.Tcl()
        except tkinter.TclError as error:
            problems.append(f"Tk is unavailable: {error}")
    for name, expected in assets.items():
        try:
            with (args.models / name).open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as error:
            problems.append(f"Cannot read {name}: {error.strerror}")
        else:
            if actual != expected:
                problems.append(f"SHA-256 mismatch: {name}")
    for problem in problems:
        print(problem)
    if not problems:
        print(f"{args.mode}: dependency presence, Tk and selected asset checks passed.")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
