Set-Location $PSScriptRoot

Write-Host "=============================================================="
Write-Host "CONDUIT SAFE SETUP LAUNCHER"
Write-Host "=============================================================="
Write-Host ""

# Never use .venv\Scripts\python.exe here. If the venv is corrupt, Python
# fails before setup.py can repair it.

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py setup.py
    exit $LASTEXITCODE
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & python setup.py
    exit $LASTEXITCODE
}

Write-Host "[FAILED] No system Python launcher was found."
Write-Host "Install Python, then run SETUP_CONDUIT.ps1 again."
exit 1
