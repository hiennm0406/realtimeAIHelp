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

## Troubleshooting

**"Failed to fetch"** means the browser never reached the bridge — it is a
network failure, not an auth or CORS failure (those come back as 401 / a CORS
error). Work down this list:

| Check | How |
| --- | --- |
| Both processes are running | You need **two** windows: `python bridge/server.py` *and* `cloudflared tunnel --url http://127.0.0.1:8787`. The tunnel alone is not enough, and neither is the bridge alone. |
| You used the tunnel URL, not localhost | `http://127.0.0.1:8787` means "this device" — on your phone it points at your phone. Off your network you must use the `https://….trycloudflare.com` URL. |
| The URL is current | A quick tunnel gets a **new URL every time you restart it**. Re-copy it into Settings after each restart. Use a named tunnel if you want a fixed one. |
| HTTPS page → HTTPS bridge | Browsers block an HTTPS site from calling a plain `http://` address (mixed content). The tunnel URL is HTTPS, so this only bites if you typed a LAN IP. |

Verify the bridge is reachable without a browser:

```
curl -H "Authorization: Bearer <token>" https://<your-tunnel>.trycloudflare.com/api/health
```

`{"ok": true, …}` means the bridge and tunnel are fine and the problem is in
the browser (wrong URL, stale token). A hang or connection error means the
tunnel is down. `401` means the token is wrong — the URL is fine.

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
| `run_retention_seconds` | `21600` | How long a finished run stays reconnectable (in memory and on disk). Raise it to step away for longer. |

## Background runs

A run is driven by a background worker that is independent of the browser
connection. Its events are buffered in memory **and streamed to disk** at
`bridge/runs/<runId>.jsonl`, so closing the tab, losing signal, walking away —
or even restarting the bridge — does **not** stop or lose the agent's work. When
you come back the UI reconnects with `GET /api/stream?runId=…`, replays
everything it missed, and tails the run to the end.

- **Close the browser / lose signal:** the worker keeps going; reconnect replays
  the live progress and the final answer.
- **Restart the bridge:** on startup it reloads every saved run from
  `bridge/runs/`, so a returning browser still gets the result. A run that was
  mid-flight when the bridge stopped is marked *interrupted* (its live process is
  gone) but whatever it produced is still replayed.

Finished runs stay reconnectable for `run_retention_seconds`; after that the
bridge drops them and deletes the transcript, and reconnecting returns `404`.
`POST /api/abort` is the only thing that actually stops a running agent.

> **Important:** the bridge runs on *your* machine, not on the web host.
> Deploying the site does **not** update it — after pulling new code you must
> restart `python bridge/server.py` for these changes to take effect.

> Transcripts under `bridge/runs/` can contain command output and secrets. They
> are git-ignored; delete the folder to wipe saved runs.

## HTTP API

All routes need `Authorization: Bearer <token>`.

- `GET /api/health` → bridge status, resolved Claude path, working dir, active run count.
- `GET /api/runs` → `{ runs: [{ runId, status, done, conversationId, startedAt, finishedAt, frames, prompt }] }`. Running and recently-finished runs, so a returning client can see what is still cooking.
- `POST /api/chat` → `text/event-stream`. Body:
  `{ prompt, sessionId?, conversationId?, model?, effort?, permissionMode? }`.
  Starts a run and streams it. The run keeps going even if this connection drops.
  SSE events: `bridge` (run started, carries `runId`), `claude` (one raw
  `stream-json` object), `notice`, `error`, `done`.
- `GET /api/stream?runId=…&offset=N` → `text/event-stream`. Reconnects to an
  existing run and replays its buffered frames from index `N` (0 = the whole
  run), then tails until it finishes. `404` if the run is unknown or aged out.
- `POST /api/abort` → `{ runId }`, kills that run and its child processes.

Conversation continuity works by echoing the `session_id` from Claude Code's
`system/init` event back as `sessionId`; the bridge turns that into `--resume`.
