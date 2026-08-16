# Running the bridge 24/7 on a VPS

Goal: the agent keeps running even when your own PC is off. Nothing here changes
the app — you just move `bridge/server.py` from your PC to an always-on Linux
box, run it as a service, and give it a stable HTTPS URL.

Tested against Ubuntu 22.04/24.04 (x86 or ARM). Commands assume a user named
`claude`; adjust paths if you use another.

---

## 0. Get a VM

Any small Linux VM works: Oracle Cloud (has an always-free ARM tier), Hetzner,
AWS Lightsail, DigitalOcean, etc. 1 vCPU / 1 GB RAM is enough for the bridge
itself. Pick Ubuntu. SSH in, then:

```bash
sudo adduser --disabled-password claude
sudo usermod -aG sudo claude       # optional; only if you want the agent to sudo
sudo su - claude
```

## 1. Node + Claude Code

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs git python3
sudo npm install -g @anthropic-ai/claude-code
claude --version          # confirms it's installed
which claude              # note this path if it's NOT /usr/bin/claude
```

## 2. Auth (headless)

The reliable headless option is an API key (bills through the Anthropic API,
pay-per-token — separate from a Pro/Max subscription):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
echo '{"type":"user","message":{...}}' >/dev/null   # (nothing to run yet)
```

You'll put this key in `/etc/claude-bridge.env` in step 4 so the service has it.

## 3. Get the code + configure

```bash
cd ~
git clone https://github.com/hiennm0406/realtimeAIHelp.git
cd realtimeAIHelp
mkdir -p ~/workspace                      # the folder the agent works in
```

Create `bridge/config.json` (the bridge also auto-creates one on first run and
prints a token):

```json
{
  "default_cwd": "/home/claude/workspace",
  "allowed_origins": ["https://YOUR-SITE.netlify.app"],
  "default_permission_mode": "bypassPermissions",
  "dangerously_skip_permissions": true,
  "claude_path": "claude"
}
```

- Set `allowed_origins` to your deployed site's exact URL (drop the `["*"]`
  default once it works — it's what stops other pages from using your bridge).
- If `which claude` in step 1 wasn't on the service PATH, set `claude_path` to
  that absolute path.
- Start it once by hand to read the generated token:
  `python3 bridge/server.py` → copy the `access token`, then Ctrl+C.

## 4. Run the bridge as a service

```bash
# secrets
sudo install -m 600 -o claude -g claude \
  deploy/claude-bridge.env.example /etc/claude-bridge.env
sudo nano /etc/claude-bridge.env          # paste your ANTHROPIC_API_KEY

# service
sudo cp deploy/claude-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-bridge
systemctl status claude-bridge            # should be active (running)
journalctl -u claude-bridge -f            # live logs
```

It now starts on boot and restarts if it crashes. The bridge binds to
`127.0.0.1:8787` only — it is not reachable from the internet yet. That's step 5.

## 5. A stable HTTPS URL

Your site is served over HTTPS, so the browser can only call the bridge over
HTTPS with a valid certificate. Two good ways:

### Option A — Cloudflare named tunnel (needs a domain on Cloudflare)

```bash
# install cloudflared (x86 shown; for ARM use the arm64 .deb)
curl -L -o cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

cloudflared tunnel login
cloudflared tunnel create claude-bridge
cloudflared tunnel route dns claude-bridge claude.example.com
```

Put `deploy/cloudflared-config.example.yml` at `~/.cloudflared/config.yml`, fill
in the tunnel ID + hostname, then:

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

Your stable URL is `https://claude.example.com`.

### Option B — Tailscale Funnel (no domain needed)

Gives a stable `https://<host>.<tailnet>.ts.net` URL with valid TLS, free:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale funnel 8787                # exposes the bridge over HTTPS
tailscale funnel status                   # shows your public URL
```

## 6. Point the app at it

On the site → **Settings**, set the Bridge URL to your new stable URL and paste
the token from step 3. (Or bake it in at build time with `VITE_BRIDGE_URL` and
redeploy — see the top-level README.)

## 7. Security checklist

`bypassPermissions` means **anyone with the token can run any command on this
VM**. So:

- Keep the token secret; rotate it (edit `bridge/config.json`, restart) if it leaks.
- Narrow `allowed_origins` to your site only.
- Run as the non-root `claude` user (above), and only add it to `sudo` if you
  actually need the agent to install packages etc.
- Never expose port 8787 directly — keep it on `127.0.0.1` and reach it only via
  the tunnel/funnel.
- Transcripts under `bridge/runs/` can hold command output and secrets; they're
  git-ignored and pruned after `run_retention_seconds`.

## Updating later

```bash
cd ~/realtimeAIHelp && git pull
sudo systemctl restart claude-bridge
```

Finished runs are reloaded from `bridge/runs/` on restart, so past results
survive the update.
