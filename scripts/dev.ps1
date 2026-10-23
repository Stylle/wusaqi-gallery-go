param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) { python -m venv .venv }
    & ./.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
    if ($LASTEXITCODE) { throw 'Image worker dependency installation failed' }
    Push-Location frontend
    try {
        npm ci --no-fund --no-audit
        if ($LASTEXITCODE) { throw 'Frontend dependency installation failed' }
        npm run build
        if ($LASTEXITCODE) { throw 'Frontend build failed' }
    } finally { Pop-Location }
    Push-Location server
    try {
        go build -trimpath -ldflags='-s -w' -o gallery.exe .
        if ($LASTEXITCODE) { throw 'Go build failed' }
        $env:LISTEN_ADDR = "127.0.0.1:$Port"
        $env:PYTHON = Join-Path $projectRoot '.venv/Scripts/python.exe'
        if (-not $env:ADMIN_PASSWORD) { $env:ADMIN_PASSWORD = 'local-test' }
        Write-Host "Local gallery: http://127.0.0.1:$Port"
        ./gallery.exe
    } finally { Pop-Location }
} finally { Pop-Location }
