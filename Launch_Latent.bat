@echo off
setlocal enabledelayedexpansion
title LATENT // Launcher & Setup Sequencer

:: Navigate to the directory where this batch file is located
cd /d "%~dp0"

:: 1. Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ================================================================
    echo [ERROR] Python was not found on your system!
    echo ================================================================
    echo LATENT requires Python 3.10 or higher.
    echo.
    echo Please download and install Python from the official site.
    echo IMPORTANT: Make sure to check the box "Add Python to PATH" 
    echo during installation.
    echo.
    echo Opening Python download page in your browser...
    start "" "https://www.python.org/downloads/"
    echo.
    pause
    exit /b
)

:: 2. Check and install missing dependencies
echo Checking required libraries...
python -c "import cv2, numpy, PIL, watchdog" >nul 2>&1
if errorlevel 1 (
    echo ================================================================
    echo Missing libraries detected. Starting automatic installation...
    echo ================================================================
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Dependency installation failed!
        echo Please ensure you are connected to the internet and try running 
        echo this batch file as an Administrator.
        echo.
        pause
        exit /b
    )
    echo Dependencies successfully installed!
)

:: 3. Launch the application
echo Starting LATENT...
start "" pythonw.exe latent.py
if errorlevel 1 (
    echo [WARNING] pythonw.exe failed to start. Falling back to console mode...
    python.exe latent.py
)

exit
