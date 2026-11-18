# Runs the cloud pipeline on your PC with no Azure account: local-cloud\ stands in for Blob Storage
# and local-cloud\results.db (SQLite) stands in for Azure SQL. Then exports CSVs for Power BI.
#   powershell -ExecutionPolicy Bypass -File .\azure\scripts\run_local_pipeline.ps1
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Run .\scripts\setup.ps1 first." }
if (-not (Test-Path "demo\data\prices.csv")) { & $Py demo\make_demo.py }
foreach ($s in "honest_momentum", "leaky_momentum", "leaky_momentum_fixed", "high_turnover_reversal") {
    & $Py -m modelaudit stage --root local-cloud --client demo --batch $s --prices demo\data\prices.csv `
        --positions "demo\data\positions_$s.csv" --gates demo\gates.json --name $s
    & $Py -m modelaudit pipeline --root local-cloud --client demo --batch $s
}
& $Py -m modelaudit export --db local-cloud\results.db --out local-cloud\powerbi
Write-Host "`nReports: local-cloud\audit-reports\demo\   Power BI CSVs: local-cloud\powerbi\"
