# Deletes everything deploy.ps1 created, so nothing keeps billing.
#   powershell -ExecutionPolicy Bypass -File .\azure\scripts\teardown.ps1 -ResourceGroup rg-model-audit
param([Parameter(Mandatory)][string]$ResourceGroup)
$ErrorActionPreference = "Stop"
$ok = Read-Host "Delete resource group '$ResourceGroup' and everything in it? Type the name to confirm"
if ($ok -ne $ResourceGroup) { Write-Host "Cancelled."; exit 1 }
# Key Vault and Foundry are soft-deleted; list them now so they can be purged afterwards.
$vaults = az keyvault list -g $ResourceGroup --query "[].name" -o tsv
$ai = az cognitiveservices account list -g $ResourceGroup --query "[].{n:name,l:location}" -o json | ConvertFrom-Json
az group delete -n $ResourceGroup --yes
foreach ($v in $vaults) { az keyvault purge -n $v --only-show-errors }
foreach ($a in $ai) { az cognitiveservices account purge -n $a.n -g $ResourceGroup -l $a.l --only-show-errors }
Write-Host "Deleted. Check Cost Management in a day to confirm spend has stopped."
