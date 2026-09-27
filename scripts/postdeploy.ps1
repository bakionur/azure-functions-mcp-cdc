# azd postdeploy hook: local client config + the Foundry agent. Never fails the deploy — prints what to rerun instead.
$ErrorActionPreference = 'Continue'
& "$PSScriptRoot/write-mcp-json.ps1"
$e = azd env get-values | Where-Object { $_ -match '^[A-Z0-9_]+=' } | ConvertFrom-StringData
if ($e.FOUNDRY_PROJECT_ENDPOINT -and $e.FOUNDRY_PROJECT_ENDPOINT.Trim('"')) {
  python "$PSScriptRoot/foundry_agent.py" setup
  if ($LASTEXITCODE) { Write-Host "Foundry agent setup failed — rerun: python scripts/foundry_agent.py setup (pip install -r scripts/requirements.txt first)" -ForegroundColor Yellow }
}
# API Center creates a 'Swagger Petstore' sample API; the catalog should show only our four MCP servers
if ($e.APIC_NAME -and $e.APIC_NAME.Trim('"')) { az apic api delete -g $e.RESOURCE_GROUP.Trim('"') -n $e.APIC_NAME.Trim('"') --api-id swagger-petstore --yes 2>$null | Out-Null }
