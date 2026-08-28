@echo off
REM Launch SafeClean without a console window.
REM Double-click this file, or make a shortcut to it.

setlocal
set "HERE=%~dp0"

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%HERE%main.py"
    exit /b 0
)

where python >nul 2>&1
if %errorlevel%==0 (
    start "" python "%HERE%main.py"
    exit /b 0
)

echo Python was not found on this PC.
echo Install Python 3.10 or newer from https://python.org/downloads
echo Make sure "Add python.exe to PATH" is ticked during setup.
pause
exit /b 1
