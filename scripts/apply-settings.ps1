<#
  Pushes settings.env into the azd environment (creates/selects it). Optional: -Provision to apply to Azure right away.
    ./scripts/apply-settings.ps1              # just sync values
    ./scripts/apply-settings.ps1 -Provision   # sync + azd provision (app settings, feature switches)
#>
param([string]$File = "$PSScriptRoot/../settings.env", [switch]$Provision)
$ErrorActionPreference = 'Stop'
Set-Location "$PSScriptRoot/.."
if (-not (Test-Path $File)) { throw "No $File — copy settings.env.sample to settings.env and fill it in." }
$s = [ordered]@{}
foreach ($line in Get-Content $File) {
  if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$') { $s[$Matches[1]] = $Matches[2] }
}
if (-not $s.AZURE_SUBSCRIPTION_ID) { throw "AZURE_SUBSCRIPTION_ID is required in settings.env" }
if ($s.ADO_PROJECT -and -not $s.ADO_TEAM) { $s.ADO_TEAM = "$($s.ADO_PROJECT) Team" }
$envName = if ($s.AZURE_ENV_NAME) { $s.AZURE_ENV_NAME } else { 'cdc' }
$s.AZURE_RESOURCE_GROUP = "rg-mcp-$envName"

azd env new $envName --subscription $s.AZURE_SUBSCRIPTION_ID --location $s.AZURE_LOCATION --no-prompt 2>$null | Out-Null
azd env select $envName
foreach ($k in $s.Keys) {
  if ($k -in 'AZURE_ENV_NAME', 'AZURE_TENANT_ID') { continue }
  azd env set $k "$($s[$k])" | Out-Null
  $shown = if ($k -match 'PAT|KEY|SECRET') { if ($s[$k]) { '***' } else { '' } } else { $s[$k] }
  Write-Host ("  {0,-24} {1}" -f $k, $shown)
}
Write-Host "azd env '$envName' updated from settings.env" -ForegroundColor Green
if ($Provision) {
  azd provision --no-prompt; if ($LASTEXITCODE) { throw "azd provision failed" }
  & "$PSScriptRoot/postdeploy.ps1"
}
