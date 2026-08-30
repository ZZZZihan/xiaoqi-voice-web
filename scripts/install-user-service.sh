#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${VOICE_WEB_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$SERVICE_DIR/hermes-voice-web.service"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_AGENT="${HERMES_AGENT:-$HERMES_HOME/hermes-agent}"
PORT="${VOICE_WEB_PORT:-8787}"

mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_FILE" <<SERVICE
[Unit]
Description=Hermes Voice Web
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=HERMES_HOME=$HERMES_HOME
Environment=HERMES_AGENT=$HERMES_AGENT
Environment=VOICE_WEB_PORT=$PORT
ExecStart=$APP_DIR/scripts/run-voice-web.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SERVICE

systemctl --user daemon-reload
systemctl --user enable --now hermes-voice-web.service
systemctl --user status --no-pager hermes-voice-web.service
