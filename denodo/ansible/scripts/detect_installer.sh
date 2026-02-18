#!/usr/bin/env bash
set -euo pipefail

ZIP_PATH="${1:-denodo/installable/denodo-express-install-9-linux64.zip}"
if [[ ! -f "$ZIP_PATH" ]]; then
  echo "zip-not-found: $ZIP_PATH" >&2
  exit 1
fi

SCRIPT_PATH=""
while IFS= read -r line; do
  if [[ "$line" == */installer_cli.sh ]]; then
    SCRIPT_PATH="$line"
    break
  fi
done < <(unzip -Z1 "$ZIP_PATH")
if [[ -z "$SCRIPT_PATH" ]]; then
  while IFS= read -r line; do
    if [[ "$line" == */install.sh ]]; then
      SCRIPT_PATH="$line"
      break
    fi
  done < <(unzip -Z1 "$ZIP_PATH")
fi
if [[ -z "$SCRIPT_PATH" ]]; then
  echo "installer-script-not-found"
  exit 2
fi

INSTALL_ROOT="$(dirname "$SCRIPT_PATH")"
printf 'denodo_installer_script: "%s"\n' "$SCRIPT_PATH"
printf 'denodo_install_root: "%s"\n' "$INSTALL_ROOT"
printf 'denodo_run_installer_during_build: false\n'
printf 'denodo_installer_flags: ""\n'
if [[ "$SCRIPT_PATH" == */installer_cli.sh ]]; then
  echo '# Denodo CLI installer detected. Recommended unattended mode:'
  echo '# denodo_installer_flags: "install --autoinstaller /tmp/denodo-installer/response_file_9_0.xml"'
else
  echo "# Note: keep run_installer_during_build=false until silent install flags are confirmed."
fi
