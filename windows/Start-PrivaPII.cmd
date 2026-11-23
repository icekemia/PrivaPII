@echo off
setlocal
cd /d "%~dp0"
if not exist "privapii\app.py" cd ..
if not exist ".venv\Scripts\python.exe" (
    echo Set up PrivaPII using the Windows instructions in README.md.
    exit /b 1
)
".venv\Scripts\python.exe" -m privapii.check_setup --mode rules
if errorlevel 1 exit /b 1
if "%~1"=="--check" exit /b 0
".venv\Scripts\python.exe" -m privapii.app
exit /b %errorlevel%
