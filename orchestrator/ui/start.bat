@echo off
REM ============================================================================
REM Orchestrator Dashboard UI - Build and Start
REM ============================================================================
REM This script builds the React UI for production and copies it to the
REM orchestrator/static folder, then starts the orchestrator backend.
REM 
REM The dashboard will be available at http://localhost:8080/
REM ============================================================================

setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo ============================================
echo   Orchestrator Dashboard UI
echo ============================================
echo.

REM Check if node_modules exists
if not exist "node_modules" (
    echo [1/4] Installing dependencies...
    call npm install
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Dependencies already installed.
)

echo [2/4] Building production bundle...
call npm run build
if errorlevel 1 (
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo [3/4] Copying to orchestrator/static...

REM Remove old static files
if exist "..\static" rmdir /s /q "..\static"

REM Copy new build
mkdir "..\static" 2>nul
xcopy /s /e /q "dist\*" "..\static\"

echo [4/4] Starting orchestrator...
echo.
echo ============================================
echo   Dashboard ready at http://localhost:8080
echo ============================================
echo.
echo Press Ctrl+C to stop the server.
echo.

cd /d "%~dp0..\.."
python -m uvicorn orchestrator.main:orchestrator_app --host 0.0.0.0 --port 8080 --reload
