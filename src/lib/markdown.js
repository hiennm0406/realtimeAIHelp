/**
 * Small markdown renderer for assistant output.
 *
 * Deliberately dependency-free: everything is HTML-escaped before any markup is
 * introduced, so model output can never inject markup into the page.
 */

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (ch) => ESCAPES[ch])
}

function inline(text) {
  return (
    text
      // `code`
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      // **bold**
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      // *italic* / _italic_
      .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
      .replace(/(^|[^_\w])_([^_\n]+)_(?![\w_])/g, '$1<em>$2</em>')
      // [label](https://…) — only http(s), so no javascript: URLs
      .replace(
        /\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
      )
  )
}

export function renderMarkdown(source) {
  const escaped = escapeHtml(source)
  const lines = escaped.split('\n')
  const out = []

  let inFence = false
  let fenceLang = ''
  let fenceBuffer = []
  let listType = null

  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`)
      listType = null
    }
  }

  const openList = (type) => {
    if (listType !== type) {
      closeList()
      out.push(`<${type}>`)
      listType = type
    }
  }

  for (const line of lines) {
    const fence = line.match(/^\s*```(\w*)\s*$/)

    if (fence) {
      if (inFence) {
        out.push(
          `<pre class="md-code"${fenceLang ? ` data-lang="${fenceLang}"` : ''}><code>${fenceBuffer.join('\n')}</code></pre>`
        )
        inFence = false
        fenceBuffer = []
        fenceLang = ''
      } else {
        closeList()
        inFence = true
        fenceLang = fence[1] || ''
      }
      continue
    }

    if (inFence) {
      fenceBuffer.push(line)
      continue
    }

    if (!line.trim()) {
      closeList()
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      closeList()
      const level = Math.min(heading[1].length + 2, 6)
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
      continue
    }

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    if (bullet) {
      openList('ul')
      out.push(`<li>${inline(bullet[1])}</li>`)
      continue
    }

    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (numbered) {
      openList('ol')
      out.push(`<li>${inline(numbered[1])}</li>`)
      continue
    }

    closeList()
    out.push(`<p>${inline(line)}</p>`)
  }

  if (inFence && fenceBuffer.length) {
    out.push(`<pre class="md-code"><code>${fenceBuffer.join('\n')}</code></pre>`)
  }
  closeList()

  return out.join('\n')
}
