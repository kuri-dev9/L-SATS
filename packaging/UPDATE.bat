@echo off
rem L-SATS updater: downloads only the program files (about 1 MB), not Python.
rem This file is never replaced by the update itself, so it is safe to run.
setlocal
cd /d "%~dp0"
if not exist "python\python.exe" (
    echo [ERROR] Run UPDATE.bat inside the extracted L-SATS folder.
    pause
    exit /b 1
)
if not exist "tools\update.ps1" (
    echo [ERROR] tools\update.ps1 is missing. Download the full ZIP again:
    echo https://github.com/kuri-dev9/L-SATS/releases/latest/download/L-SATS-windows.zip
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\update.ps1" %*
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
rem Success: the program was started again by update.ps1. Close this window after a moment.
ping -n 4 127.0.0.1 >nul
