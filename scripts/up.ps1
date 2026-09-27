<#
  One-shot spin-up, the day before. All inputs come from settings.env (copy settings.env.sample):
    ./scripts/up.ps1
  Prereqs: az login (azd config set auth.useAzCliAuth true), Python 3.13 venv with scripts/requirements.txt, Node 20+.
  Deploys: 4 Flex MCP apps (concierge self-hosted, ado Entra-protected, skywatch, domainforge), API Center, Foundry
  project + gpt-5.4-mini; postdeploy writes .vscode/mcp.json and creates the Foundry agent; then smoke-tests.
#>
param([string]$File = "$PSScriptRoot/../settings.env")
$ErrorActionPreference = 'Stop'
Set-Location "$PSScriptRoot/.."
& "$PSScriptRoot/apply-settings.ps1" -File $File
$e = azd env get-values | Where-Object { $_ -match '^[A-Z0-9_]+=' } | ConvertFrom-StringData
az account set --subscription $e.AZURE_SUBSCRIPTION_ID.Trim('"')
az group create -n $e.AZURE_RESOURCE_GROUP.Trim('"') -l $e.AZURE_LOCATION.Trim('"') -o none
azd up --no-prompt
if ($LASTEXITCODE) { throw "azd up failed" }
python ./scripts/smoke.py
Write-Host "`nDone. VS Code → Copilot Chat → Configure Tools: 6 MCP servers. Sign in to adopilot-remote once (Entra)." -ForegroundColor Green
