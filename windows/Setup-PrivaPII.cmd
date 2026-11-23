@echo off
setlocal
cd /d "%~dp0"
if not exist "wheelhouse\*.whl" (
    echo Run setup from an extracted PrivaPII pilot package with a wheelhouse.
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    python -c "import sys, tkinter; assert sys.version_info[:2] == (3, 11)"
    if errorlevel 1 (
        echo Install 64-bit Python 3.11 with Tk and put python.exe on PATH.
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip --disable-pip-version-check install --no-index --find-links wheelhouse -r pilot-requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip --disable-pip-version-check check
if errorlevel 1 exit /b 1
call Start-PrivaPII.cmd --check
exit /b %errorlevel%
