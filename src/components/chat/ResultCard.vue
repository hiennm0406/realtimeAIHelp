<template>
  <div class="res" :class="{ 'res--error': item.isError }">
    <p v-if="item.isError" class="res__error">{{ item.text || 'Run failed.' }}</p>

    <div class="res__stats">
      <span v-for="stat in stats" :key="stat.label" class="res__stat" :title="stat.title">
        <b>{{ stat.value }}</b>
        {{ stat.label }}
      </span>
    </div>

    <p v-if="item.permissionDenials && item.permissionDenials.length" class="res__denials">
      {{ item.permissionDenials.length }} tool call(s) were denied by the permission mode.
    </p>
  </div>
</template>

<script>
import { formatCost, formatDuration, formatTokens } from '../../lib/format.js'

export default {
  props: {
    item: { type: Object, required: true },
  },
  computed: {
    stats() {
      const usage = this.item.usage || {}
      const list = [
        {
          label: 'in',
          value: formatTokens(usage.totalInput),
          title: `${usage.input || 0} fresh + ${usage.cacheRead || 0} cache read + ${usage.cacheWrite || 0} cache write`,
        },
        { label: 'out', value: formatTokens(usage.output), title: 'Output tokens' },
      ]

      if (usage.thinking) {
        list.push({
          label: 'thinking',
          value: formatTokens(usage.thinking),
          title: 'Thinking tokens (billed as output)',
        })
      }
      if (usage.cacheRead) {
        list.push({
          label: 'cached',
          value: formatTokens(usage.cacheRead),
          title: 'Input tokens served from the prompt cache at ~10% of the input price',
        })
      }
      if (usage.webSearches) {
        list.push({
          label: 'searches',
          value: String(usage.webSearches),
          title: 'Web search requests',
        })
      }
      if (usage.webFetches) {
        list.push({
          label: 'fetches',
          value: String(usage.webFetches),
          title: 'Web fetch requests',
        })
      }

      list.push({
        label: 'cost',
        value: formatCost(this.item.cost),
        title: 'Cost reported by Claude Code for this run',
      })
      list.push({
        label: '',
        value: formatDuration(this.item.durationMs),
        title: `API time ${formatDuration(this.item.apiDurationMs)}, first token after ${formatDuration(this.item.ttftMs)}`,
      })
      if (this.item.turns > 1) {
        list.push({ label: 'turns', value: String(this.item.turns), title: 'Agent turns' })
      }
      if (this.item.stopReason && this.item.stopReason !== 'end_turn') {
        list.push({ label: '', value: this.item.stopReason, title: 'Stop reason' })
      }

      return list
    },
  },
}
</script>

<style scoped>
.res {
  margin: 12px 0 4px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}

.res__error {
  margin: 0 0 8px;
  color: var(--bad);
  font-size: 13px;
}

.res__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: 12px;
  color: var(--muted);
}

.res__stat b {
  color: var(--text-soft);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.res--error .res__stats {
  opacity: 0.8;
}

.res__denials {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--warn);
}
</style>
