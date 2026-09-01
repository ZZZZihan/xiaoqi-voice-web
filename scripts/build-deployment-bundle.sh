#!/usr/bin/env bash
set -euo pipefail

XIAOQI_APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XIAOQI_OUTPUT_ROOT="${1:-$XIAOQI_APP_DIR/dist}"
XIAOQI_BUILD_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
XIAOQI_BUNDLE_NAME="xiaoqi-voice-web-$XIAOQI_BUILD_STAMP"
XIAOQI_BUNDLE_DIR="$XIAOQI_OUTPUT_ROOT/$XIAOQI_BUNDLE_NAME"
XIAOQI_ARCHIVE="$XIAOQI_OUTPUT_ROOT/$XIAOQI_BUNDLE_NAME.tar.gz"

XIAOQI_DEPLOYMENT_FILES=(
  README.md
  app.css
  call-mode.js
  index.html
  requirements.txt
  server.py
  ui-motion.js
  docs/ACCEPTANCE.md
  docs/TRUSTED_HTTPS.md
  docs/trusted-https/xiaoqi-local-ca.cer
  docs/trusted-https/xiaoqi-local-ca.pem
  scripts/install-user-service.sh
  scripts/run-voice-web.sh
)

if [[ -e "$XIAOQI_BUNDLE_DIR" || -e "$XIAOQI_ARCHIVE" ]]; then
  echo "Refusing to overwrite an existing bundle: $XIAOQI_BUNDLE_NAME" >&2
  exit 1
fi

XIAOQI_BASE_COMMIT="$(git -C "$XIAOQI_APP_DIR" rev-parse HEAD 2>/dev/null || printf 'unknown')"
if [[ -n "$(git -C "$XIAOQI_APP_DIR" status --porcelain --untracked-files=all 2>/dev/null || true)" ]]; then
  echo "Refusing to build a deployment bundle from an uncommitted worktree." >&2
  exit 1
fi

mkdir -p "$XIAOQI_BUNDLE_DIR"

for XIAOQI_RELATIVE_PATH in "${XIAOQI_DEPLOYMENT_FILES[@]}"; do
  if [[ ! -f "$XIAOQI_APP_DIR/$XIAOQI_RELATIVE_PATH" ]]; then
    echo "Missing deployment file: $XIAOQI_RELATIVE_PATH" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$XIAOQI_BUNDLE_DIR/$XIAOQI_RELATIVE_PATH")"
  cp "$XIAOQI_APP_DIR/$XIAOQI_RELATIVE_PATH" "$XIAOQI_BUNDLE_DIR/$XIAOQI_RELATIVE_PATH"
done

if grep -RIlE 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|XIAOMI_API_KEY[[:space:]]*=[^[:space:]]+' "$XIAOQI_BUNDLE_DIR" >/dev/null; then
  echo "Refusing to package a private key or populated API credential." >&2
  rm -rf "$XIAOQI_BUNDLE_DIR"
  exit 1
fi

{
  printf 'bundle=%s\n' "$XIAOQI_BUNDLE_NAME"
  printf 'created_utc=%s\n' "$XIAOQI_BUILD_STAMP"
  printf 'base_commit=%s\n' "$XIAOQI_BASE_COMMIT"
  printf 'source_state=clean\n'
  printf 'deployment_performed=false\n'
  printf 'verify_files=shasum -a 256 -c SHA256SUMS\n'
  printf 'deploy_order=copy non-HTML runtime files, restart and verify service, then copy index.html last\n'
} > "$XIAOQI_BUNDLE_DIR/BUILD-INFO.txt"

(
  cd "$XIAOQI_BUNDLE_DIR"
  shasum -a 256 "${XIAOQI_DEPLOYMENT_FILES[@]}" > SHA256SUMS
  shasum -a 256 -c SHA256SUMS
)

tar -czf "$XIAOQI_ARCHIVE" -C "$XIAOQI_OUTPUT_ROOT" "$XIAOQI_BUNDLE_NAME"
(
  cd "$XIAOQI_OUTPUT_ROOT"
  shasum -a 256 "$(basename "$XIAOQI_ARCHIVE")" > "$(basename "$XIAOQI_ARCHIVE.sha256")"
)

printf 'Bundle directory: %s\n' "$XIAOQI_BUNDLE_DIR"
printf 'Bundle archive: %s\n' "$XIAOQI_ARCHIVE"
printf 'Archive checksum: %s\n' "$XIAOQI_ARCHIVE.sha256"
