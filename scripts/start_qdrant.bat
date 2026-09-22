@echo off
setlocal

REM Starts the local Qdrant used by every local run (QDRANT_URL=http://localhost:6333, no API key).
REM The image tag matches the deployed Qdrant (_QDRANT_IMAGE_TAG in cloudbuild.yaml); QDRANT_IMAGE_TAG overrides it.
REM The ports are published on 127.0.0.1 only, because the local instance runs without an API key.

echo Checking Docker availability...
docker --version >nul 2>&1
if errorlevel 1 (
    echo Docker is not installed or not in the PATH. Please install Docker Desktop.
    exit /b 1
)

set CONTAINER_NAME=qdrant
if not defined QDRANT_IMAGE_TAG set QDRANT_IMAGE_TAG=v1.19.1
set IMAGE_NAME=qdrant/qdrant:%QDRANT_IMAGE_TAG%
set PORT_MAPPING=-p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334
set VOLUME_NAME=qdrant_data
set VOLUME_MAPPING=/qdrant/storage
set READY_URL=http://localhost:6333/readyz

echo Checking status of container '%CONTAINER_NAME%'...

REM Initialize variables
set RUNNING_ID=
set STOPPED_ID=

REM Check if container is running
for /f "tokens=*" %%i in ('docker ps -q -f "name=^/%CONTAINER_NAME%$"') do set RUNNING_ID=%%i

if defined RUNNING_ID (
    echo Container '%CONTAINER_NAME%' is already running on port 6333.
    goto wait_until_ready
)

REM Check if container exists (but stopped)
for /f "tokens=*" %%i in ('docker ps -aq -f "name=^/%CONTAINER_NAME%$"') do set STOPPED_ID=%%i

if defined STOPPED_ID (
    echo Container '%CONTAINER_NAME%' exists but is stopped. Starting it...
    docker start %CONTAINER_NAME% >nul
    if errorlevel 1 goto start_failed
    goto wait_until_ready
)

REM Container does not exist, run a new one
echo Container '%CONTAINER_NAME%' not found. Creating it from '%IMAGE_NAME%'...
docker run -d --name %CONTAINER_NAME% %PORT_MAPPING% -v %VOLUME_NAME%:%VOLUME_MAPPING% %IMAGE_NAME% >nul
if errorlevel 1 goto start_failed

:wait_until_ready
echo Waiting for Qdrant to become ready...
for /l %%n in (1,1,30) do (
    curl -fs %READY_URL% >nul 2>&1 && goto ready
    timeout /t 1 /nobreak >nul
)
echo Qdrant did not become ready within 30 seconds; check 'docker logs %CONTAINER_NAME%'.
exit /b 1

:ready
echo Qdrant is ready at http://localhost:6333.
exit /b 0

:start_failed
echo Failed to start container '%CONTAINER_NAME%'.
exit /b 1
