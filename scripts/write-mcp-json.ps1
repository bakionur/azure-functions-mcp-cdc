# Writes .vscode/mcp.json (gitignored — it holds keys) with the local servers and the four remote ones.
#   concierge-remote   self-hosted SDK server  → host key 'default'
#   adopilot-remote    Entra-protected         → NO header: VS Code gets 401 → signs you in (Demo 3)
#   skywatch/domainforge-remote                → per-app 'mcp_extension' system key
$ErrorActionPreference = 'Stop'
$root = Resolve-Path "$PSScriptRoot/.."
$py = if (Test-Path "$root/.venv/Scripts/python.exe") { '${workspaceFolder}/.venv/Scripts/python.exe' } elseif (Test-Path "$root/.venv/bin/python") { '${workspaceFolder}/.venv/bin/python' } else { 'python' }
$cfg = [ordered]@{ servers = [ordered]@{
  'cdc-concierge-local' = [ordered]@{ type='stdio'; command=$py; args=@('${workspaceFolder}/local/server.py') }
  'skywatch-localhost'  = [ordered]@{ type='http'; url='http://localhost:7071/runtime/webhooks/mcp' }
}}
$vals = azd env get-values 2>$null | Where-Object { $_ -match '^[A-Z0-9_]+=' }
$e = if ($vals) { $vals | ConvertFrom-StringData } else { @{} }
if ($e.MCP_SKYWATCH_URL) {
  $rg = $e.RESOURCE_GROUP.Trim('"')
  function Key($app, $query) { az functionapp keys list -g $rg -n $app --query $query -o tsv }
  $cfg.servers['concierge-remote'] = [ordered]@{ type='http'; url=$e.MCP_CONCIERGE_URL.Trim('"'); headers=@{ 'x-functions-key' = (Key $e.APP_CONCIERGE.Trim('"') 'functionKeys.default') } }
  $ado = [ordered]@{ type='http'; url=$e.MCP_ADO_URL.Trim('"') }
  if ($e.ADO_AUTH_MODE -and $e.ADO_AUTH_MODE.Trim('"') -eq 'key') { $ado.headers = @{ 'x-functions-key' = (Key $e.APP_ADO.Trim('"') 'systemKeys.mcp_extension') } }
  $cfg.servers['adopilot-remote'] = $ado
  foreach ($s in 'skywatch','domainforge') {
    $cfg.servers["$s-remote"] = [ordered]@{ type='http'; url=$e."MCP_$($s.ToUpper())_URL".Trim('"'); headers=@{ 'x-functions-key' = (Key $e."APP_$($s.ToUpper())".Trim('"') 'systemKeys.mcp_extension') } }
  }
}
New-Item -ItemType Directory -Force "$root/.vscode" | Out-Null
$cfg | ConvertTo-Json -Depth 6 | Set-Content "$root/.vscode/mcp.json"
Write-Host "wrote .vscode/mcp.json with $($cfg.servers.Count) servers (gitignored)"
