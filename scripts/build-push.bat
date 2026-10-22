@echo off
rem Build and push wusaqi-gallery images to Docker Hub (Windows).
rem Usage: run from repo root on a machine where docker login is done.
setlocal enabledelayedexpansion

set PREFIX=stylle
if not "%IMAGE_PREFIX%"=="" set PREFIX=%IMAGE_PREFIX%

set VERSION=dev
for /f %%i in ('git rev-parse --short HEAD') do set VERSION=%%i

set API_IMAGE=%PREFIX%/wusaqi-api
set WEB_IMAGE=%PREFIX%/wusaqi-web

echo ==^> Building %API_IMAGE%:%VERSION%
docker build -t %API_IMAGE%:%VERSION% -t %API_IMAGE%:latest .\backend || goto :fail

echo ==^> Building %WEB_IMAGE%:%VERSION%
docker build -t %WEB_IMAGE%:%VERSION% -t %WEB_IMAGE%:latest .\frontend || goto :fail

echo ==^> Pushing (4 tags)
docker push %API_IMAGE%:%VERSION% || goto :fail
docker push %API_IMAGE%:latest || goto :fail
docker push %WEB_IMAGE%:%VERSION% || goto :fail
docker push %WEB_IMAGE%:latest || goto :fail

echo.
echo Done. Deploy on NAS with docker-compose.hub.yml
exit /b 0

:fail
echo BUILD/PUSH FAILED
exit /b 1
