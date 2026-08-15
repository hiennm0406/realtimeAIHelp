# Claude Code bridge

Runs on the machine where Claude Code is installed. The deployed website talks to
this process, this process runs `claude`, and every line Claude Code emits is
relayed straight back to the browser.

```
phone / laptop ──▶ Netlify (static Vue site)
                        │
                        │  HTTPS + Bearer token
                        ▼
                   tunnel URL  ──▶  bridge/server.py  ──▶  claude.exe
                                    (this machine)         (your files, your tools)
```

Python 3.8+ only. No `pip install` needed.

## 1. Start it

```
python bridge/server.py
```

or double-click `bridge/start.bat`.

On first run it writes `bridge/config.json` and prints an access token:

```
  listening on   http://127.0.0.1:8787
  claude binary  C:\Users\you\.local\bin\claude.EXE
  working dir    D:\Project\xamxi
  permissions    bypassPermissions

  access token   <a long random string - yours will differ>
```

Copy that token — the web UI asks for it.

`config.json` is listed in `.gitignore`, so the token is never committed.

## 2. Make it reachable

The bridge listens on `127.0.0.1`, so by default only this machine can reach it.
Pick one:

**Cloudflare Tunnel** (works from anywhere, no port forwarding, no account for a
quick tunnel):

```
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8787
```

It prints a `https://something.trycloudflare.com` URL. That is your bridge URL.
A quick tunnel gets a new URL every restart; a named tunnel keeps a fixed one.

**ngrok**: `ngrok http 8787`, then use the printed https URL.

**Same Wi-Fi only**: set `"host": "0.0.0.0"` in `config.json`, allow port 8787
through Windows Firewall, and use `http://<your-pc-ip>:8787`. Note that browsers
block plain HTTP requests from an HTTPS page, so this only works if you also open
the site over HTTP (e.g. the local dev server), not from the Netlify URL.

## 3. Point the site at it

Open the site → **Settings** → paste the bridge URL and token → **Test connection**.
Settings are stored in the browser, so each device is configured once.

## Security

`default_permission_mode` is `bypassPermissions` and `dangerously_skip_permissions`
is on. That is what makes the web chat behave like the terminal, and it means:

> **Anyone holding the token can run any command on this machine.**

So:

- Never commit or share `config.json`.
- Stop the tunnel when you are not using it — a quick-tunnel URL is public, and
  the token is the only thing standing between the internet and a shell.
- Rotate the token by deleting `"token"` from `config.json` and restarting.
- If you want a safer default, set `"default_permission_mode": "acceptEdits"`
  (Claude can still read and edit files, but shell commands need approval — and
  in headless mode an unapproved command is simply refused) or `"plan"` for
  read-only.

## Config reference

`bridge/config.json`:

| Key | Default | Meaning |
| --- | --- | --- |
| `host` | `127.0.0.1` | Interface to bind. `0.0.0.0` exposes it to your LAN. |
| `port` | `8787` | Listening port. |
| `token` | generated | Shared secret. Sent as `Authorization: Bearer …`. |
| `claude_path` | `claude` | Path to the executable if it isn't on `PATH`. |
| `default_cwd` | project root | The folder Claude works in. |
| `allowed_cwds` | `[]` | Extra folders the UI may switch to. |
| `default_model` | `""` | `""` uses whatever Claude Code is configured with. |
| `default_permission_mode` | `bypassPermissions` | See above. |
| `dangerously_skip_permissions` | `true` | Adds `--dangerously-skip-permissions`. |
| `allowed_tools` | `[]` | `[]` means every tool, including WebSearch and WebFetch. |
| `allowed_origins` | `["*"]` | CORS. Narrow this to your site's URL once deployed. |
| `max_concurrent` | `2` | Simultaneous Claude runs. |
| `run_timeout_seconds` | `1800` | Hard stop for one run. |

## HTTP API

All routes need `Authorization: Bearer <token>`.

- `GET /api/health` → bridge status, resolved Claude path, working dir.
- `POST /api/chat` → `text/event-stream`. Body:
  `{ prompt, sessionId?, model?, effort?, permissionMode? }`.
  SSE events: `bridge` (run started, carries `runId`), `claude` (one raw
  `stream-json` object), `notice`, `error`, `done`.
- `POST /api/abort` → `{ runId }`, kills that run and its child processes.

Conversation continuity works by echoing the `session_id` from Claude Code's
`system/init` event back as `sessionId`; the bridge turns that into `--resume`.
