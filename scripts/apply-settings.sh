#!/bin/sh
# Twin of apply-settings.ps1.   ./scripts/apply-settings.sh [--provision] [file]
set -e
cd "$(dirname "$0")/.."
PROVISION=; [ "$1" = "--provision" ] && { PROVISION=1; shift; }
FILE="${1:-settings.env}"
[ -f "$FILE" ] || { echo "No $FILE — copy settings.env.sample to settings.env and fill it in."; exit 1; }
# shellcheck disable=SC2046
set -a; . "./$FILE"; set +a
[ -n "$AZURE_SUBSCRIPTION_ID" ] || { echo "AZURE_SUBSCRIPTION_ID is required"; exit 1; }
[ -n "$ADO_PROJECT" ] && [ -z "$ADO_TEAM" ] && ADO_TEAM="$ADO_PROJECT Team"
ENV_NAME="${AZURE_ENV_NAME:-cdc}"
AZURE_RESOURCE_GROUP="rg-mcp-$ENV_NAME"
azd env new "$ENV_NAME" --subscription "$AZURE_SUBSCRIPTION_ID" --location "$AZURE_LOCATION" --no-prompt >/dev/null 2>&1 || true
azd env select "$ENV_NAME"
for k in $(grep -E '^[A-Z0-9_]+=' "$FILE" | cut -d= -f1) AZURE_RESOURCE_GROUP ADO_TEAM; do
  case "$k" in AZURE_ENV_NAME|AZURE_TENANT_ID) continue;; esac
  eval "v=\${$k:-}"
  azd env set "$k" "$v" >/dev/null
  case "$k" in *PAT*|*KEY*|*SECRET*) [ -n "$v" ] && v='***';; esac
  printf '  %-24s %s\n' "$k" "$v"
done
echo "azd env '$ENV_NAME' updated from $FILE"
if [ -n "$PROVISION" ]; then azd provision --no-prompt && ./scripts/postdeploy.sh; fi
