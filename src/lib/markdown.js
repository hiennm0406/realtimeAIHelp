/**
 * Small markdown renderer for assistant output.
 *
 * Deliberately dependency-free: the whole source is HTML-escaped before any
 * markup is introduced, so model output can never inject markup into the page.
 * Everything downstream therefore works on already-escaped text - which is why
 * block detection looks for `&gt;` rather than `>`.
 */

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (ch) => ESCAPES[ch])
}

// Placeholder for a code span while the emphasis passes run. Without this,
// `**` / `_` / `*` inside a code span get turned into markup - so an identifier
// like `snake_case_name` came out with its middle word italicised. NUL is used
// because it cannot occur in rendered text and is not a regex metacharacter.
const MARK = '\u0000'

function inline(text) {
  const codes = []
  let out = text.replace(/`([^`\n]+)`/g, (_match, code) => {
    codes.push(code)
    return `${MARK}${codes.length - 1}${MARK}`
  })

  out = out
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/(^|[^_\w])_([^_\n]+)_(?![\w_])/g, '$1<em>$2</em>')
    // [label](https://…) — only http(s), so no javascript: URLs
    .replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    )

  return out.replace(
    new RegExp(`${MARK}(\\d+)${MARK}`, 'g'),
    (_match, index) => `<code>${codes[Number(index)]}</code>`
  )
}

// ---------- tables ----------

/** `| --- | :--: |` and friends: the row that turns the one above into a header. */
function isTableRule(line) {
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.includes('-')
}

function isTableRow(line) {
  return line.includes('|') && line.trim() !== ''
}

function splitRow(line) {
  let text = line.trim()
  if (text.startsWith('|')) text = text.slice(1)
  if (text.endsWith('|')) text = text.slice(0, -1)
  return text.split('|').map((cell) => cell.trim())
}

/** Column alignments from the rule row: `:--` left, `--:` right, `:-:` center. */
function readAlignments(rule) {
  return splitRow(rule).map((cell) => {
    const left = cell.startsWith(':')
    const right = cell.endsWith(':')
    if (left && right) return 'center'
    if (right) return 'right'
    if (left) return 'left'
    return ''
  })
}

function renderTable(header, rule, bodyLines) {
  const heads = splitRow(header)
  const aligns = readAlignments(rule)
  const attr = (index) => (aligns[index] ? ` style="text-align:${aligns[index]}"` : '')

  const out = ['<div class="md-tablewrap"><table class="md-table"><thead><tr>']
  heads.forEach((cell, index) => out.push(`<th${attr(index)}>${inline(cell)}</th>`))
  out.push('</tr></thead><tbody>')

  for (const line of bodyLines) {
    const cells = splitRow(line)
    out.push('<tr>')
    for (let index = 0; index < heads.length; index += 1) {
      out.push(`<td${attr(index)}>${inline(cells[index] ?? '')}</td>`)
    }
    out.push('</tr>')
  }

  out.push('</tbody></table></div>')
  return out.join('')
}

// ---------- blocks ----------

function indentOf(line) {
  const lead = line.match(/^[ \t]*/)[0]
  // A tab counts as four columns, which is what the common editors emit.
  return lead.replace(/\t/g, '    ').length
}

/**
 * Renders already-escaped lines. Split out from renderMarkdown so blockquotes
 * can recurse into their own content without escaping it a second time.
 */
function renderBlocks(lines) {
  const out = []
  // One entry per open list level: nesting is driven by leading indentation.
  const stack = []

  const closeList = () => {
    const top = stack.pop()
    if (top.openLi) out.push('</li>')
    out.push(`</${top.tag}>`)
  }
  const closeListsDeeperThan = (indent) => {
    while (stack.length && stack[stack.length - 1].indent > indent) closeList()
  }
  const closeAllLists = () => {
    while (stack.length) closeList()
  }

  let index = 0
  while (index < lines.length) {
    const line = lines[index]

    // Fenced code block.
    const fence = line.match(/^\s*```(\w*)\s*$/)
    if (fence) {
      closeAllLists()
      const lang = fence[1] || ''
      const buffer = []
      index += 1
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        buffer.push(lines[index])
        index += 1
      }
      index += 1 // consume the closing fence (or run off the end)
      out.push(
        `<pre class="md-code"${lang ? ` data-lang="${lang}"` : ''}><code>${buffer.join('\n')}</code></pre>`
      )
      continue
    }

    // Blockquote: gather the run of quoted lines, strip the marker, recurse.
    if (/^\s*&gt;/.test(line)) {
      closeAllLists()
      const quoted = []
      while (index < lines.length && /^\s*&gt;/.test(lines[index])) {
        quoted.push(lines[index].replace(/^\s*&gt;\s?/, ''))
        index += 1
      }
      out.push(`<blockquote>${renderBlocks(quoted)}</blockquote>`)
      continue
    }

    // Table: a row followed by a rule row.
    if (
      isTableRow(line) &&
      index + 1 < lines.length &&
      isTableRule(lines[index + 1]) &&
      lines[index + 1].includes('|')
    ) {
      closeAllLists()
      const header = line
      const rule = lines[index + 1]
      index += 2
      const body = []
      while (index < lines.length && isTableRow(lines[index])) {
        body.push(lines[index])
        index += 1
      }
      out.push(renderTable(header, rule, body))
      continue
    }

    // Blank line ends any open list.
    if (!line.trim()) {
      closeAllLists()
      index += 1
      continue
    }

    // Horizontal rule.
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      closeAllLists()
      out.push('<hr />')
      index += 1
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      closeAllLists()
      const level = Math.min(heading[1].length + 2, 6)
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    const bullet = line.match(/^([ \t]*)[-*+]\s+(.*)$/)
    const numbered = line.match(/^([ \t]*)\d+[.)]\s+(.*)$/)
    if (bullet || numbered) {
      const match = bullet || numbered
      const tag = bullet ? 'ul' : 'ol'
      const depth = indentOf(line)
      const content = match[2]

      closeListsDeeperThan(depth)
      const top = stack[stack.length - 1]
      if (!top || top.indent < depth) {
        // Deeper than anything open: nest inside the enclosing <li>, which is
        // deliberately left open so the markup stays valid.
        stack.push({ tag, indent: depth, openLi: false })
        out.push(`<${tag}>`)
      } else if (top.tag !== tag) {
        // Same level, different kind of list.
        closeList()
        stack.push({ tag, indent: depth, openLi: false })
        out.push(`<${tag}>`)
      }

      const current = stack[stack.length - 1]
      if (current.openLi) out.push('</li>')
      out.push(`<li>${inline(content)}`)
      current.openLi = true
      index += 1
      continue
    }

    closeAllLists()
    out.push(`<p>${inline(line)}</p>`)
    index += 1
  }

  closeAllLists()
  return out.join('\n')
}

export function renderMarkdown(source) {
  return renderBlocks(escapeHtml(source).split('\n'))
}
