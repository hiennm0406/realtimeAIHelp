<template>
  <div class="think" :class="{ 'think--live': !item.done }">
    <button class="think__head" type="button" @click="open = !open">
      <span class="think__dot" aria-hidden="true"></span>
      <span class="think__title">{{ headline }}</span>
      <span class="think__chevron">{{ open ? '▾' : '▸' }}</span>
    </button>

    <div v-if="open" class="think__body">
      <pre v-if="item.text">{{ item.text }}</pre>
      <p v-else class="think__empty">
        Claude reasoned here, but the reasoning text was not returned.
      </p>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    item: { type: Object, required: true },
    defaultOpen: { type: Boolean, default: false },
  },
  data() {
    return { open: this.defaultOpen }
  },
  computed: {
    headline() {
      if (!this.item.done) return 'Thinking…'
      const chars = (this.item.text || '').length
      return chars ? `Thought for ${chars.toLocaleString()} characters` : 'Thought'
    },
  },
}
</script>

<style scoped>
.think {
  border: 1px solid var(--border);
  border-left: 3px solid color-mix(in srgb, var(--accent) 45%, var(--border));
  background: color-mix(in srgb, var(--panel-2) 70%, transparent);
  border-radius: 10px;
  margin: 8px 0;
  overflow: hidden;
}

.think__head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: none;
  border: 0;
  color: var(--muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  text-align: left;
}

.think__head:hover {
  color: var(--text-soft);
}

.think__title {
  flex: 1;
}

.think__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  flex: none;
}

.think--live .think__dot {
  animation: think-pulse 1.1s ease-in-out infinite;
}

@keyframes think-pulse {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

.think__chevron {
  font-size: 11px;
  opacity: 0.7;
}

.think__body {
  padding: 0 12px 10px;
  border-top: 1px solid var(--border);
}

.think__body pre {
  margin: 10px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-soft);
}

.think__empty {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--muted);
}
</style>
