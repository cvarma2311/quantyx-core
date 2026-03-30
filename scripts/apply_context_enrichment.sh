#!/usr/bin/env bash
set -euo pipefail

cd /Users/vnagaraju/PycharmProjects/quantyx-core
set -a
source .env
set +a

export PGHOST="${DB_HOST}"
export PGPORT="${DB_PORT}"
export PGDATABASE="${DB_NAME}"
export PGUSER="${DB_USER}"
export PGPASSWORD="${DB_PASSWORD}"

# Phase 48 — add enriched_context column to quantyx_business_context
psql -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.quantyx_business_context
  ADD COLUMN IF NOT EXISTS enriched_context TEXT NULL;
SQL

echo "Migration applied: enriched_context column added to quantyx_business_context"