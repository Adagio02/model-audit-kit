# Creates .venv and installs the audit tool.  Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.12 -m venv .venv; if ($LASTEXITCODE -ne 0) { python -m venv .venv } }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& .\.venv\Scripts\python.exe -m pytest
