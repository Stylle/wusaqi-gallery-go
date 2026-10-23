@echo off
rem Build and push the single wusaqi-gallery image to Docker Hub (Windows).
rem Usage: run from repo root on a machine where docker login is done.
setlocal enabledelayedexpansion

set PREFIX=stylle
if not "%IMAGE_PREFIX%"=="" set PREFIX=%IMAGE_PREFIX%

set VERSION=
for /f %%i in ('git rev-parse --short HEAD') do set VERSION=%%i
if "%VERSION%"=="" goto :fail
if "%PLATFORMS%"=="" set PLATFORMS=linux/amd64,linux/arm64

set IMAGE=%PREFIX%/wusaqi-gallery

echo ==^> Building %IMAGE%:%VERSION%
docker buildx build --platform %PLATFORMS% -t %IMAGE%:%VERSION% -t %IMAGE%:latest --push . || goto :fail

echo.
echo Done. Deploy: docker compose -f docker-compose.hub.yml pull ^&^& up -d
exit /b 0

:fail
echo BUILD/PUSH FAILED
exit /b 1
