@echo off
rem L-SATS update for a folder made with "git clone": double-click to get the newest version and restart.
rem run.bat does the work (git pull, packages, restart). The portable ZIP has its own UPDATE.bat.
setlocal
cd /d "%~dp0"
if not exist ".git\" (
    echo [ERROR] This folder was not made with git.
    echo If you use the portable ZIP, run the UPDATE.bat inside that folder instead.
    pause
    exit /b 1
)
call run.bat restart
if errorlevel 1 (
    echo.
    echo [ERROR] The program did not start. Send a screenshot of this window.
    pause
    exit /b 1
)
echo.
echo Done. If the browser was already open, press F5 to refresh.
ping -n 4 127.0.0.1 >nul
