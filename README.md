# realtimeAIHelp

Claude Code, usable from any device. A Vue site you deploy to a host, plus a small
Python bridge that runs on the machine where Claude Code is installed. The site
sends your message to that machine, Claude Code does the work there with its full
toolset, and the transcript streams back — thinking, tool calls, tool output,
token usage and cost, the same information the terminal shows.

```
phone / laptop ──▶ Netlify (this Vue app)
                        │  HTTPS + Bearer token
                        ▼
                   tunnel URL  ──▶  bridge/server.py  ──▶  claude.exe
                                    (your PC)               your files, shell, web search
```

The site is static, so it never holds your credentials. Nothing runs in the cloud
except the page itself.

## Quick start

**1. Start the bridge** on the machine with Claude Code:

```
python bridge/server.py
```

Copy the access token it prints. Full details in [`bridge/README.md`](bridge/README.md).

**2. Expose it** so other devices can reach it:

```
cloudflared tunnel --url http://127.0.0.1:8787
```

**3. Run or deploy the site.**

```
npm install
npm run dev      # http://localhost:5173
npm run build    # -> dist/
```

Requires Node 22+ (see `.nvmrc`). For Netlify, connect the repo — `netlify.toml`
already sets the build command and publish directory. `public/_redirects` handles
SPA routing.

**4. Open the site → Settings**, paste the tunnel URL and token, hit
**Test connection**.

### Changing the prefilled bridge URL

Settings starts with a bridge URL already filled in, so a new device only needs
the token. It is baked in at build time, and a quick tunnel changes hostname on
every restart — when that happens, set `VITE_BRIDGE_URL` instead of editing the
source:

```
VITE_BRIDGE_URL=https://your-tunnel.trycloudflare.com npm run build
```

On Netlify: **Site settings → Environment variables**, add `VITE_BRIDGE_URL`,
redeploy. With no variable set it falls back to the value in `src/lib/bridge.js`.

The prefill only applies to devices that have never saved settings — the browser
remembers whatever you last typed, so on a device you already configured you
have to edit the field by hand.

## What the chat shows

| | |
| --- | --- |
| **Thinking** | Collapsed by default, expands to the reasoning. Empty when the model returns no reasoning text. |
| **Tool calls** | Name plus a one-line preview; expand for full JSON input and output. Colour-coded running / ok / error. |
| **Usage** | Per turn: input (fresh + cached), output, thinking tokens, web searches, cost, wall time. Running total in the header. |
| **Context** | How much of the model's context window the prompt is using, per turn and in the header. Derived from `modelUsage.contextWindow` and the turn's prompt tokens. Turns amber under 35% left, red under 15%. |
| **History** | **Chats** lists past conversations; click one to reopen it and keep talking on the same Claude Code session. Stored in the browser, so it is per-device and never leaves it. |
| **Session** | Follow-ups resume the same Claude Code session, so it keeps its context. **New** starts a fresh one. |
| **Background** | Runs live on the bridge, not in the tab. Close the page or lose signal and the agent keeps working; reopen the chat (or switch back to the tab) and it reconnects, replays what you missed, and shows the finished answer. Runs stay reconnectable for a retention window (`run_retention_seconds`, default 1h). **Stop** is the only thing that ends a run early. |

Settings let you pick the model, effort level, and permission mode per device, and
hide thinking or tool I/O if you want a plainer transcript.

## Security

The bridge defaults to `bypassPermissions`, which is what makes the web chat as
capable as the terminal. **Anyone with the token can run any command on your
machine.** Keep the token private, stop the tunnel when you're done, and read the
security section in [`bridge/README.md`](bridge/README.md) before exposing it.

## Layout

```
bridge/                Python bridge (stdlib only) + its docs
src/lib/               bridge client, SSE parsing, stream-json -> timeline, markdown
src/components/chat/   chat UI
```
