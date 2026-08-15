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
    sessionId: '',
    model: '',
    cwd: '',
    permissionMode: '',
    availableTools: [],
    status: '',
    liveUsage: null,
    rateLimit: null,
    totals: { cost: 0, turns: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  }
}

/**
 * Appends an item and returns it *as read back through the store*. When `convo`
 * is a Vue reactive object that read-back is the proxy, and mutating the proxy
 * is what schedules a re-render - mutating the raw object we passed in would
 * update the data silently and never repaint.
 */
function push(convo, item) {
  convo.seq += 1
  item.id = `i${convo.seq}`
  convo.timeline.push(item)
  return convo.timeline[convo.timeline.length - 1]
}

export function addUserMessage(convo, text) {
  return push(convo, { kind: 'user', text })
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

  push(convo, {
    kind: 'result',
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
