<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="drawer card" role="dialog" aria-modal="true">
      <div class="drawer__head">
        <b>Bridge API</b>
        <div class="drawer__headtools">
          <button class="btn" type="button" :disabled="loading" @click="refresh">
            {{ loading ? 'Loading…' : 'Refresh' }}
          </button>
          <button class="btn" type="button" @click="$emit('close')">Close</button>
        </div>
      </div>

      <p class="drawer__hint">
        Endpoints exposed by <code>bridge/server.py</code>, and the runs it is holding
        right now. All routes need <code>Authorization: Bearer &lt;token&gt;</code>.
      </p>

      <section class="rules__block">
        <div class="rules__blockhead">Endpoints</div>
        <ul class="rules__eplist">
          <li v-for="ep in endpoints" :key="ep.path" class="rules__ep">
            <span class="rules__method" :class="`rules__method--${ep.method.toLowerCase()}`">
              {{ ep.method }}
            </span>
            <code class="rules__path">{{ ep.path }}</code>
            <span class="rules__desc">{{ ep.desc }}</span>
          </li>
        </ul>
      </section>

      <section class="rules__block">
        <div class="rules__blockhead">
          Runs
          <span v-if="runs.length" class="rules__count">{{ runs.length }}</span>
        </div>

        <p v-if="error" class="drawer__bad">{{ error }}</p>
        <p v-else-if="!loading && !runs.length" class="rules__empty">
          No runs on the bridge right now.
        </p>

        <ul v-else class="rules__runs">
          <li v-for="run in runs" :key="run.runId" class="rules__run">
            <div class="rules__runtop">
              <span class="rules__badge" :class="`rules__badge--${run.status}`">
                {{ run.done ? run.status : 'running' }}
              </span>
              <code class="rules__runid" :title="run.runId">{{ run.runId.slice(0, 8) }}</code>
              <span class="rules__runwhen">{{ formatWhen(run.startedAt) }}</span>
            </div>
            <div class="rules__runprompt">{{ run.prompt || '(no prompt)' }}</div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script>
import { listRuns } from '../../lib/bridge.js'

const ENDPOINTS = [
  { method: 'GET', path: '/api/health', desc: 'Bridge status, Claude path, active run count.' },
  { method: 'GET', path: '/api/runs', desc: 'Runs still held: running + recently finished.' },
  { method: 'POST', path: '/api/chat', desc: 'Start a run and stream it (keeps going if you leave).' },
  { method: 'GET', path: '/api/stream', desc: 'Reconnect to a run by runId and replay it.' },
  { method: 'POST', path: '/api/abort', desc: 'Kill a run and its child processes.' },
]

export default {
  props: {
    settings: { type: Object, required: true },
  },
  emits: ['close'],
  data() {
    return {
      endpoints: ENDPOINTS,
      runs: [],
      loading: false,
      error: '',
    }
  },
  mounted() {
    this.refresh()
  },
  methods: {
    async refresh() {
      this.loading = true
      this.error = ''
      try {
        this.runs = await listRuns(this.settings)
      } catch (error) {
        this.error = `${error.message} Check that the bridge is running and reachable.`
      } finally {
        this.loading = false
      }
    },
    formatWhen(ts) {
      if (!ts) return ''
      const diff = Date.now() - ts
      if (diff < 60_000) return 'just now'
      if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
      if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
      return new Date(ts).toLocaleString()
    },
  },
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 24px 16px;
  overflow-y: auto;
}

.drawer {
  width: 100%;
  max-width: 480px;
  margin: auto;
  padding: 16px;
}

.drawer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.drawer__headtools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.drawer__hint {
  margin: 0 0 12px;
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.5;
}

.drawer__bad {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--bad);
  line-height: 1.5;
}

.rules__block {
  margin-top: 14px;
}

.rules__blockhead {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}

.rules__count {
  font-size: 11px;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0 7px;
  letter-spacing: 0;
}

.rules__eplist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rules__ep {
  display: grid;
  grid-template-columns: 46px auto;
  align-items: baseline;
  gap: 4px 8px;
}

.rules__method {
  grid-row: span 2;
  font-size: 10.5px;
  font-weight: 600;
  text-align: center;
  border-radius: 6px;
  padding: 2px 0;
  border: 1px solid var(--border);
  color: var(--muted);
}

.rules__method--get {
  color: var(--good);
  border-color: color-mix(in srgb, var(--good) 40%, var(--border));
}

.rules__method--post {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
}

.rules__path {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  color: var(--text);
}

.rules__desc {
  grid-column: 2;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.45;
}

.rules__empty {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
}

.rules__runs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rules__run {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 10px;
  background: var(--panel-2);
}

.rules__runtop {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rules__badge {
  font-size: 10.5px;
  font-weight: 600;
  border-radius: 999px;
  padding: 1px 8px;
  border: 1px solid var(--border);
  color: var(--muted);
}

.rules__badge--running {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
}

.rules__badge--done {
  color: var(--good);
  border-color: color-mix(in srgb, var(--good) 40%, var(--border));
}

.rules__badge--error {
  color: var(--bad);
  border-color: color-mix(in srgb, var(--bad) 45%, var(--border));
}

.rules__runid {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: var(--muted);
}

.rules__runwhen {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted);
}

.rules__runprompt {
  margin-top: 5px;
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.45;
  word-break: break-word;
}

code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
</style>
