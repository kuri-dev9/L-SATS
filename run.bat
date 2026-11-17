@echo off
rem Slab Thickness Analyzer - Windows launcher
rem Double-click to run. First run creates .venv and installs packages.
setlocal
cd /d "%~dp0"

call :find_python
rem Prefer py / python on PATH. On some PCs these are the Microsoft Store aliases (WindowsApps)
rem that fail with "The file cannot be accessed by the system", so then look in the usual install folders.
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3" && exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python" && exit /b 0
for %%V in (3.13 3.12 3.14 3.11 3.15) do call :try_python "%LOCALAPPDATA%\Python\pythoncore-%%V-64\python.exe"
for %%V in (313 312 314 311 315) do call :try_python "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
for %%V in (313 312 314 311 315) do call :try_python "%ProgramFiles%\Python%%V\python.exe"
call :try_python "%LOCALAPPDATA%\Python\bin\python.exe"
if defined PY exit /b 0
exit /b 1

:try_python
if defined PY exit /b 0
if not exist "%~1" exit /b 1
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul || exit /b 1
set PY="%~1"
exit /b 0

:nopython

rem Install packages on first run, and again whenever requirements.txt changes (e.g. after git pull)
set "NEED="
if not exist ".venv\installed.ok" set "NEED=1"
if not exist ".venv\requirements.txt" set "NEED=1"
if not defined NEED fc /b requirements.txt ".venv\requirements.txt" >nul 2>nul || set "NEED=1"
if defined NEED (
    echo [1/2] Installing packages - first run or new packages, 1-3 minutes...
    if not exist ".venv\Scripts\python.exe" (
        echo        Python: %PY%
        %PY% -m venv .venv || goto :fail
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
    copy /y requirements.txt ".venv\requirements.txt" >nul
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
