#!/usr/bin/env bash
#
# One-shot setup for the Claude Code bridge on a fresh Ubuntu VM (Oracle ARM or
# any x86/arm64 box). Installs Node + Claude Code + Python, clones the app,
# writes config, and runs the bridge as a systemd service that starts on boot.
#
# Run it on the VM (NOT on your PC):
#   curl -fsSL https://raw.githubusercontent.com/hiennm0406/realtimeAIHelp/main/deploy/setup.sh -o setup.sh
#   ANTHROPIC_API_KEY=sk-ant-xxx  SITE_ORIGIN=https://your-site.netlify.app  bash setup.sh
#
# Both env vars are optional - it will prompt for the API key if missing, and
# default CORS to "*" if SITE_ORIGIN is unset (tighten it later in config.json).
set -euo pipefail

REPO_URL="https://github.com/hiennm0406/realtimeAIHelp.git"
APP_DIR="$HOME/realtimeAIHelp"
SVC_USER="$(id -un)"
PYTHON="$(command -v python3 || echo /usr/bin/python3)"

echo "==> Installing Node, Python, git ..."
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
fi
sudo apt-get install -y nodejs git python3

echo "==> Installing Claude Code CLI ..."
sudo npm install -g @anthropic-ai/claude-code
CLAUDE_BIN="$(command -v claude || echo claude)"
echo "    claude at: $CLAUDE_BIN"

echo "==> Fetching the app ..."
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only || true
else
  git clone "$REPO_URL" "$APP_DIR"
fi
mkdir -p "$HOME/workspace"

echo "==> Writing bridge/config.json (if missing) ..."
CFG="$APP_DIR/bridge/config.json"
if [ ! -f "$CFG" ]; then
  cat >"$CFG" <<JSON
{
  "default_cwd": "$HOME/workspace",
  "allowed_origins": ["${SITE_ORIGIN:-*}"],
  "claude_path": "$CLAUDE_BIN"
}
JSON
fi

echo "==> Secrets file /etc/claude-bridge.env ..."
if [ ! -f /etc/claude-bridge.env ]; then
  if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    read -rp "Paste your ANTHROPIC_API_KEY (blank to fill in later): " ANTHROPIC_API_KEY || true
  fi
  echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}" | sudo tee /etc/claude-bridge.env >/dev/null
  sudo chmod 600 /etc/claude-bridge.env
fi

echo "==> Installing systemd service ..."
sudo tee /etc/systemd/system/claude-bridge.service >/dev/null <<UNIT
[Unit]
Description=Claude Code bridge (realtimeAIHelp)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/claude-bridge.env
# Python block-buffers stdout when it is a pipe, so without this journalctl
# shows nothing for a long time - including the startup banner and the token.
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON bridge/server.py
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now claude-bridge
sleep 2

echo
echo "==> Bridge status:"
systemctl --no-pager --lines=0 status claude-bridge || true
echo
echo "==> Access token (paste into the site's Settings):"
grep -o '"token"[^,]*' "$CFG" || echo "   (not generated yet - check: journalctl -u claude-bridge -n 30)"
echo
echo "Next:"
echo "  1) Verify auth works:   ANTHROPIC_API_KEY=\$(sudo cat /etc/claude-bridge.env | cut -d= -f2) claude -p 'say hi'"
echo "  2) Give it a public HTTPS URL with Tailscale Funnel:"
echo "       curl -fsSL https://tailscale.com/install.sh | sh"
echo "       sudo tailscale up"
echo "       sudo tailscale funnel 8787"
echo "       tailscale funnel status      # <- your URL"
echo "  3) On the site -> Settings: paste that URL + the token above."
