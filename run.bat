@echo off
rem Slab Thickness Analyzer - Windows launcher
rem
rem   run.bat            double-click: run in this window (close the window to stop)
rem   run.bat start      run in the background and open the browser
rem   run.bat stop       stop the server on the port
rem   run.bat restart    stop, then start
rem   run.bat status     show whether it is running
rem   run.bat log        show the last lines of the server log
rem
rem Port: LSATS_PORT (default 8501). Extra arguments go to streamlit,
rem e.g. run.bat start --server.address 0.0.0.0
setlocal
cd /d "%~dp0"
if not defined LSATS_PORT set "LSATS_PORT=8501"
set "URL=http://localhost:%LSATS_PORT%"
set "LOG=.run\server.log"

rem Arguments after the command word go to streamlit
set "ARGS="
set "CMD=%~1"
if /i "%CMD%"=="start" goto :collect
if /i "%CMD%"=="restart" goto :collect
goto :dispatch
:collect
shift
if "%~1"=="" goto :dispatch
set ARGS=%ARGS% %1
goto :collect

:dispatch
if /i "%CMD%"=="start" goto :cmd_start
if /i "%CMD%"=="stop" goto :cmd_stop
if /i "%CMD%"=="restart" goto :cmd_restart
if /i "%CMD%"=="status" goto :cmd_status
if /i "%CMD%"=="log" goto :cmd_log
if /i "%CMD%"=="help" goto :cmd_help
if /i "%CMD%"=="/?" goto :cmd_help

rem Default (double-click, or only streamlit options): run in this window
call :prepare || exit /b 1
echo Starting Slab Thickness Analyzer: %URL%
echo        The browser opens automatically. Close this window to stop.
".venv\Scripts\python.exe" -m streamlit run app.py --server.port %LSATS_PORT% %*
goto :eof

:cmd_help
echo Usage:
echo   run.bat            run in this window - close the window to stop
echo   run.bat start      run in the background and open the browser
echo   run.bat stop       stop the server
echo   run.bat restart    stop, then start
echo   run.bat status     show whether it is running
echo   run.bat log        show the last lines of the server log
echo Port: set LSATS_PORT - default 8501
exit /b 0

:cmd_start
call :server_pid
if defined SPID (
    echo Already running: %URL%  - PID %SPID%
    exit /b 0
)
call :prepare || exit /b 1
if not exist ".run" mkdir ".run"
echo Starting Slab Thickness Analyzer in the background...
powershell -NoProfile -Command "Start-Process -FilePath '%CD%\.venv\Scripts\python.exe' -WorkingDirectory '%CD%' -ArgumentList '-m streamlit run app.py --server.headless true --server.port %LSATS_PORT%%ARGS%' -WindowStyle Hidden -RedirectStandardOutput '%CD%\%LOG%' -RedirectStandardError '%CD%\.run\server.err.log'" || goto :startfail
set /a N=0
:wait
set /a N+=1
call :healthy && goto :started
if %N% geq 90 goto :startfail
rem wait about 1 second (timeout.exe fails when input is redirected)
ping -n 2 127.0.0.1 >nul
goto :wait
:started
call :server_pid
echo Running: %URL%  - PID %SPID%, log: %LOG%
if not defined LSATS_NO_BROWSER start "" "%URL%"
exit /b 0
:startfail
echo Failed to start. Last lines of the log:
call :show_log
exit /b 1

:cmd_stop
call :server_pid
if not defined SPID (
    echo Not running - port %LSATS_PORT%.
    exit /b 0
)
if /i not "%SNAME%"=="python" (
    echo Port %LSATS_PORT% is used by another program: %SNAME% - PID %SPID%. Not stopping it.
    exit /b 1
)
taskkill /PID %SPID% /T /F >nul 2>nul
set /a N=0
:stopwait
set /a N+=1
call :server_pid
if not defined SPID goto :stopped
if %N% geq 10 goto :stopped
ping -n 2 127.0.0.1 >nul
goto :stopwait
:stopped
echo Stopped - port %LSATS_PORT%.
exit /b 0

:cmd_restart
call :cmd_stop || exit /b 1
goto :cmd_start

:cmd_status
call :server_pid
if not defined SPID (
    echo Stopped - port %LSATS_PORT%.
    exit /b 1
)
call :healthy && (
    echo Running: %URL%  - PID %SPID%
    exit /b 0
)
echo Port %LSATS_PORT% is in use by %SNAME% - PID %SPID%, but the app is not answering yet.
exit /b 0

:cmd_log
if not exist "%LOG%" (
    echo No log yet: %LOG%
    exit /b 1
)
call :show_log
exit /b 0

:show_log
powershell -NoProfile -Command "foreach ($f in '%LOG%', '.run\server.err.log') { if (Test-Path $f) { Get-Content $f -Tail 30 } }"
exit /b 0

rem ---- helpers
:server_pid
rem PID and process name listening on the port (Get-NetTCPConnection: same on any Windows language)
set "SPID="
set "SNAME="
for /f "tokens=1,2" %%A in ('powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %LSATS_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; Write-Output ($c.OwningProcess.ToString() + ' ' + $p.ProcessName) }"') do (
    set "SPID=%%A"
    set "SNAME=%%B"
)
exit /b 0

:healthy
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%/_stcore/health'; if ($r.Content -match 'ok') { exit 0 } } catch {}; exit 1" >nul 2>nul
exit /b %errorlevel%

:prepare
call :find_python || goto :nopython

rem Install packages on first run, and again whenever requirements.txt changes (e.g. after git pull)
set "NEED="
if not exist ".venv\installed.ok" set "NEED=1"
if not exist ".venv\requirements.txt" set "NEED=1"
if not defined NEED fc /b requirements.txt ".venv\requirements.txt" >nul 2>nul || set "NEED=1"
if defined NEED (
    echo Installing packages - first run or new packages, 1-3 minutes...
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
exit /b 0

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
