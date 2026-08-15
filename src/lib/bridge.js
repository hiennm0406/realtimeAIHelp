/**
 * Client for the local Claude Code bridge (see bridge/server.py).
 *
 * The bridge relays Claude Code's `stream-json` output verbatim over SSE, so
 * everything the terminal shows - thinking, tool calls, token usage, cost - is
 * available here too.
 */

const STORAGE_KEY = 'claude-bridge-settings'

// Where the bridge lives, prefilled into Settings on a device that has never
// been configured. A quick tunnel hands out a NEW hostname every time
// cloudflared restarts, so when that happens this value goes stale: set
// VITE_BRIDGE_URL at build time (Netlify: Site settings -> Environment
// variables) to change it without touching code, or use a named tunnel to get
// a hostname that never moves.
const FALLBACK_BRIDGE_URL = 'https://compute-separate-point-stages.trycloudflare.com'

// Optional chaining because `import.meta.env` only exists under Vite; this
// module is also loaded directly by the test harness.
export const DEFAULT_SETTINGS = {
  url: import.meta.env?.VITE_BRIDGE_URL || FALLBACK_BRIDGE_URL,
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
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : { ...DEFAULT_SETTINGS }
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
export function setActiveRun(conversationId, runId, anchor) {
  if (!conversationId || !runId) return
  const map = readActiveRuns()
  map[conversationId] = { runId, anchor: anchor ?? 0, startedAt: Date.now() }
  writeActiveRuns(map)
}

export function clearActiveRun(conversationId) {
  const map = readActiveRuns()
  if (map[conversationId]) {
    delete map[conversationId]
    writeActiveRuns(map)
  }
}

function baseUrl(settings) {
  return (settings.url || '').trim().replace(/\/+$/, '')
}

function authHeaders(settings) {
  return {
    Authorization: `Bearer ${(settings.token || '').trim()}`,
    'Content-Type': 'application/json',
  }
}

export async function checkHealth(settings) {
  const response = await fetch(`${baseUrl(settings)}/api/health`, {
    headers: authHeaders(settings),
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
  await fetch(`${baseUrl(settings)}/api/abort`, {
    method: 'POST',
    headers: authHeaders(settings),
    body: JSON.stringify({ runId }),
  }).catch(() => {})
}

/** Runs the bridge is still holding: in-flight ones, plus recently finished. */
export async function listRuns(settings) {
  const response = await fetch(`${baseUrl(settings)}/api/runs`, {
    headers: authHeaders(settings),
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
 */
async function readEventStream(response, handlers) {
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
 * even if this connection drops, so a returning client can pick it up again with
 * `resumeChat`.
 */
export async function streamChat({
  settings,
  prompt,
  sessionId,
  conversationId,
  handlers = {},
  signal,
}) {
  const response = await fetch(`${baseUrl(settings)}/api/chat`, {
    method: 'POST',
    headers: authHeaders(settings),
    signal,
    body: JSON.stringify({
      prompt,
      sessionId: sessionId || undefined,
      conversationId: conversationId || undefined,
      model: settings.model || undefined,
      effort: settings.effort || undefined,
      permissionMode: settings.permissionMode || undefined,
    }),
  })

  if (!response.ok) throw await errorFromResponse(response)
  await readEventStream(response, handlers)
}

/**
 * Reconnects to a run that is still alive (or recently finished) on the bridge
 * and replays it from `offset`. With offset 0 the whole run replays, which is
 * how a fresh page rebuilds the in-progress turn after the user comes back.
 *
 * Throws with `error.status === 404` when the run is gone (finished long enough
 * ago that the bridge dropped it).
 */
export async function resumeChat({ settings, runId, offset = 0, handlers = {}, signal }) {
  const url = `${baseUrl(settings)}/api/stream?runId=${encodeURIComponent(runId)}&offset=${offset}`
  const response = await fetch(url, { headers: authHeaders(settings), signal })
  if (!response.ok) throw await errorFromResponse(response)
  await readEventStream(response, handlers)
}
