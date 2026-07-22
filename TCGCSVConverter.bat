@echo off
setlocal

cd /d "%~dp0"

if exist ".conda\python.exe" (
    ".conda\python.exe" "tcg_csv_converter_gui.py"
    goto :eof
)

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 "tcg_csv_converter_gui.py"
    goto :eof
)

where python >nul 2>&1
if %errorlevel%==0 (
    python "tcg_csv_converter_gui.py"
    goto :eof
)

echo Could not find a Python executable.
echo Install Python 3 or run from the configured environment.
pause
