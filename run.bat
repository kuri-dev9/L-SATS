@echo off
rem Slab Thickness Analyzer - Windows launcher
rem Double-click to run. First run creates .venv and installs packages.
setlocal
cd /d "%~dp0"

call :find_python || goto :nopython

if not exist ".venv\installed.ok" (
    echo [1/2] Creating virtual environment and installing packages - first run only, 1-3 minutes...
    if not exist ".venv\Scripts\python.exe" (
        %PY% -m venv .venv || goto :fail
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
    echo ok> ".venv\installed.ok"
)

rem Skip Streamlit's first-run email prompt
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo [2/2] Starting Slab Thickness Analyzer: http://localhost:8501
echo        The browser opens automatically. Close this window to stop.
".venv\Scripts\python.exe" -m streamlit run app.py %*
goto :eof

:find_python
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3" && exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python" && exit /b 0
exit /b 1

:nopython
echo.
echo Python 3.11 or later is required.
echo Download: https://www.python.org/downloads/windows/
echo During installation, check "Add python.exe to PATH".
pause
exit /b 1

:fail
echo.
echo Installation failed. Check the internet connection or proxy settings, then run again.
pause
exit /b 1
