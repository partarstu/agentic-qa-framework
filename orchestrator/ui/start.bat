@echo off
REM ============================================================================
REM Orchestrator Dashboard UI - Build and Start
REM ============================================================================
REM This script installs dependencies (if needed), builds the React UI,
REM copies it to orchestrator/static, and starts the development server.
REM 
REM The UI dev server will be available at http://localhost:5173/
REM ============================================================================

setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo ============================================
echo   Orchestrator Dashboard UI
echo ============================================
echo.

REM Check required environment variable
if "%ORCHESTRATOR_PORT%"=="" (
    echo ERROR: ORCHESTRATOR_PORT environment variable is not set.
    echo Please set it to the port number your orchestrator is running on.
    echo Example: set ORCHESTRATOR_PORT=8080
    exit /b 1
)

echo Configured Orchestrator Port: %ORCHESTRATOR_PORT%

REM Check if node_modules exists
if not exist "node_modules" (
    echo [1/3] Installing dependencies...
    call npm install
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Dependencies already installed.
)

echo [2/3] Building production bundle...
call npm run build
if errorlevel 1 (
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo [3/3] Copying to orchestrator/static...

REM Remove old static files
if exist "..\static" rmdir /s /q "..\static"

REM Copy new build
mkdir "..\static" 2>nul
xcopy /s /e /q "dist\*" "..\static\"

echo.
echo ============================================
echo   Starting UI Development Server
echo ============================================
echo.
echo UI will be available at: http://localhost:5173
echo API calls will be proxied to: http://localhost:%ORCHESTRATOR_PORT%
echo.
echo Note: The orchestrator must be running separately on port %ORCHESTRATOR_PORT%
echo.
echo Press Ctrl+C to stop the server.
echo.

call npm run dev
