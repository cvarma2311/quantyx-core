#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

LOG_FILE="${REPO_ROOT}/app.log"
PREV_LOG_FILE="${REPO_ROOT}/app.prev.log"
PID_FILE="${REPO_ROOT}/.api_8787.pid"
PORT="${PORT:-8787}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -x "${REPO_ROOT}/.venv/bin/uvicorn" ]]; then
  UVICORN_BIN="${REPO_ROOT}/.venv/bin/uvicorn"
else
  UVICORN_BIN="uvicorn"
fi

echo "==> Stopping any process on port ${PORT}"
EXISTING_PIDS="$(lsof -ti "tcp:${PORT}" || true)"
if [[ -n "${EXISTING_PIDS}" ]]; then
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    kill "${pid}" || true
  done <<< "${EXISTING_PIDS}"
  sleep 2
  REMAINING_PIDS="$(lsof -ti "tcp:${PORT}" || true)"
  if [[ -n "${REMAINING_PIDS}" ]]; then
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill -9 "${pid}" || true
    done <<< "${REMAINING_PIDS}"
  fi
fi

{
  if [[ -f "${LOG_FILE}" ]]; then
    cp "${LOG_FILE}" "${PREV_LOG_FILE}" || true
  fi
  : > "${LOG_FILE}"
  echo
  echo "=================================================================="
  echo "START $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "PORT=${PORT}"
  echo "CMD=${UVICORN_BIN} services.api.main:app --reload --port ${PORT}"
  echo "=================================================================="
} >> "${LOG_FILE}"

echo "==> Starting API on port ${PORT}"
nohup "${UVICORN_BIN}" services.api.main:app --reload --port "${PORT}" >> "${LOG_FILE}" 2>&1 &
API_PID=$!
echo "${API_PID}" > "${PID_FILE}"

sleep 2

echo "==> API started"
echo "PID: ${API_PID}"
echo "Log: ${LOG_FILE}"
echo "PID file: ${PID_FILE}"
echo
echo "Useful commands:"
echo "  tail -f ${LOG_FILE}"
echo "  curl -s http://localhost:${PORT}/health || true"
