/**
 * Turns Claude Code's raw `stream-json` events into a flat, renderable timeline.
 *
 * Two kinds of event describe the same content:
 *   - `stream_event` carries partial deltas, which is what makes text appear
 *     token by token;
 *   - `assistant` carries the finished message.
 * Both are keyed by `${messageId}#${blockIndex}`, so the finished message simply
 * overwrites whatever the deltas built up. That keeps the live feel of streaming
 * without ever leaving partially-decoded text on screen.
 */

import { summarizeUsage } from './format.js'

export function createConversation() {
  return {
    seq: 0,
    timeline: [],
    blocks: {}, // `${messageId}#${index}` -> timeline item
    tools: {}, // tool_use id -> timeline item
    // Declared here rather than sprung into existence on the first
    // message_start, so that Object.assign(convo, createConversation()) - how a
    // new chat is started - actually clears it instead of leaving the previous
    // conversation's message id behind.
    currentMessageId: '',
    sessionId: '',
    model: '',
    cwd: '',
    permissionMode: '',
    availableTools: [],
    status: '',
    liveUsage: null,
    rateLimit: null,
    // How full the model's context window is, from the last completed turn.
    context: null,
    totals: { cost: 0, turns: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  }
}

/**
 * Context pressure for the turn that just finished.
 *
 * Everything the model had to read this turn - fresh input plus whatever was
 * served from or written to the prompt cache - is the prompt, and the prompt is
 * what fills the context window. Claude Code reports the window size per model
 * in `modelUsage`, so the remaining share is derivable rather than guessed.
 */
function readContext(data) {
  const models = data.modelUsage
  if (!models || typeof models !== 'object') return null

  const entry = models[data.model] || Object.values(models)[0]
  const window = Number(entry?.contextWindow || 0)
  if (!window) return null

  const usage = data.usage || {}
  const used =
    Number(usage.input_tokens || 0) +
    Number(usage.cache_read_input_tokens || 0) +
    Number(usage.cache_creation_input_tokens || 0)

  const remaining = Math.max(0, window - used)
  return {
    window,
    used,
    remaining,
    percentLeft: Math.max(0, Math.min(100, (remaining / window) * 100)),
  }
}

/**
 * Appends an item and returns it *as read back through the store*. When `convo`
 * is a Vue reactive object that read-back is the proxy, and mutating the proxy
 * is what schedules a re-render - mutating the raw object we passed in would
 * update the data silently and never repaint.
 */
/**
 * Rebuilds a conversation saved by lib/history.
 *
 * `blocks` and `tools` are intentionally left empty: they key off message IDs
 * from a live run, and any further turn on this conversation produces fresh
 * ones. `seq` is carried over so newly appended items cannot collide with the
 * restored ones' ids.
 */
export function restoreConversation(body) {
  const convo = createConversation()
  if (!body) return convo

  convo.timeline = Array.isArray(body.timeline) ? body.timeline : []
  convo.sessionId = body.sessionId || ''
  convo.model = body.model || ''
  convo.cwd = body.cwd || ''
  convo.permissionMode = body.permissionMode || ''
  convo.context = body.context || null
  if (body.totals) Object.assign(convo.totals, body.totals)
  convo.seq = Number(body.seq) || convo.timeline.length
  return convo
}

function push(convo, item) {
  convo.seq += 1
  item.id = `i${convo.seq}`
  convo.timeline.push(item)
  return convo.timeline[convo.timeline.length - 1]
}

/**
 * `images` are thumbnails, not the bytes that were sent. The full-size copies
 * went to the model and are not kept: the transcript lives in localStorage,
 * where a few full-resolution screenshots would evict the rest of the history.
 */
export function addUserMessage(convo, text, images = []) {
  const item = { kind: 'user', text }
  if (images.length) item.images = images
  return push(convo, item)
}

export function addLocalError(convo, text) {
  convo.status = ''
  return push(convo, { kind: 'error', text })
}

function blockKey(messageId, index) {
  return `${messageId || 'msg'}#${index}`
}

function ensureBlock(convo, key, factory) {
  if (!convo.blocks[key]) {
    convo.blocks[key] = push(convo, factory())
  }
  return convo.blocks[key]
}

function applyStreamEvent(convo, wrapper) {
  const event = wrapper.event
  if (!event) return

  if (event.type === 'message_start') {
    convo.currentMessageId = event.message?.id || ''
    convo.status = 'responding'
    return
  }

  if (event.type === 'message_delta') {
    if (event.usage) convo.liveUsage = summarizeUsage(event.usage)
    return
  }

  if (event.type === 'message_stop') {
    convo.status = ''
    return
  }

  const key = blockKey(convo.currentMessageId, event.index)

  if (event.type === 'content_block_start') {
    const block = event.content_block || {}
    if (block.type === 'text') {
      ensureBlock(convo, key, () => ({ kind: 'text', text: '', done: false }))
    } else if (block.type === 'thinking') {
      convo.status = 'thinking'
      ensureBlock(convo, key, () => ({ kind: 'thinking', text: '', done: false }))
    } else if (block.type === 'tool_use') {
      const item = ensureBlock(convo, key, () => ({
        kind: 'tool',
        name: block.name || 'tool',
        toolId: block.id || '',
        input: null,
        result: '',
        status: 'running',
      }))
      if (block.id) convo.tools[block.id] = item
    }
    return
  }

  if (event.type === 'content_block_delta') {
    const item = convo.blocks[key]
    if (!item) return
    const delta = event.delta || {}
    if (delta.type === 'text_delta') item.text += delta.text || ''
    else if (delta.type === 'thinking_delta') item.text += delta.thinking || ''
    // input_json_delta is partial JSON; the finished message fills it in properly.
    return
  }

  if (event.type === 'content_block_stop') {
    const item = convo.blocks[key]
    if (item && 'done' in item) item.done = true
  }
}

function applyAssistantMessage(convo, wrapper) {
  const message = wrapper.message
  if (!message) return
  const content = Array.isArray(message.content) ? message.content : []

  content.forEach((block, index) => {
    const key = blockKey(message.id, index)

    if (block.type === 'text') {
      const item = ensureBlock(convo, key, () => ({ kind: 'text', text: '', done: false }))
      item.text = block.text || ''
      item.done = true
    } else if (block.type === 'thinking') {
      const item = ensureBlock(convo, key, () => ({
        kind: 'thinking',
        text: '',
        done: false,
      }))
      // With display "omitted" the text is empty - the block still tells the
      // user that Claude reasoned here, which is worth showing.
      item.text = block.thinking || item.text || ''
      item.done = true
    } else if (block.type === 'tool_use') {
      const item = ensureBlock(convo, key, () => ({
        kind: 'tool',
        name: block.name || 'tool',
        toolId: block.id || '',
        input: null,
        result: '',
        status: 'running',
      }))
      item.name = block.name || item.name
      item.toolId = block.id || item.toolId
      item.input = block.input ?? item.input
      if (item.toolId) convo.tools[item.toolId] = item
    }
  })

  if (message.usage) convo.liveUsage = summarizeUsage(message.usage)
  if (message.model) convo.model = message.model
}

function applyUserMessage(convo, wrapper) {
  const content = wrapper.message?.content
  if (!Array.isArray(content)) return

  for (const block of content) {
    if (block?.type !== 'tool_result') continue
    const item = convo.tools[block.tool_use_id]
    if (!item) continue
    item.result = block.content
    item.status = block.is_error ? 'error' : 'ok'
  }
}

function applyResult(convo, data) {
  convo.status = ''
  convo.sessionId = data.session_id || convo.sessionId

  const usage = summarizeUsage(data.usage)
  if (usage) {
    convo.totals.input += usage.input
    convo.totals.output += usage.output
    convo.totals.cacheRead += usage.cacheRead
    convo.totals.cacheWrite += usage.cacheWrite
  }
  convo.totals.cost += Number(data.total_cost_usd || 0)
  convo.totals.turns += Number(data.num_turns || 0)

  const context = readContext(data)
  if (context) convo.context = context

  push(convo, {
    kind: 'result',
    context,
    isError: Boolean(data.is_error),
    subtype: data.subtype || '',
    text: data.is_error ? data.result || 'Run failed.' : '',
    usage,
    cost: Number(data.total_cost_usd || 0),
    durationMs: Number(data.duration_ms || 0),
    apiDurationMs: Number(data.duration_api_ms || 0),
    ttftMs: Number(data.ttft_ms || 0),
    turns: Number(data.num_turns || 0),
    stopReason: data.stop_reason || '',
    permissionDenials: data.permission_denials || [],
  })
}

/** Feeds one raw stream-json object into the timeline. */
export function applyClaudeEvent(convo, data) {
  if (!data || typeof data !== 'object') return

  switch (data.type) {
    case 'system':
      if (data.subtype === 'init') {
        convo.sessionId = data.session_id || convo.sessionId
        convo.model = data.model || convo.model
        convo.cwd = data.cwd || convo.cwd
        convo.permissionMode = data.permissionMode || convo.permissionMode
        convo.availableTools = data.tools || convo.availableTools
        convo.status = 'starting'
      } else if (data.subtype === 'status') {
        convo.status = data.status || ''
      }
      return

    case 'stream_event':
      applyStreamEvent(convo, data)
      return

    case 'assistant':
      applyAssistantMessage(convo, data)
      return

    case 'user':
      applyUserMessage(convo, data)
      return

    case 'rate_limit_event':
      convo.rateLimit = data.rate_limit_info || null
      return

    case 'result':
      applyResult(convo, data)
      return

    default:
      // Unknown event types are ignored on purpose: Claude Code adds new ones
      // over time and none of them should break the transcript.
      return
  }
}
