# Uploads one audit batch to Blob Storage. submit.json is uploaded LAST: its arrival triggers the audit.
#
#   powershell -ExecutionPolicy Bypass -File .\azure\scripts\submit_batch.ps1 -StorageAccount <name> `
#       -Client demo -Batch leaky_momentum -Prices demo\data\prices.csv -Positions demo\data\positions_leaky_momentum.csv `
#       -Gates demo\gates.json [-Strategy "Leaky momentum"] [-Wait]
#
# Uses your az login (Storage Blob Data Contributor, granted by main.bicep). No storage keys.

param(
    [Parameter(Mandatory)][string]$StorageAccount,
    [Parameter(Mandatory)][string]$Client,
    [Parameter(Mandatory)][string]$Batch,
    [Parameter(Mandatory)][string]$Prices,
    [Parameter(Mandatory)][string]$Positions,
    [string]$Gates = "",
    [string]$Strategy = "",
    [switch]$Wait
)
$ErrorActionPreference = "Stop"
foreach ($n in $Client, $Batch) { if ($n -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$') { throw "Invalid name: $n" } }
$prefix = "$Client/$Batch"

function Upload($file, $name) {
    az storage blob upload --auth-mode login --account-name $StorageAccount -c audit-inputs `
        -n "$prefix/$name" -f $file --overwrite --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Upload of $name failed (new role assignments can take a few minutes)." }
    Write-Host "  uploaded $name"
}

Upload $Prices "prices.csv"
Upload $Positions "positions.csv"
if ($Gates) { Upload $Gates "gates.json" }
$submit = New-TemporaryFile
@{ strategy = $(if ($Strategy) { $Strategy } else { $Batch }) } | ConvertTo-Json | Set-Content $submit -Encoding utf8
Upload $submit "submit.json"
Remove-Item $submit

if ($Wait) {
    Write-Host "Waiting for the report..."
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep 10
        $done = az storage blob exists --auth-mode login --account-name $StorageAccount -c audit-reports `
            -n "$prefix/results.json" --query exists -o tsv
        $err = az storage blob exists --auth-mode login --account-name $StorageAccount -c audit-reports `
            -n "$prefix/error.json" --query exists -o tsv
        if ($done -eq "true" -or $err -eq "true") { break }
    }
    $target = $(if ($err -eq "true") { "error.json" } else { "report.html" })
    $local = Join-Path $env:TEMP "$Client-$Batch-$target"
    az storage blob download --auth-mode login --account-name $StorageAccount -c audit-reports `
        -n "$prefix/$target" -f $local --overwrite --only-show-errors | Out-Null
    Start-Process $local
}
