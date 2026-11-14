@echo off
rem Run automated tests on Windows.
setlocal
cd /d "%~dp0"
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python 3.10 or later is required: https://www.python.org/downloads/windows/
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv || exit /b 1
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt || exit /b 1
".venv\Scripts\python.exe" -m pytest %*
