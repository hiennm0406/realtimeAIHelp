export function formatTokens(value) {
  const n = Number(value || 0)
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function formatCost(usd) {
  const n = Number(usd || 0)
  if (!n) return '$0'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(3)}`
}

export function formatDuration(ms) {
  const n = Number(ms || 0)
  if (n < 1000) return `${n}ms`
  if (n < 60_000) return `${(n / 1000).toFixed(1)}s`
  const minutes = Math.floor(n / 60_000)
  const seconds = Math.round((n % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}

/** Flattens Claude's usage object into the numbers worth showing. */
export function summarizeUsage(usage) {
  if (!usage) return null
  const input = Number(usage.input_tokens || 0)
  const output = Number(usage.output_tokens || 0)
  const cacheRead = Number(usage.cache_read_input_tokens || 0)
  const cacheWrite = Number(usage.cache_creation_input_tokens || 0)
  return {
    input,
    output,
    cacheRead,
    cacheWrite,
    thinking: Number(usage.output_tokens_details?.thinking_tokens || 0),
    webSearches: Number(usage.server_tool_use?.web_search_requests || 0),
    webFetches: Number(usage.server_tool_use?.web_fetch_requests || 0),
    // What the model actually had to read this turn, cached or not.
    totalInput: input + cacheRead + cacheWrite,
  }
}

/** One-line preview of a tool call's arguments, for the collapsed header. */
export function describeToolInput(input) {
  if (!input || typeof input !== 'object') return ''
  const pick = (...keys) => {
    for (const key of keys) {
      if (typeof input[key] === 'string' && input[key].trim()) return input[key].trim()
    }
    return ''
  }
  const primary = pick(
    'command',
    'file_path',
    'path',
    'pattern',
    'query',
    'url',
    'prompt',
    'description'
  )
  if (!primary) return ''
  const oneLine = primary.replace(/\s+/g, ' ')
  return oneLine.length > 110 ? `${oneLine.slice(0, 110)}…` : oneLine
}

export function stringifyToolContent(content) {
  if (content == null) return ''
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === 'string') return block
        if (block?.type === 'text') return block.text
        return JSON.stringify(block, null, 2)
      })
      .join('\n')
  }
  return JSON.stringify(content, null, 2)
}
