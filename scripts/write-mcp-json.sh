#!/bin/sh
# Writes .vscode/mcp.json (gitignored — it holds keys). Twin of write-mcp-json.ps1.
set -e
cd "$(dirname "$0")/.."
py=python; [ -x .venv/bin/python ] && py='${workspaceFolder}/.venv/bin/python'
mkdir -p .vscode
vals="$(azd env get-values 2>/dev/null | grep -E '^[A-Z0-9_]+=' || true)"
eval "$vals"
if [ -n "${MCP_SKYWATCH_URL:-}" ]; then
  key() { az functionapp keys list -g "$RESOURCE_GROUP" -n "$1" --query "$2" -o tsv; }
  ado_headers=""
  [ "$ADO_AUTH_MODE" = "key" ] && ado_headers=", \"headers\": { \"x-functions-key\": \"$(key "$APP_ADO" systemKeys.mcp_extension)\" }"
  remote=",
    \"cdc-concierge-remote\":   { \"type\": \"http\", \"url\": \"$MCP_CONCIERGE_URL\", \"headers\": { \"x-functions-key\": \"$(key "$APP_CONCIERGE" functionKeys.default)\" } },
    \"cdc-adopilot-remote\":    { \"type\": \"http\", \"url\": \"$MCP_ADO_URL\"$ado_headers },
    \"cdc-skywatch-remote\":    { \"type\": \"http\", \"url\": \"$MCP_SKYWATCH_URL\", \"headers\": { \"x-functions-key\": \"$(key "$APP_SKYWATCH" systemKeys.mcp_extension)\" } },
    \"cdc-domainforge-remote\": { \"type\": \"http\", \"url\": \"$MCP_DOMAINFORGE_URL\", \"headers\": { \"x-functions-key\": \"$(key "$APP_DOMAINFORGE" systemKeys.mcp_extension)\" } }"
fi
cat > .vscode/mcp.json << JSON
{
  "servers": {
    "cdc-concierge-local": { "type": "stdio", "command": "$py", "args": ["\${workspaceFolder}/local/server.py"] },
    "cdc-skywatch-localhost":  { "type": "http", "url": "http://localhost:7071/runtime/webhooks/mcp" }${remote:-}
  }
}
JSON
echo "wrote .vscode/mcp.json (gitignored)"
