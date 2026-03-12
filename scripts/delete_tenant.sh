#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8787}"
TENANT_ID="${1:-}"
MODE="${2:-purge_and_delete}" # dry_run | purge_only | purge_and_delete

if [[ -z "$TENANT_ID" ]]; then
  echo "Usage: $0 <tenant_id> [dry_run|purge_only|purge_and_delete]"
  exit 1
fi

echo "API_BASE=$API_BASE"
echo "TENANT_ID=$TENANT_ID"
echo "MODE=$MODE"

if [[ "$MODE" == "dry_run" ]]; then
  curl -sS -X POST "$API_BASE/tenant/purge" \
    -H 'Content-Type: application/json' \
    -d "{\"tenant_id\":\"$TENANT_ID\",\"dry_run\":true}" | jq .
  exit 0
fi

echo "Purging tenant data..."
curl -sS -X POST "$API_BASE/tenant/purge" \
  -H 'Content-Type: application/json' \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"confirm\":true,\"dry_run\":false}" | jq .

if [[ "$MODE" == "purge_only" ]]; then
  exit 0
fi

echo "Deleting tenant registry row..."
curl -sS -X DELETE "$API_BASE/tenants/$TENANT_ID?purge=false" | jq .

echo "Done."
