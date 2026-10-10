@echo off
rem Starts Open DyePrint. Photos can be dropped onto this file or passed as arguments.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    echo Setting up Open DyePrint for the first time...
    python -m venv .venv || goto :error
    .venv\Scripts\python -m pip install --quiet --upgrade pip
    .venv\Scripts\python -m pip install --quiet -e . || goto :error
)
start "" .venv\Scripts\pythonw.exe -m opendyeprint %*
exit /b 0
:error
echo Setup failed. Is Python 3.10+ installed and on PATH?
pause
