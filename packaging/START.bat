@echo off
rem L-SATS portable launcher (Python included - no installation needed)
setlocal
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1

if not exist "python\python.exe" (
    echo [ERROR] The "python" folder is missing.
    echo Extract the whole ZIP file first, then run START.bat from the extracted folder.
    pause
    exit /b 1
)

rem Skip Streamlit's first-run email prompt
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo ============================================================
echo  L-SATS Slab Thickness Analyzer
echo  The browser opens automatically: http://localhost:8501
echo  Keep this window open while using the program.
echo  Close this window to stop the program.
echo ============================================================
"python\python.exe" -m streamlit run app.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] The program stopped with an error. Send a screenshot of this window.
    pause
)
