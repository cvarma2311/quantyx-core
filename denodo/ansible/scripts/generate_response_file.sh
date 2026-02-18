#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${ANSIBLE_DIR}/.." && pwd)"

ZIP_PATH="${1:-${REPO_DIR}/installable/denodo-express-install-9-linux64.zip}"
OUT_FILE="${2:-${REPO_DIR}/installable/response_file_9_0.xml}"
DOCKER_PLATFORM="${3:-linux/amd64}"

if [[ ! -f "$ZIP_PATH" ]]; then
  echo "zip-not-found: $ZIP_PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT_FILE")"
WORK_DIR="$(mktemp -d /tmp/denodo-response-gen.XXXXXX)"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

cp "$ZIP_PATH" "$WORK_DIR/denodo-express-install-9-linux64.zip"

echo "Launching disposable interactive container to generate response file..."
echo "Output target: $OUT_FILE"

DOCKER_TTY_ARGS=()
if [[ -t 0 && -t 1 ]]; then
  DOCKER_TTY_ARGS=(-it)
fi

docker run --rm "${DOCKER_TTY_ARGS[@]}" \
  --platform "$DOCKER_PLATFORM" \
  -v "$WORK_DIR:/work" \
  ubuntu:22.04 \
  bash -lc '
    set -e
    apt-get update >/dev/null
    apt-get install -y --no-install-recommends unzip ca-certificates >/dev/null
    cd /work
    unzip -q denodo-express-install-9-linux64.zip
    cd denodo-install-9
    chmod +x installer_cli.sh
    echo "Running installer_cli.sh generate /work/response_file_9_0.xml"
    ./installer_cli.sh generate /work/response_file_9_0.xml
    ls -l /work/response_file_9_0.xml
  '

if [[ ! -f "$WORK_DIR/response_file_9_0.xml" ]]; then
  echo "response-file-not-generated" >&2
  exit 2
fi

cp "$WORK_DIR/response_file_9_0.xml" "$OUT_FILE"
echo "Response file saved: $OUT_FILE"
