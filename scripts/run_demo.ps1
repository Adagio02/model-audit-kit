# Builds the synthetic demo market and audits the three example strategies.
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Run .\scripts\setup.ps1 first." }
& $Py demo\make_demo.py
foreach ($s in "honest_momentum", "leaky_momentum", "high_turnover_reversal") {
    & $Py -m modelaudit run --prices demo\data\prices.csv --positions "demo\data\positions_$s.csv" `
        --gates demo\gates.json --name $s --out "demo\reports\$s"
}
Start-Process "demo\reports\leaky_momentum\report.html"
