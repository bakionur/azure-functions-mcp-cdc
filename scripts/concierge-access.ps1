# Switch the concierge (self-hosted MCP server) between public and key-protected, no redeploy.
#   ./scripts/concierge-access.ps1 public      # anyone with the URL (Claude / ChatGPT connectors, the audience)
#   ./scripts/concierge-access.ps1 protected   # function key required again (default)
#   ./scripts/concierge-access.ps1 status
# How: app setting AzureFunctionsJobHost__customHandler__http__defaultAuthorizationLevel overrides
# host.json customHandler.http.defaultAuthorizationLevel (default "function"). The app restarts (~30 s).
# `azd provision` rewrites app settings from Bicep, so it also resets the app to protected.
# Read-only tools over public agenda data only; still: switch back after the session.
param([Parameter(Mandatory)][ValidateSet('public', 'protected', 'status')][string]$Mode)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$e = @{}; azd env get-values | ForEach-Object { if ($_ -match '^([A-Z0-9_]+)="?(.*?)"?$') { $e[$Matches[1]] = $Matches[2] } }
$rg, $app, $url = $e.RESOURCE_GROUP, $e.APP_CONCIERGE, $e.MCP_CONCIERGE_URL
$setting = 'AzureFunctionsJobHost__customHandler__http__defaultAuthorizationLevel'

function Probe {
    $body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
    try {
        Invoke-WebRequest -Uri $url -Method Post -Body $body -ContentType 'application/json' -Headers @{ Accept = 'application/json, text/event-stream' } -TimeoutSec 30 | Out-Null
        return 'PUBLIC (no key needed)'
    } catch { return "PROTECTED (HTTP $([int]$_.Exception.Response.StatusCode) without a key)" }
}

switch ($Mode) {
    'public'    { az functionapp config appsettings set -g $rg -n $app --settings "$setting=anonymous" -o none }
    'protected' { az functionapp config appsettings delete -g $rg -n $app --setting-names $setting -o none }
}
if ($Mode -ne 'status') {
    az functionapp restart -g $rg -n $app -o none   # deleting a setting doesn't restart the host on its own
    Write-Host "concierge -> $Mode; waiting for the restart..."
    $want = if ($Mode -eq 'public') { 'PUBLIC*' } else { 'PROTECTED*' }
    for ($i = 0; $i -lt 18 -and -not ((Probe) -like $want); $i++) { Start-Sleep 10 }
}
Write-Host "concierge: $(Probe)"
Write-Host "URL: $url"
