@echo off
setlocal

echo Checking Docker availability...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Docker is not installed or not in the PATH. Please install Docker Desktop.
    exit /b 1
)

set CONTAINER_NAME=qdrant
set IMAGE_NAME=qdrant/qdrant
set PORT_MAPPING=6333:6333 -p 6334:6334
set VOLUME_NAME=qdrant_data
set VOLUME_MAPPING=/qdrant/storage

echo Checking status of container '%CONTAINER_NAME%'...

REM Initialize variables
set RUNNING_ID=
set STOPPED_ID=

REM Check if container is running
for /f "tokens=*" %%i in ('docker ps -q -f "name=^/%CONTAINER_NAME%$"') do set RUNNING_ID=%%i

if defined RUNNING_ID (
    echo Container '%CONTAINER_NAME%' is already running on port 6333.
    exit /b 0
)

REM Check if container exists (but stopped)
for /f "tokens=*" %%i in ('docker ps -aq -f "name=^/%CONTAINER_NAME%$"') do set STOPPED_ID=%%i

if defined STOPPED_ID (
    echo Container '%CONTAINER_NAME%' exists but is stopped. Starting it...
    docker start %CONTAINER_NAME%
    if %errorlevel% equ 0 (
        echo Container '%CONTAINER_NAME%' started successfully.
    ) else (
        echo Failed to start container '%CONTAINER_NAME%'.
    )
    exit /b 0
)

REM Container does not exist, run a new one
echo Container '%CONTAINER_NAME%' not found. Creating and starting a new container...
echo Ensuring image '%IMAGE_NAME%' is available...
docker pull %IMAGE_NAME%

echo Running container...
docker run -d --name %CONTAINER_NAME% -p %PORT_MAPPING% -v %VOLUME_NAME%:%VOLUME_MAPPING% %IMAGE_NAME%

if %errorlevel% equ 0 (
    echo Container '%CONTAINER_NAME%' started successfully.
) else (
    echo Failed to start container '%CONTAINER_NAME%'.
)

endlocal
