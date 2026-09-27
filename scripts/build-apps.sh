#!/bin/sh
# Builds the two MCP App widgets into single-file index.html (runs as azd preprovision hook).
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
for s in skywatch domainforge; do
  cd "$root/servers/$s/app"
  [ -d node_modules ] || npm ci --no-audit --no-fund >/dev/null
  npm run build >/dev/null
  echo "built $s widget -> servers/$s/app/dist/index.html"
done
