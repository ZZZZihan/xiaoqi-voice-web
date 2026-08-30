#!/usr/bin/env bash
set -euo pipefail

HOST="${VOICE_WEB_HOST:-0.0.0.0}"
PORT="${VOICE_WEB_PORT:-8787}"
APP_DIR="${VOICE_WEB_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_AGENT="${HERMES_AGENT:-$HERMES_HOME/hermes-agent}"
PYTHON="${VOICE_WEB_PYTHON:-$HERMES_AGENT/venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${VOICE_WEB_PYTHON:-python3}"
fi

export HERMES_HOME
export HERMES_AGENT
export PATH="$HERMES_AGENT/venv/bin:$PATH"

cd "$APP_DIR"

args=(
  -m uvicorn
  server:app
  --host "$HOST"
  --port "$PORT"
)

if [[ -n "${VOICE_WEB_SSL_KEYFILE:-}" && -n "${VOICE_WEB_SSL_CERTFILE:-}" ]]; then
  args+=(--ssl-keyfile "$VOICE_WEB_SSL_KEYFILE" --ssl-certfile "$VOICE_WEB_SSL_CERTFILE")
elif [[ -f "$APP_DIR/certs/key.pem" && -f "$APP_DIR/certs/cert.pem" ]]; then
  args+=(--ssl-keyfile "$APP_DIR/certs/key.pem" --ssl-certfile "$APP_DIR/certs/cert.pem")
fi

exec "$PYTHON" "${args[@]}"
