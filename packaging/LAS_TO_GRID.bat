@echo off
rem Convert LAS/LAZ point clouds (one file per floor) to grid CSV files for L-SATS.
rem Drag and drop the folder that has the LAS files onto this file.
setlocal
cd /d "%~dp0"
set "F=%~1"
if "%F%"=="" set /p F=Folder with LAS files: 
if "%F%"=="" goto :eof
"%~dp0python\python.exe" -m slab.las "%F%"
echo.
echo Done. Open L-SATS (START.bat) and upload the CSV files in the LSATS_grid folder.
pause
