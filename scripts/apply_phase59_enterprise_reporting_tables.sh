#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if [[ ! -f .env ]]; then
  echo "Missing .env in repo root" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${DB_HOST:-}" || -z "${DB_USER:-}" || -z "${DB_NAME:-}" || -z "${DB_PORT:-}" ]]; then
  echo "DB_HOST, DB_USER, DB_NAME, and DB_PORT must be set in .env" >&2
  exit 1
fi

export PGPASSWORD="${DB_PASSWORD:-}"

psql \
  -v ON_ERROR_STOP=1 \
  -h "${DB_HOST}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  -p "${DB_PORT}" \
  -f artifacts/phase59_enterprise_reporting_trends.sql

echo "Applied Phase 59 enterprise reporting tables to ${DB_NAME} on ${DB_HOST}:${DB_PORT}"
