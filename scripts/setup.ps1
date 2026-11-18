# Creates .venv and installs the audit tool.  Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1          # local tool
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Azure   # plus the Azure SDKs
param([switch]$Azure)
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.12 -m venv .venv; if ($LASTEXITCODE -ne 0) { python -m venv .venv } }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
$extras = if ($Azure) { ".[dev,azure]" } else { ".[dev]" }
& .\.venv\Scripts\python.exe -m pip install -e $extras
& .\.venv\Scripts\python.exe -m pytest
