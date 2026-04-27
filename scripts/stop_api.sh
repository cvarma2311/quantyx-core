#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

PID_FILE="${REPO_ROOT}/.api_8787.pid"
PORT="${PORT:-8787}"

echo "==> Stopping API on port ${PORT}"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}" || true
    sleep 2
    if kill -0 "${PID}" 2>/dev/null; then
      kill -9 "${PID}" || true
    fi
  fi
  rm -f "${PID_FILE}"
fi

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

echo "==> API stopped"
