#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
  echo "Missing .env in repo root" >&2
  exit 1
fi

# Load DB credentials from .env
set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${DB_HOST:-}" || -z "${DB_USER:-}" || -z "${DB_NAME:-}" || -z "${DB_PORT:-}" ]]; then
  echo "DB_HOST, DB_USER, DB_NAME, and DB_PORT must be set in .env" >&2
  exit 1
fi

echo "This will DROP ALL tables named quantyx_* in database: ${DB_NAME} on ${DB_HOST}:${DB_PORT}"
echo "Type YES to continue:"
read -r confirm
if [[ "${confirm}" != "YES" ]]; then
  echo "Aborted."
  exit 1
fi

export PGPASSWORD="${DB_PASSWORD:-}"

psql \
  -h "$DB_HOST" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  -p "$DB_PORT" \
  -v ON_ERROR_STOP=1 \
  -c "
DO \$\$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public' AND tablename LIKE 'quantyx_%'
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE;', r.tablename);
  END LOOP;
END
\$\$;
"

psql \
  -h "$DB_HOST" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  -p "$DB_PORT" \
  -f artifacts/quantyx_tables.sql

psql \
  -h "$DB_HOST" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  -p "$DB_PORT" \
  -f artifacts/quantyx_tables_updates.sql

echo "Done. quantyx_* tables dropped and recreated."
