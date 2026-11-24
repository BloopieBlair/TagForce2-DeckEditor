@echo off
setlocal enabledelayedexpansion

title Duelist Hub - Yu-Gi-Oh! GX: Tag Force 2 Save Editor

echo ===============================================================================
echo            DUELIST HUB - YU-GI-OH! GX TAG FORCE 2 SAVE EDITOR
echo ===============================================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python was not found on your system PATH.
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    echo Make sure to check the box "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Display Python version
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo [OK] Using !PYTHON_VER!
echo.

:: Check if cards database exists
if not exist "%~dp0cards_db.json" (
    echo [ERROR] cards_db.json was not found in the project folder!
    echo Please make sure all repository files are present.
    echo.
    pause
    exit /b 1
)

:: Start server (auto-detects save or launches Demo Mode, respects TAGFORCE_PORT)
python "%~dp0run_showcase.py" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The server exited with error code %ERRORLEVEL%.
    pause
)

endlocal
