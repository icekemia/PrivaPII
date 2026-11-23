@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Set up PrivaPII using the Windows instructions in README.md.
    exit /b 1
)
".venv\Scripts\python.exe" check_setup.py --mode rules
if errorlevel 1 exit /b 1
if "%~1"=="--check" exit /b 0
".venv\Scripts\python.exe" app.py
exit /b %errorlevel%
