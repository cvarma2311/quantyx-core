#!/usr/bin/env bash
set -euo pipefail

ZIP_PATH="${1:?usage: discover_installer.sh <zip_path> [out_dir]}"
OUT_DIR="${2:-$(pwd)/../runtime/discovery}"

if [[ ! -f "$ZIP_PATH" ]]; then
  echo "zip-not-found: $ZIP_PATH" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
LISTING_FILE="$OUT_DIR/zip_listing.txt"
INSTALL_SH_FILE="$OUT_DIR/install.sh"
DAT_STRINGS_FILE="$OUT_DIR/dat_strings_filtered.txt"
START_SCRIPTS_FILE="$OUT_DIR/start_script_candidates.txt"
REPORT_FILE="$OUT_DIR/INSTALLER_DISCOVERY_REPORT.md"

unzip -Z1 "$ZIP_PATH" > "$LISTING_FILE"

INSTALL_SH_PATH="$(awk '/\/install\.sh$/ {print; exit}' "$LISTING_FILE")"
if [[ -n "$INSTALL_SH_PATH" ]]; then
  unzip -p "$ZIP_PATH" "$INSTALL_SH_PATH" > "$INSTALL_SH_FILE"
else
  : > "$INSTALL_SH_FILE"
fi

awk '/(start|launcher|server|vdp|scheduler|web|platform|tools).*(\.sh|\.bat)$/ {print}' "$LISTING_FILE" > "$START_SCRIPTS_FILE" || true

DAT_PATH="$(awk '/\/denodo-install-[^\/]+\.dat$/ {print; exit}' "$LISTING_FILE")"
if [[ -z "$DAT_PATH" ]]; then
  DAT_PATH="$(awk '/\.dat$/ {print; exit}' "$LISTING_FILE")"
fi
if [[ -n "$DAT_PATH" ]]; then
  unzip -p "$ZIP_PATH" "$DAT_PATH" | strings | \
    awk 'length($0) < 180' | \
    grep -Ei '(silent|console|response|option|install|unattend|properties|license|accept|target|directory|mode|headless|java)' | \
    LC_ALL=C sort -u > "$DAT_STRINGS_FILE" || true
else
  : > "$DAT_STRINGS_FILE"
fi

cat > "$REPORT_FILE" <<REP
# Installer Discovery Report

## Inputs
- Zip: \
\`$ZIP_PATH\`

## Detected core files
- install script: \
\`${INSTALL_SH_PATH:-NOT FOUND}\`
- dat payload: \
\`${DAT_PATH:-NOT FOUND}\`

## install.sh summary
Saved to: \
\`$INSTALL_SH_FILE\`

## Candidate startup/entry scripts inside zip
Saved to: \
\`$START_SCRIPTS_FILE\`

## Filtered strings from .dat payload
Saved to: \
\`$DAT_STRINGS_FILE\`

## Recommended next steps
1. Review \
\`$INSTALL_SH_FILE\` for invocation of the .dat installer.
2. Review \
\`$DAT_STRINGS_FILE\` for hints of silent/console/response-file options.
3. Prefer CLI installer if present:
   - \`installer_cli.sh generate response_file_9_0.xml\`
   - \`installer_cli.sh install --autoinstaller response_file_9_0.xml\`
4. If still unclear, run a disposable interactive installer container once and capture a response file.
5. Set these vars once confirmed:
   - \
\`denodo_run_installer_during_build: true\`
   - \
\`denodo_installer_script\`
   - \
\`denodo_install_root\`
   - \
\`denodo_installer_flags\`
   - \
\`denodo_env.DENODO_START_CMD\`
REP

echo "Discovery report written to: $REPORT_FILE"
