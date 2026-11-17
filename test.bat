@echo off
rem Run automated tests on Windows.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto :run
call :find_python || (
    echo Python 3.11 or later is required: https://www.python.org/downloads/windows/
    exit /b 1
)
%PY% -m venv .venv || exit /b 1
:run
".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt || exit /b 1
".venv\Scripts\python.exe" -m pytest %*
exit /b

:find_python
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
