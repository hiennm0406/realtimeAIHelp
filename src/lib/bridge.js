/**
 * Client for the local Claude Code bridge (see bridge/server.py).
 *
 * The bridge relays Claude Code's `stream-json` output verbatim over SSE, so
 * everything the terminal shows - thinking, tool calls, token usage, cost - is
 * available here too.
 */

const STORAGE_KEY = 'claude-bridge-settings'

// Where the bridge lives. Fixed at build time, not editable per device: a
// device only ever needs the token.
//
// A Cloudflare *quick* tunnel hands out a NEW hostname every time cloudflared
// restarts, so a value of that shape goes stale on the next restart. When it
// does, rebuild with VITE_BRIDGE_URL set (Netlify: Site settings ->
// Environment variables) rather than editing this line - or point it at a named
// tunnel / Tailscale Funnel, whose hostname never moves.
const FALLBACK_BRIDGE_URL = 'https://judicial-incidents-eyes-use.trycloudflare.com'

// Optional chaining because `import.meta.env` only exists under Vite; this
// module is also loaded directly by the test harness.
export const BRIDGE_URL = import.meta.env?.VITE_BRIDGE_URL || FALLBACK_BRIDGE_URL

// `url` is deliberately absent: it is a build-time constant, so storing a copy
// per device is what let a stale hostname survive forever on a phone that had
// been configured once.
export const DEFAULT_SETTINGS = {
  token: '',
  model: '',
  effort: '',
  permissionMode: '',
  showThinking: true,
  showToolIO: true,
}

export function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const saved = raw ? JSON.parse(raw) : {}
    // Drop a `url` written by an older build; the constant is the only source
    // now, and there is no longer any UI that could correct a stale one.
    delete saved.url
    return { ...DEFAULT_SETTINGS, ...saved }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    /* private browsing / storage disabled - settings just won't persist */
  }
}

// Which run (if any) is still in flight for a conversation. Written when a run
// starts, cleared when it finishes, so that reopening the app - even after a
// full reload on another device - can reconnect to a run that kept working in
// the background on the bridge.
const ACTIVE_RUNS_KEY = 'claude-active-runs'

function readActiveRuns() {
  try {
    return JSON.parse(localStorage.getItem(ACTIVE_RUNS_KEY) || '{}') || {}
  } catch {
    return {}
  }
}

function writeActiveRuns(map) {
  try {
    localStorage.setItem(ACTIVE_RUNS_KEY, JSON.stringify(map))
  } catch {
    /* storage disabled - reconnect just won't be available */
  }
}

export function getActiveRun(conversationId) {
  return readActiveRuns()[conversationId] || null
}

// `anchor` is the conversation's timeline length at the moment the run started -
// i.e. right after the user's message, before any answer. On reconnect we
// truncate back to it and replay the run from scratch, so a run that was
// half-rendered (or half-saved) before the user left rebuilds cleanly with no
// duplicated blocks.
//
// `totals` is the matching snapshot of the conversation's cost/token counters at
// that same moment. Replaying the run re-applies its `result` frame, so the
// counters have to be rewound to this snapshot first or the run's cost is added
// twice. It lives here, not on the component, so it survives a page reload.
export function setActiveRun(conversationId, runId, anchor, totals) {
  if (!conversationId || !runId) return
  const map = readActiveRuns()
  const existing = map[conversationId]
  map[conversationId] = {
    runId,
    anchor: anchor ?? 0,
    // Re-arming the same run (a reconnect) must not overwrite the original
    // snapshot with counters the replay has already moved.
    totals: existing?.runId === runId ? existing.totals : totals ? { ...totals } : null,
    startedAt: existing?.runId === runId ? existing.startedAt : Date.now(),
  }
  writeActiveRuns(map)
}

export function clearActiveRun(conversationId) {
  const map = readActiveRuns()
  if (map[conversationId]) {
    delete map[conversationId]
    writeActiveRuns(map)
  }
}

/**
 * A run id, chosen here rather than by the bridge.
 *
 * The bridge accepts it verbatim (hex only - it becomes a filename), which is
 * what lets Stop abort a run in the window before the first frame has made it
 * back over a slow tunnel. Without it, hitting Stop early left the run working
 * on the bridge with nobody watching, holding a concurrency slot until it timed
 * out half an hour later.
 */
export function newRunId() {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function baseUrl() {
  return BRIDGE_URL.trim().replace(/\/+$/, '')
}

function authHeaders(settings) {
  return {
    Authorization: `Bearer ${(settings.token || '').trim()}`,
    'Content-Type': 'application/json',
  }
}

/**
 * Fetch with a deadline, so a tunnel that accepts the connection and then goes
 * quiet fails in seconds instead of hanging the button forever.
 */
async function fetchWithTimeout(url, options = {}, ms = 20000) {
  const timer = new AbortController()
  const id = setTimeout(() => timer.abort(), ms)
  // Honour a caller's signal too, without losing the timeout.
  const onOuterAbort = () => timer.abort()
  options.signal?.addEventListener('abort', onOuterAbort, { once: true })
  try {
    return await fetch(url, { ...options, signal: timer.signal })
  } catch (error) {
    if (error.name === 'AbortError' && !options.signal?.aborted) {
      throw new Error(`The bridge did not respond within ${Math.round(ms / 1000)}s.`)
    }
    throw error
  } finally {
    clearTimeout(id)
    options.signal?.removeEventListener('abort', onOuterAbort)
  }
}

export async function checkHealth(settings, signal) {
  const response = await fetchWithTimeout(`${baseUrl()}/api/health`, {
    headers: authHeaders(settings),
    signal,
  })
  if (!response.ok) {
    throw new Error(
      response.status === 401
        ? 'Token rejected by the bridge.'
        : `Bridge replied ${response.status}.`
    )
  }
  return response.json()
}

export async function abortRun(settings, runId) {
  if (!runId) return
  await fetch(`${baseUrl()}/api/abort`, {
    method: 'POST',
    headers: authHeaders(settings),
    body: JSON.stringify({ runId }),
  }).catch(() => {})
}

/**
 * A plain (non-streaming) snapshot of a run's frames from `offset` onward, plus
 * whether it's finished. Short request/response, so it works over tunnels that
 * buffer or drop the long-lived /api/stream reconnect. Clients poll this.
 *
 * Returns `{ runId, done, status, next, frames: [[event, data], ...] }`.
 * Throws with `error.status === 404` when the run is gone.
 */
export async function fetchRunSnapshot(settings, runId, offset = 0, signal) {
  const url = `${baseUrl()}/api/run?runId=${encodeURIComponent(runId)}&offset=${offset}`
  const response = await fetchWithTimeout(url, { headers: authHeaders(settings), signal }, 30000)
  if (!response.ok) throw await errorFromResponse(response)
  return response.json()
}

/** Runs the bridge is still holding: in-flight ones, plus recently finished. */
export async function listRuns(settings, signal) {
  const response = await fetchWithTimeout(`${baseUrl()}/api/runs`, {
    headers: authHeaders(settings),
    signal,
  })
  if (!response.ok) throw new Error(`Bridge replied ${response.status}.`)
  const body = await response.json()
  return Array.isArray(body.runs) ? body.runs : []
}

/**
 * Reads an SSE response and fans each frame out to `handlers`.
 *
 * `handlers` receives:
 *   onBridge(data)  - bridge lifecycle (started, with runId)
 *   onClaude(data)  - one raw stream-json object straight from Claude Code
 *   onNotice(data)  - non-JSON output Claude printed
 *   onError(data)   - bridge or Claude error
 *   onDone(data)    - run finished, carries exitCode
 *
 * `onActivity` fires on every chunk received, keepalive pings included, so the
 * caller can tell a live-but-quiet stream (Claude thinking) from a dead socket.
 */
async function readEventStream(response, handlers, onActivity) {
  if (!response.body) throw new Error('This browser cannot read streaming responses.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (event, raw) => {
    let data
    try {
      data = JSON.parse(raw)
    } catch {
      return
    }
    if (event === 'claude') handlers.onClaude?.(data)
    else if (event === 'bridge') handlers.onBridge?.(data)
    else if (event === 'notice') handlers.onNotice?.(data)
    else if (event === 'error') handlers.onError?.(data)
    else if (event === 'done') handlers.onDone?.(data)
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    onActivity?.()
    buffer += decoder.decode(value, { stream: true })

    let split
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)

      let event = 'message'
      const dataLines = []
      for (const line of frame.split('\n')) {
        if (line.startsWith(':')) continue // keepalive ping
        if (line.startsWith('id:')) continue // frame index; the offset is tracked server-side
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (dataLines.length) dispatch(event, dataLines.join('\n'))
    }
  }
}

async function errorFromResponse(response) {
  let message = `Bridge replied ${response.status}.`
  try {
    const body = await response.json()
    if (body?.error) message = body.error
  } catch {
    /* keep the status-code message */
  }
  const error = new Error(message)
  error.status = response.status
  return error
}

/**
 * Starts a Claude Code run and streams it. The run keeps going on the bridge
 * even if this connection drops, so a returning client can pick it back up by
 * polling `fetchRunSnapshot`.
 */
export async function streamChat({
  settings,
  prompt,
  runId,
  sessionId,
  conversationId,
  handlers = {},
  signal,
  onActivity,
}) {
  const response = await fetch(`${baseUrl()}/api/chat`, {
    method: 'POST',
    headers: authHeaders(settings),
    signal,
    body: JSON.stringify({
      prompt,
      runId: runId || undefined,
      sessionId: sessionId || undefined,
      conversationId: conversationId || undefined,
      model: settings.model || undefined,
      effort: settings.effort || undefined,
      permissionMode: settings.permissionMode || undefined,
    }),
  })

  if (!response.ok) throw await errorFromResponse(response)
  await readEventStream(response, handlers, onActivity)
}
