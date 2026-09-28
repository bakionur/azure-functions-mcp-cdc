#!/bin/sh
# Twin of concierge-access.ps1.   ./scripts/concierge-access.sh public|protected|status
# Switches the concierge between public and key-protected via an app setting (no redeploy, ~30 s restart).
# `azd provision` rewrites app settings from Bicep, so it also resets the app to protected.
set -e
cd "$(dirname "$0")/.."
MODE="$1"
case "$MODE" in public|protected|status) ;; *) echo "usage: $0 public|protected|status"; exit 1;; esac
eval "$(azd env get-values | grep -E '^(RESOURCE_GROUP|APP_CONCIERGE|MCP_CONCIERGE_URL)=')"
SETTING=AzureFunctionsJobHost__customHandler__http__defaultAuthorizationLevel

probe() {
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST "$MCP_CONCIERGE_URL" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}')
  if [ "$code" = 200 ]; then echo "PUBLIC (no key needed)"; else echo "PROTECTED (HTTP $code without a key)"; fi
}

case "$MODE" in
  public)    az functionapp config appsettings set -g "$RESOURCE_GROUP" -n "$APP_CONCIERGE" --settings "$SETTING=anonymous" -o none ;;
  protected) az functionapp config appsettings delete -g "$RESOURCE_GROUP" -n "$APP_CONCIERGE" --setting-names "$SETTING" -o none ;;
esac
if [ "$MODE" != status ]; then
  az functionapp restart -g "$RESOURCE_GROUP" -n "$APP_CONCIERGE" -o none  # deleting a setting doesn't restart the host on its own
  echo "concierge -> $MODE; waiting for the restart..."
  want=PUBLIC; [ "$MODE" = protected ] && want=PROTECTED
  i=0; while [ $i -lt 18 ] && ! probe | grep -q "^$want"; do sleep 10; i=$((i+1)); done
fi
echo "concierge: $(probe)"
echo "URL: $MCP_CONCIERGE_URL"
