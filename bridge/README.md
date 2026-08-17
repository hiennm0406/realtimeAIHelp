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

### A locked-down profile

This gives the web chat file access to one project, web search, and nothing else
— no shell, no downloads, no reach into the rest of the machine:

```json
{
  "default_permission_mode": "default",
  "dangerously_skip_permissions": false,
  "allowed_permission_modes": [],
  "allowed_tools": ["Read", "Glob", "Grep", "WebSearch", "TodoWrite", "Write", "Edit"],
  "disallowed_tools": ["Bash", "BashOutput", "KillShell", "PowerShell",
                       "WebFetch", "Task", "NotebookEdit"],
  "confine_to_cwd": true,
  "writable_paths": ["data"]
}
```

Two limits worth knowing before relying on it:

- **Claude Code refuses to write anywhere under `.claude/`** regardless of these
  settings, in every permission mode. Skills therefore cannot be authored from
  the web chat; write them from a desktop session instead.
- The fence is Claude Code's permission layer, not the operating system. A run
  still executes as the user running the bridge. For a boundary that does not
  depend on the agent honouring its own rules, run the bridge as a dedicated
  user whose filesystem access is limited by OS permissions.

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
| `allowed_tools` | `[]` | Tools that run without a prompt. `[]` means every tool, including Bash and WebFetch. Bare tool names work; **path patterns such as `Write(data/**)` do not match on Windows** — they fail closed, denying everything. Use `writable_paths` instead. |
| `disallowed_tools` | `[]` | Tools refused outright, overriding `allowed_tools`. Passed on the command line, so a run cannot lift it by editing a settings file. Path patterns **do** work here. |
| `allowed_permission_modes` | `[]` | Permission modes the browser may select. `[]` means it cannot change the mode at all — otherwise a token holder could pick `bypassPermissions` and grant themselves a shell. |
| `confine_to_cwd` | `false` | Fence `Read`/`Write`/`Edit` into `default_cwd`. Generates deny rules for every path outside it, refreshed on every run, so a folder created later is covered too. Without this a run can read any file the bridge's user can — other projects, `~/.ssh`, `~/.claude/.credentials.json`. |
| `writable_paths` | `[]` | Subdirectories of `default_cwd` that `Write`/`Edit` may touch, e.g. `["data"]`. Everything else in the project becomes read-only. Needs `confine_to_cwd`. |
| `allowed_origins` | `["*"]` | CORS. Narrow this to your site's URL once deployed. |
| `max_concurrent` | `2` | Simultaneous Claude runs. |
| `run_idle_timeout_seconds` | `1800` | Kill a run only after this long with **no output at all**. An actively working agent keeps streaming, so it's never reaped mid-work — only a hung one is. (Replaces the old wall-clock `run_timeout_seconds`, still honored if present.) |
| `run_max_seconds` | `21600` | Absolute backstop, in case a run prints forever. The idle timeout is the real guard. |
| `run_retention_seconds` | `604800` | How long a finished run's transcript stays **on disk**, and so how long it stays reconnectable. A week by default — it is only a file. |
| `run_memory_seconds` | `600` | How long a finished run's frames stay in **RAM** after last use. Past this they are dropped and re-read from the transcript on demand. |
| `max_body_bytes` | `33554432` | Largest request body accepted, so a bogus `Content-Length` cannot turn into an unbounded allocation. Attached images travel as base64, which inflates them by a third, so this sits above the image limits below. |

## Image attachments

`POST /api/chat` takes an optional `images` array alongside the prompt:

```json
{ "prompt": "what is wrong here?",
  "images": [{ "mediaType": "image/png", "data": "<base64>" }] }
```

They are forwarded to Claude Code as `stream-json` content blocks, so the model
**sees** them directly — no tool call, and nothing is written to disk, so the
confinement rules are untouched by this feature. A message with images and no
prompt is valid: sending a screenshot is a complete request on its own.

PNG, JPEG, GIF and WebP only, max 8 per message, 8MB each and 24MB in total.
The declared `mediaType` must match the file's magic bytes — that field is what
tells the API how to decode the payload, so a mismatch is refused rather than
forwarded. SVG is rejected outright: it is markup that can carry script, and the
API does not accept it anyway.

The bytes are held only until they have been written to Claude Code's stdin, and
the transcript records their shape (`{mediaType, bytes}`) rather than their
contents — otherwise every reconnectable run would pin its attachments in RAM
for a week and bloat `runs/` by the size of every screenshot ever sent.

The browser downscales to 1568px before uploading, which is where Claude
downsamples anyway, so the limits above are far more generous than normal use
needs.

## Background runs

A run is driven by a background worker that is independent of the browser
connection. Every event is **streamed to disk** at `bridge/runs/<runId>.jsonl`,
so closing the tab, losing signal, walking away — or even restarting the bridge
— does **not** stop or lose the agent's work. When you come back the UI polls
`GET /api/run?runId=…&offset=N`, replays everything it missed, and keeps
catching up until the run finishes.

The transcript on disk is the source of truth; memory is only a cache of it.
Frames of a finished run are dropped from RAM `run_memory_seconds` after they
were last read, and reloaded from the file when something asks for them again.
That is what lets `run_retention_seconds` be a week without the bridge slowly
growing to hold every byte of tool output it has ever streamed — which matters
on a 1 GB VPS.

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
  `{ prompt, runId?, sessionId?, conversationId?, model?, effort?, permissionMode? }`.
  Starts a run and streams it. The run keeps going even if this connection drops.
  SSE events: `bridge` (run started, carries `runId`), `claude` (one raw
  `stream-json` object), `notice`, `error`, `done`.
  `runId` lets the caller name the run (hex, 16–64 chars) so it can abort it
  before the first frame comes back; omit it and the bridge picks one. `409` if
  the id is already in use, or if that id was aborted while this request was in
  flight.
- `GET /api/run?runId=…&offset=N` → JSON snapshot
  `{ runId, done, status, next, total, frames }` from index `N`. A plain
  request/response, so it survives tunnels that buffer or drop a long-lived
  stream. This is what the UI polls. At most 400 frames come back per call, so
  catching up on a big run is a series of small responses — keep asking while
  `next < total`, and treat the run as finished only when `done` is true **and**
  `next >= total`.
- `GET /api/stream?runId=…&offset=N` → `text/event-stream`. Reconnects to an
  existing run and replays its frames from index `N` (0 = the whole run), then
  tails until it finishes. `404` if the run is unknown or aged out.
- `POST /api/abort` → `{ runId }`, kills that run and its child processes. If the
  run has not been created yet (Stop pressed while `POST /api/chat` is still in
  flight) the id is recorded as cancelled and the run is refused when it arrives.

Conversation continuity works by echoing the `session_id` from Claude Code's
`system/init` event back as `sessionId`; the bridge turns that into `--resume`.
