"""Build an offline Python 3.11 Windows pilot with an explicit file allowlist."""

import argparse
import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
MODES = {"rules": "requirements/requirements.txt", "nus": "requirements/requirements-evaluation.txt",
         "ocr": "requirements/requirements-ocr.txt"}
PUBLIC_DOCS = {"README.md", "docs/Pilot_Readiness.md", "docs/OCR.md",
               "docs/Dependency_Review.md", "docs/NUS_Evaluation.md", "docs/Benchmark_Protocol.md",
               "docs/Demo_Guide.md", "docs/Development_Setup.md", "docs/PrivaPII_Action_Plan.md"}
STARTUP = {"windows/Start-PrivaPII.cmd", "windows/Setup-PrivaPII.cmd"}
PILOT_TOOLS = {"tools/__init__.py", "tools/benchmark.py", "tools/export_quality.py", "tools/ocr_smoke.py"}


def package_files():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    return sorted(name for name in tracked
                  if name in PUBLIC_DOCS | STARTUP | PILOT_TOOLS | set(MODES.values())
                  or (name.startswith("privapii/") and name.count("/") == 1 and name.endswith(".py")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="rules")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11) or platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Build the Windows x64 pilot with 64-bit Python 3.11 on Windows.")
    target = args.output or ROOT / "dist" / f"PrivaPII-Windows-{args.mode}.zip"
    checksum = target.with_suffix(".zip.sha256")
    if target.suffix.lower() != ".zip" or target.exists() or checksum.exists():
        parser.error("Choose a new .zip destination.")
    target.parent.mkdir(parents=True, exist_ok=True)
    files = package_files()
    requirement = MODES[args.mode]
    if not STARTUP <= set(files):
        parser.error("Commit the pilot setup and launcher files before building.")
    requirements = f"-r {requirement}\n"
    if args.mode != "rules":
        requirements += "torch==2.15.0+cpu\n"
    scratch = ROOT / "scratch"
    scratch.mkdir(exist_ok=True)
    assert scratch.resolve().is_relative_to(ROOT)
    with TemporaryDirectory(prefix="pilot-wheels-", dir=scratch) as directory:
        temp = Path(directory)
        assert temp.resolve().is_relative_to(scratch.resolve())
        request = [sys.executable, "-m", "pip", "--disable-pip-version-check", "download", "--only-binary=:all:",
                   "--dest", str(temp), "-r", str(ROOT / requirement)]
        if args.mode != "rules":
            request.extend(["--extra-index-url", "https://download.pytorch.org/whl/cpu", "torch==2.15.0+cpu"])
        subprocess.run(request, check=True)
        with target.open("xb") as stream, ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            for name in files:
                archive.write(ROOT / name, Path(name).name if name in STARTUP else name)
            archive.writestr("pilot-requirements.txt", requirements)
            for wheel in sorted(temp.glob("*.whl")):
                archive.write(wheel, f"wheelhouse/{wheel.name}")
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with checksum.open("x", encoding="ascii") as stream:
        stream.write(f"{digest}  {target.name}\n")
    print(f"Built {target} and {checksum}")


if __name__ == "__main__":
    main()
