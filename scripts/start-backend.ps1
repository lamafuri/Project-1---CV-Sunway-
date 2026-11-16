# Start backend (Windows Python venv)
$repoRoot = Split-Path $PSScriptRoot -Parent
$backendDir = Join-Path $repoRoot "backend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$systemPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"

# Docker Desktop's CLI may be missing from PATH in an already-open VS Code shell.
if (Test-Path (Join-Path $dockerBin "docker.exe")) {
    $env:PATH = "$dockerBin;$env:PATH"
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating venv..."
    if (-not (Test-Path $systemPython)) {
        Write-Host "Python 3.12 not found. Install with: winget install Python.Python.3.12" -ForegroundColor Red
        exit 1
    }
    & $systemPython -m venv (Join-Path $backendDir ".venv")
    & $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")
}

# config.py anchors .env and relative paths to the repo root, so the working
# directory does not matter for settings. --app-dir puts the `app` package on
# the path without changing the working directory.
Set-Location $repoRoot
& $venvPython -m uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000
