/**
 * Chat history in localStorage.
 *
 * The index and the conversation bodies are stored under separate keys so that
 * listing the sidebar never has to parse megabytes of transcript.
 *
 * localStorage is only ~5MB, and a single agentic turn can produce far more
 * than that in tool output, so bodies are trimmed on the way in and the oldest
 * conversations are evicted when the browser refuses a write.
 */

const INDEX_KEY = 'claude-chat-index'
const BODY_PREFIX = 'claude-chat:'

const MAX_CONVERSATIONS = 40
const MAX_TOOL_CHARS = 4000
const MAX_TEXT_CHARS = 20000

function readIndex() {
  try {
    const raw = localStorage.getItem(INDEX_KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function writeIndex(list) {
  try {
    localStorage.setItem(INDEX_KEY, JSON.stringify(list))
  } catch {
    /* out of space; the caller's eviction pass handles it */
  }
}

export function listConversations() {
  return readIndex().sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
}

export function newConversationId() {
  return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

/** First user message, condensed into something readable in a sidebar. */
export function deriveTitle(timeline) {
  const first = timeline.find((item) => item.kind === 'user')
  if (!first) return 'New chat'
  const line = first.text.replace(/\s+/g, ' ').trim()
  if (!line) return 'New chat'
  return line.length > 60 ? `${line.slice(0, 60)}…` : line
}

function trim(value, limit) {
  if (typeof value !== 'string') return value
  return value.length > limit ? `${value.slice(0, limit)}\n… (trimmed for storage)` : value
}

/** Drops the live-run bookkeeping and caps the bulky fields. */
function packTimeline(timeline) {
  return timeline.map((item) => {
    if (item.kind === 'tool') {
      return {
        ...item,
        result: trim(
          typeof item.result === 'string' ? item.result : JSON.stringify(item.result ?? ''),
          MAX_TOOL_CHARS
        ),
      }
    }
    if (item.kind === 'text' || item.kind === 'thinking') {
      return { ...item, text: trim(item.text, MAX_TEXT_CHARS) }
    }
    return item
  })
}

export function saveConversation(id, convo) {
  if (!id || !convo?.timeline?.length) return

  const body = {
    timeline: packTimeline(convo.timeline),
    sessionId: convo.sessionId,
    model: convo.model,
    cwd: convo.cwd,
    permissionMode: convo.permissionMode,
    context: convo.context,
    totals: convo.totals,
    seq: convo.seq,
  }

  const entry = {
    id,
    title: deriveTitle(convo.timeline),
    sessionId: convo.sessionId,
    model: convo.model,
    cost: convo.totals?.cost || 0,
    messages: convo.timeline.filter((i) => i.kind === 'user').length,
    updatedAt: Date.now(),
  }

  const index = readIndex().filter((e) => e.id !== id)
  index.unshift(entry)

  // Trim to the cap before writing, so eviction is not driven only by quota errors.
  const keep = index.slice(0, MAX_CONVERSATIONS)
  for (const dropped of index.slice(MAX_CONVERSATIONS)) {
    try {
      localStorage.removeItem(BODY_PREFIX + dropped.id)
    } catch {
      /* ignore */
    }
  }

  let remaining = [...keep]
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      localStorage.setItem(BODY_PREFIX + id, JSON.stringify(body))
      writeIndex(remaining)
      return
    } catch {
      // Out of space: drop the oldest conversation that is not the one being
      // saved, then try again.
      const victim = [...remaining].reverse().find((e) => e.id !== id)
      if (!victim) {
        writeIndex(remaining)
        return
      }
      remaining = remaining.filter((e) => e.id !== victim.id)
      try {
        localStorage.removeItem(BODY_PREFIX + victim.id)
      } catch {
        /* ignore */
      }
    }
  }
}

export function loadConversation(id) {
  try {
    const raw = localStorage.getItem(BODY_PREFIX + id)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function deleteConversation(id) {
  try {
    localStorage.removeItem(BODY_PREFIX + id)
  } catch {
    /* ignore */
  }
  writeIndex(readIndex().filter((e) => e.id !== id))
}

export function clearAllConversations() {
  for (const entry of readIndex()) {
    try {
      localStorage.removeItem(BODY_PREFIX + entry.id)
    } catch {
      /* ignore */
    }
  }
  writeIndex([])
}
