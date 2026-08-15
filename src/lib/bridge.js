/**
 * Client for the local Claude Code bridge (see bridge/server.py).
 *
 * The bridge relays Claude Code's `stream-json` output verbatim over SSE, so
 * everything the terminal shows - thinking, tool calls, token usage, cost - is
 * available here too.
 */

const STORAGE_KEY = 'claude-bridge-settings'

export const DEFAULT_SETTINGS = {
  url: 'http://127.0.0.1:8787',
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

/**
 * Streams one Claude Code run.
 *
 * `handlers` receives:
 *   onBridge(data)  - bridge lifecycle (started, with runId)
 *   onClaude(data)  - one raw stream-json object straight from Claude Code
 *   onNotice(data)  - non-JSON output Claude printed
 *   onError(data)   - bridge or Claude error
 *   onDone(data)    - run finished, carries exitCode
 */
export async function streamChat({ settings, prompt, sessionId, handlers = {}, signal }) {
  const response = await fetch(`${baseUrl(settings)}/api/chat`, {
    method: 'POST',
    headers: authHeaders(settings),
    signal,
    body: JSON.stringify({
      prompt,
      sessionId: sessionId || undefined,
      model: settings.model || undefined,
      effort: settings.effort || undefined,
      permissionMode: settings.permissionMode || undefined,
    }),
  })

  if (!response.ok) {
    let message = `Bridge replied ${response.status}.`
    try {
      const body = await response.json()
      if (body?.error) message = body.error
    } catch {
      /* keep the status-code message */
    }
    throw new Error(message)
  }
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
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (dataLines.length) dispatch(event, dataLines.join('\n'))
    }
  }
}
