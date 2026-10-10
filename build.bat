@echo off
rem Builds dist\OpenDyePrint\OpenDyePrint.exe (a folder you can copy anywhere).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    python -m venv .venv || goto :error
)
.venv\Scripts\python -m pip install --quiet -e .[dev] || goto :error
.venv\Scripts\python packaging\make_icon.py || goto :error
.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name OpenDyePrint ^
    --icon src\opendyeprint\assets\opendyeprint.ico ^
    --add-data "src\opendyeprint\assets;opendyeprint\assets" ^
    --collect-binaries pi_heif ^
    --distpath dist --workpath "%TEMP%\opendyeprint-build" ^
    packaging\launch.py || goto :error
.venv\Scripts\python packaging\collect_licenses.py || goto :error
echo.
if exist build rmdir /s /q build
echo Built dist\OpenDyePrint\OpenDyePrint.exe  (run this one; keep the _internal folder next to it)
exit /b 0
:error
echo Build failed.
exit /b 1
