#!/bin/sh
# azd postdeploy hook: local client config + the Foundry agent. Twin of postdeploy.ps1.
cd "$(dirname "$0")/.."
./scripts/write-mcp-json.sh
eval "$(azd env get-values | grep -E '^[A-Z0-9_]+=')"
if [ -n "$FOUNDRY_PROJECT_ENDPOINT" ]; then
  python scripts/foundry_agent.py setup || echo "Foundry agent setup failed — rerun: python scripts/foundry_agent.py setup"
fi
# API Center creates a 'Swagger Petstore' sample API; the catalog should show only our four MCP servers
[ -n "$APIC_NAME" ] && az apic api delete -g "$RESOURCE_GROUP" -n "$APIC_NAME" --api-id swagger-petstore --yes >/dev/null 2>&1
exit 0
