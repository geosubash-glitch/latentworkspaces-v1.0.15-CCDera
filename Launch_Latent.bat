@echo off
setlocal
title Latent Studio
rem Run Latent Studio from source. Most people should use the installer from the
rem Releases page instead; this is for running the code directly.

cd /d "%~dp0"

rem 1. Find Python 3.9+ (prefer the py launcher that python.org installs)
set "PY="
where py >nul 2>&1 && py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Latent Studio needs Python 3.9 or newer.
    echo.
    echo Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

rem 2. Private environment next to the app, so nothing is installed system-wide
if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up Latent Studio. This takes a minute...
    %PY% -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -c "import cv2, numpy, PIL" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
)

rem 3. Launch without a console window
start "" ".venv\Scripts\pythonw.exe" -m latent %*
exit /b 0

:fail
echo.
echo Setup failed. Check your internet connection and try again.
echo If it keeps failing, delete the .venv folder next to this file and retry.
pause
exit /b 1
