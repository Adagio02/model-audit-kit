# Audits one client's files.  Put their CSVs in clients\<name>\input\ first.
#   powershell -ExecutionPolicy Bypass -File .\scripts\audit_client.ps1 -Client acme -Strategy "Acme L/S"
param([Parameter(Mandatory)][string]$Client, [string]$Strategy = $Client)
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$In = "clients\$Client\input"
$Gates = if (Test-Path "$In\gates.json") { "$In\gates.json" } else { "templates\gates_default.json" }
$Out = "clients\$Client\report_" + (Get-Date -Format "yyyy-MM-dd")
& .\.venv\Scripts\python.exe -m modelaudit run --prices "$In\prices.csv" --positions "$In\positions.csv" `
    --gates $Gates --name $Strategy --out $Out
Start-Process "$Out\report.html"
