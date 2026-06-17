$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path $PWD '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    python -m venv .venv
}

& $python -m pip install --upgrade pip
& $python -m pip install -e '.[build]'

& $python -m PyInstaller --clean --noconfirm 'packaging\NTE History Exporter.spec'
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$exe = Join-Path $PWD 'dist\nte-history-exporter.exe'
if (-not (Test-Path $exe)) {
    throw "Expected build output was not created: $exe"
}

Write-Host "Built $exe"
& $exe --help
if ($LASTEXITCODE -ne 0) {
    throw "Built executable smoke test failed with exit code $LASTEXITCODE"
}
