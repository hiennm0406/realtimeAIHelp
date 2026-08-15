<template>
  <div class="tool" :class="`tool--${item.status}`">
    <button class="tool__head" type="button" @click="open = !open">
      <span class="tool__badge">{{ statusIcon }}</span>
      <span class="tool__name">{{ item.name }}</span>
      <span v-if="summary" class="tool__summary">{{ summary }}</span>
      <span class="tool__chevron">{{ open ? '▾' : '▸' }}</span>
    </button>

    <div v-if="open" class="tool__body">
      <template v-if="showIo">
        <div class="tool__label">Input</div>
        <pre class="tool__pre">{{ inputText }}</pre>

        <div v-if="item.status !== 'running'" class="tool__label">Result</div>
        <pre v-if="item.status !== 'running'" class="tool__pre">{{ resultText }}</pre>
        <p v-else class="tool__pending">Running…</p>
      </template>
      <p v-else class="tool__pending">
        Tool input and output are hidden. Enable them in Settings.
      </p>
    </div>
  </div>
</template>

<script>
import { describeToolInput, stringifyToolContent } from '../../lib/format.js'

const MAX_PREVIEW = 20000

export default {
  props: {
    item: { type: Object, required: true },
    showIo: { type: Boolean, default: true },
  },
  data() {
    return { open: false }
  },
  computed: {
    statusIcon() {
      if (this.item.status === 'running') return '●'
      return this.item.status === 'error' ? '✕' : '✓'
    },
    summary() {
      return describeToolInput(this.item.input)
    },
    inputText() {
      if (this.item.input == null) return '(pending)'
      return JSON.stringify(this.item.input, null, 2)
    },
    resultText() {
      const text = stringifyToolContent(this.item.result)
      if (!text) return '(no output)'
      return text.length > MAX_PREVIEW
        ? `${text.slice(0, MAX_PREVIEW)}\n\n… truncated (${text.length.toLocaleString()} characters total)`
        : text
    },
  },
}
</script>

<style scoped>
.tool {
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel-2) 70%, transparent);
  border-radius: 10px;
  margin: 8px 0;
  overflow: hidden;
}

.tool__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: none;
  border: 0;
  color: var(--text-soft);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  text-align: left;
}

.tool__badge {
  flex: none;
  font-size: 11px;
  color: var(--muted);
}

.tool--ok .tool__badge {
  color: var(--good);
}

.tool--error .tool__badge {
  color: var(--bad);
}

.tool--running .tool__badge {
  color: var(--warn);
  animation: tool-pulse 1.1s ease-in-out infinite;
}

@keyframes tool-pulse {
  0%,
  100% {
    opacity: 0.3;
  }
  50% {
    opacity: 1;
  }
}

.tool__name {
  font-weight: 600;
  flex: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.tool__summary {
  flex: 1;
  min-width: 0;
  color: var(--muted);
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.tool__chevron {
  flex: none;
  font-size: 11px;
  opacity: 0.7;
}

.tool__body {
  padding: 4px 12px 12px;
  border-top: 1px solid var(--border);
}

.tool__label {
  margin: 10px 0 5px;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}

.tool__pre {
  margin: 0;
  padding: 9px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  max-height: 420px;
  overflow-y: auto;
}

.tool__pending {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--muted);
}
</style>
