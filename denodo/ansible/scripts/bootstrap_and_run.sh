#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${ROOT_DIR}/.venv"
PLAYBOOK="site.yml"
EXTRA_ARGS=()

if [[ $# -ge 1 ]]; then
  case "$1" in
    site)
      PLAYBOOK="site.yml"
      shift
      ;;
    build)
      PLAYBOOK="build_image.yml"
      shift
      ;;
    run)
      PLAYBOOK="run_container.yml"
      shift
      ;;
    verify|rebuild|restart|destroy|discovery)
      PLAYBOOK="$1.yml"
      shift
      ;;
    generate-response)
      shift
      if [[ $# -gt 0 ]]; then
        "${ROOT_DIR}/scripts/generate_response_file.sh" "$@"
      else
        "${ROOT_DIR}/scripts/generate_response_file.sh" "${ROOT_DIR}/../installable/denodo-express-install-9-linux64.zip" "${ROOT_DIR}/../installable/response_file_9_0.xml"
      fi
      exit 0
      ;;
  esac
fi

EXTRA_ARGS=("$@")

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker CLI is required" >&2
  exit 1
fi

DOCKER_HOST_FROM_CONTEXT="$(docker context inspect --format '{{(index .Endpoints \"docker\").Host}}' 2>/dev/null | head -n 1 || true)"
if [[ -n "${DOCKER_HOST_FROM_CONTEXT}" ]]; then
  export DOCKER_HOST="${DOCKER_HOST_FROM_CONTEXT}"
fi

if ! docker version >/dev/null 2>&1; then
  echo "Docker daemon is not reachable. Start Docker Desktop (or your Docker engine) and rerun." >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtualenv at ${VENV_DIR}..."
  python3 -m venv "$VENV_DIR"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip >/dev/null
"${VENV_DIR}/bin/python" -m pip install ansible requests docker >/dev/null

echo "Installing required Ansible collections..."
"${VENV_DIR}/bin/ansible-galaxy" collection install -r requirements.yml

echo "Running playbook: playbooks/${PLAYBOOK}"
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  "${VENV_DIR}/bin/ansible-playbook" "playbooks/${PLAYBOOK}" "${EXTRA_ARGS[@]}"
else
  "${VENV_DIR}/bin/ansible-playbook" "playbooks/${PLAYBOOK}"
fi
