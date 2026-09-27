#!/bin/sh
# Twin of up.ps1. All inputs come from settings.env (copy settings.env.sample).   ./scripts/up.sh [file]
set -e
cd "$(dirname "$0")/.."
./scripts/apply-settings.sh "${1:-settings.env}"
eval "$(azd env get-values | grep -E '^[A-Z0-9_]+=')"
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az group create -n "$AZURE_RESOURCE_GROUP" -l "$AZURE_LOCATION" -o none
azd up --no-prompt
python scripts/smoke.py
