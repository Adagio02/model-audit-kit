# Deploys the Model Audit Kit to Azure (Phase 1). Run from the project folder in PowerShell:
#
#   az login
#   powershell -ExecutionPolicy Bypass -File .\azure\scripts\deploy.ps1 -ResourceGroup rg-model-audit -AlertEmail you@example.com
#
# Needs: Azure CLI (az), Azure Functions Core Tools v4 (func), and the project's .venv
# with the azure extras (scripts\setup.ps1 -Azure). Safe to re-run: every step is idempotent.

param(
    [Parameter(Mandatory)][string]$ResourceGroup,
    [string]$Location = "eastus2",
    [string]$Prefix = "maudit",
    [string]$AlertEmail = "",
    [int]$MonthlyBudget = 10,
    [switch]$SkipFoundry,
    [string]$FoundryLocation = "",
    [string]$SqlLocation = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$Py = ".\.venv\Scripts\python.exe"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (see the error above). Fix it and re-run; every step is safe to repeat." } }
function Need($cmd, $hint) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" } }

Need az   "Install the Azure CLI: winget install Microsoft.AzureCLI"
Need func "Install Functions Core Tools: winget install Microsoft.Azure.FunctionsCoreTools"
if (-not (Test-Path $Py)) { throw "Run .\scripts\setup.ps1 -Azure first." }

Step "Checking your Azure sign-in"
$me = az ad signed-in-user show --query "{id:id, upn:userPrincipalName}" -o json | ConvertFrom-Json
Check "Reading your signed-in user"
$sub = az account show --query name -o tsv
Write-Host "Signed in as $($me.upn), subscription '$sub'"
$ip = (Invoke-RestMethod -Uri "https://api.ipify.org")
foreach ($ns in "Microsoft.Web", "Microsoft.Sql", "Microsoft.KeyVault", "Microsoft.EventGrid",
                "Microsoft.CognitiveServices", "Microsoft.OperationalInsights", "Microsoft.Insights") {
    az provider register --namespace $ns --only-show-errors | Out-Null
}

Step "Creating resource group $ResourceGroup in $Location"
az group create -n $ResourceGroup -l $Location --only-show-errors | Out-Null
Check "Creating the resource group"

Step "Deploying infrastructure (Bicep) - takes about 5 minutes"
$params = @("prefix=$Prefix", "deployerObjectId=$($me.id)", "deployerLogin=$($me.upn)", "clientIp=$ip",
            "deployFoundry=$((-not $SkipFoundry).ToString().ToLower())", "alertEmail=$AlertEmail", "monthlyBudget=$MonthlyBudget")
if ($FoundryLocation) { $params += "foundryLocation=$FoundryLocation" }
if ($SqlLocation) { $params += "sqlLocation=$SqlLocation" }
$out = az deployment group create -g $ResourceGroup -n model-audit -f azure\infra\main.bicep `
    --parameters $params --query properties.outputs -o json | ConvertFrom-Json
Check "The infrastructure deployment"
$app = $out.functionAppName.value
$sql = $out.sqlServerFqdn.value
$dbName = $out.sqlDatabaseName.value
$storage = $out.storageAccountName.value
Write-Host "Function App: $app`nSQL: $sql/$dbName`nStorage: $storage`nKey Vault: $($out.keyVaultName.value)"

Step "Creating SQL tables and views, and granting the Function's identity access"
& $Py azure\scripts\apply_sql.py --server $sql --database $dbName --file azure\sql\schema.sql
Check "Creating the SQL schema"
& $Py azure\scripts\apply_sql.py --server $sql --database $dbName --file azure\sql\grant_function_identity.sql --var "APP_NAME=$app"
Check "Granting SQL access"

Step "Packaging and publishing the function code (remote build)"
$pkg = "azure\function_app\modelaudit"
if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
Copy-Item src\modelaudit $pkg -Recurse
Get-ChildItem $pkg -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Push-Location azure\function_app
try { func azure functionapp publish $app --python; Check "Publishing the function code" } finally { Pop-Location }

Step "Connecting Blob Storage events to the function (Event Grid)"
$key = $null
for ($i = 0; $i -lt 12 -and -not $key; $i++) {
    $key = az functionapp keys list -g $ResourceGroup -n $app --query "systemKeys.blobs_extension" -o tsv
    if (-not $key) { Write-Host "  waiting for the function host to start..."; Start-Sleep 10 }
}
if (-not $key) { throw "No blobs_extension key yet. Wait a minute and re-run this script." }
$hostName = az functionapp show -g $ResourceGroup -n $app --query defaultHostName -o tsv
$endpoint = "https://$hostName/runtime/webhooks/blobs?functionName=Host.Functions.AuditOnSubmit&code=$key"
$topic = "$Prefix-storage-events"
# "list" + filter instead of "show": show writes an error when the topic doesn't exist yet,
# which Windows PowerShell 5.1 turns into a terminating error under ErrorActionPreference=Stop.
$existing = az eventgrid system-topic list -g $ResourceGroup --query "[?name=='$topic'].name" -o tsv
Check "Listing Event Grid topics"
if (-not $existing) {
    az eventgrid system-topic create -g $ResourceGroup -n $topic -l $Location `
        --topic-type Microsoft.Storage.StorageAccounts --source $out.storageAccountId.value --only-show-errors | Out-Null
    Check "Creating the Event Grid topic"
}
# The endpoint contains '&', which cmd.exe (az runs through az.cmd) would treat as a command separator.
# Azure CLI reads an argument from a file when it starts with '@', so pass it that way.
$endpointFile = New-TemporaryFile
[IO.File]::WriteAllText($endpointFile.FullName, $endpoint)
az eventgrid system-topic event-subscription create -g $ResourceGroup --system-topic-name $topic -n audit-submit `
    --endpoint-type webhook --endpoint "@$($endpointFile.FullName)" --included-event-types Microsoft.Storage.BlobCreated `
    --subject-begins-with /blobServices/default/containers/audit-inputs/ --subject-ends-with submit.json `
    --only-show-errors | Out-Null
$subscriptionExit = $LASTEXITCODE
Remove-Item $endpointFile
$LASTEXITCODE = $subscriptionExit
Check "Creating the Event Grid subscription"

Step "Done"
Write-Host @"
Try it with the demo data:
  powershell -ExecutionPolicy Bypass -File .\azure\scripts\submit_batch.ps1 -StorageAccount $storage -Client demo -Batch leaky_momentum ``
      -Prices demo\data\prices.csv -Positions demo\data\positions_leaky_momentum.csv -Gates demo\gates.json
Then check: Azure portal > $app > Monitor, the audit-reports container, and SQL: SELECT * FROM audit.v_findings
"@
