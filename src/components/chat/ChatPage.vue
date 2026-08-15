<template>
  <div class="chat">
    <header class="chat__bar card">
      <div class="chat__id">
        <b>Claude Code</b>
        <span v-if="convo.model" class="chat__pill">{{ convo.model }}</span>
        <span v-if="convo.permissionMode" class="chat__pill">{{ convo.permissionMode }}</span>
        <span v-if="convo.sessionId" class="chat__pill" :title="convo.sessionId">
          session {{ convo.sessionId.slice(0, 8) }}
        </span>
      </div>

      <div class="chat__bartools">
        <span v-if="convo.totals.cost" class="chat__total" title="Total cost this conversation">
          {{ formatCost(convo.totals.cost) }}
        </span>
        <button class="btn" type="button" :disabled="running" @click="newConversation">
          New
        </button>
        <button class="btn" type="button" @click="showSettings = !showSettings">
          Settings
        </button>
      </div>
    </header>

    <SettingsDrawer
      v-if="showSettings"
      :settings="settings"
      @close="showSettings = false"
      @update="applySettings"
    />

    <div v-if="!configured" class="chat__setup card">
      <b>Set the bridge URL and token first.</b>
      <p>
        Start <code>bridge/server.py</code> on the machine that has Claude Code, copy the
        token it prints, then open Settings above.
      </p>
      <button class="btn" type="button" @click="showSettings = true">Open settings</button>
    </div>

    <div ref="scroller" class="chat__log">
      <div v-if="!convo.timeline.length" class="chat__empty">
        Ask anything. Claude runs on your machine with its full toolset, so it can read
        and edit files, run commands, and search the web.
      </div>

      <template v-for="item in convo.timeline" :key="item.id">
        <div v-if="item.kind === 'user'" class="turn turn--user">
          <div class="bubble">{{ item.text }}</div>
        </div>

        <div v-else-if="item.kind === 'text'" class="turn turn--claude">
          <div class="md" v-html="renderMarkdown(item.text)"></div>
        </div>

        <div v-else-if="item.kind === 'thinking'" class="turn turn--claude">
          <ThinkingBlock v-if="settings.showThinking" :item="item" />
        </div>

        <div v-else-if="item.kind === 'tool'" class="turn turn--claude">
          <ToolBlock :item="item" :show-io="settings.showToolIO" />
        </div>

        <div v-else-if="item.kind === 'result'" class="turn turn--claude">
          <ResultCard :item="item" />
        </div>

        <div v-else-if="item.kind === 'notice'" class="turn turn--claude">
          <pre class="notice">{{ item.text }}</pre>
        </div>

        <div v-else-if="item.kind === 'error'" class="turn turn--claude">
          <div class="errbox">{{ item.text }}</div>
        </div>
      </template>

      <div v-if="running" class="turn turn--claude">
        <div class="status">
          <span class="status__dot"></span>
          {{ statusLabel }}
        </div>
      </div>
    </div>

    <form class="chat__composer card" @submit.prevent="send">
      <textarea
        ref="input"
        v-model="draft"
        class="chat__input"
        rows="1"
        placeholder="Message Claude Code…  (Enter to send, Shift+Enter for a new line)"
        :disabled="!configured"
        @keydown="onKeydown"
        @input="autosize"
      ></textarea>

      <button
        v-if="running"
        class="btn chat__stop"
        type="button"
        @click="stop"
      >
        Stop
      </button>
      <button
        v-else
        class="btn chat__send"
        type="submit"
        :disabled="!configured || !draft.trim()"
      >
        Send
      </button>
    </form>
  </div>
</template>

<script>
import { reactive } from 'vue'
import ResultCard from './ResultCard.vue'
import SettingsDrawer from './SettingsDrawer.vue'
import ThinkingBlock from './ThinkingBlock.vue'
import ToolBlock from './ToolBlock.vue'
import { abortRun, loadSettings, saveSettings, streamChat } from '../../lib/bridge.js'
import {
  addLocalError,
  addUserMessage,
  applyClaudeEvent,
  createConversation,
} from '../../lib/conversation.js'
import { formatCost } from '../../lib/format.js'
import { renderMarkdown } from '../../lib/markdown.js'

const STATUS_LABELS = {
  starting: 'Starting…',
  requesting: 'Contacting the API…',
  thinking: 'Thinking…',
  responding: 'Responding…',
}

export default {
  components: { ResultCard, SettingsDrawer, ThinkingBlock, ToolBlock },
  data() {
    return {
      settings: reactive(loadSettings()),
      convo: reactive(createConversation()),
      draft: '',
      running: false,
      runId: '',
      controller: null,
      showSettings: false,
    }
  },
  computed: {
    configured() {
      return Boolean(this.settings.url?.trim() && this.settings.token?.trim())
    },
    statusLabel() {
      return STATUS_LABELS[this.convo.status] || 'Working…'
    },
  },
  mounted() {
    if (!this.configured) this.showSettings = true
  },
  beforeUnmount() {
    this.controller?.abort()
  },
  methods: {
    formatCost,
    renderMarkdown,

    applySettings(next) {
      Object.assign(this.settings, next)
      saveSettings({ ...this.settings })
    },

    newConversation() {
      Object.assign(this.convo, createConversation())
    },

    onKeydown(event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        this.send()
      }
    },

    autosize() {
      const el = this.$refs.input
      if (!el) return
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, 220)}px`
    },

    scrollToEnd() {
      this.$nextTick(() => {
        const el = this.$refs.scroller
        if (el) el.scrollTop = el.scrollHeight
      })
    },

    async stop() {
      await abortRun(this.settings, this.runId)
      this.controller?.abort()
    },

    async send() {
      const prompt = this.draft.trim()
      if (!prompt || this.running || !this.configured) return

      addUserMessage(this.convo, prompt)
      this.draft = ''
      this.$nextTick(this.autosize)
      this.scrollToEnd()

      this.running = true
      this.convo.status = 'starting'
      this.controller = new AbortController()

      // Only auto-scroll while the user is already near the bottom, so reading
      // back through a long transcript isn't interrupted by new output.
      let pinned = true
      const scroller = this.$refs.scroller
      const onScroll = () => {
        if (!scroller) return
        const gap = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
        pinned = gap < 120
      }
      scroller?.addEventListener('scroll', onScroll, { passive: true })

      const nudge = () => {
        if (pinned) this.scrollToEnd()
      }

      try {
        await streamChat({
          settings: this.settings,
          prompt,
          sessionId: this.convo.sessionId,
          signal: this.controller.signal,
          handlers: {
            onBridge: (data) => {
              if (data.type === 'started') this.runId = data.runId
            },
            onClaude: (data) => {
              applyClaudeEvent(this.convo, data)
              nudge()
            },
            onNotice: (data) => {
              this.convo.timeline.push({
                id: `n${Date.now()}${this.convo.timeline.length}`,
                kind: 'notice',
                text: data.text,
              })
              nudge()
            },
            onError: (data) => {
              addLocalError(this.convo, data.message || 'The bridge reported an error.')
              nudge()
            },
            onDone: () => {
              this.convo.status = ''
            },
          },
        })
      } catch (error) {
        if (error.name === 'AbortError') {
          addLocalError(this.convo, 'Stopped.')
        } else {
          addLocalError(
            this.convo,
            `${error.message} Check that the bridge is running and reachable at ${this.settings.url}.`
          )
        }
      } finally {
        scroller?.removeEventListener('scroll', onScroll)
        this.running = false
        this.runId = ''
        this.controller = null
        this.convo.status = ''
        nudge()
      }
    },
  },
}
</script>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 100px);
  max-width: 960px;
  margin: 0 auto;
}

.chat__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  flex-wrap: wrap;
}

.chat__id {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.chat__pill {
  font-size: 11.5px;
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 9px;
  white-space: nowrap;
}

.chat__bartools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat__total {
  font-size: 12.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.chat__setup {
  padding: 14px;
}

.chat__setup p {
  margin: 6px 0 10px;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.55;
}

.chat__log {
  flex: 1;
  overflow-y: auto;
  padding: 4px 2px;
}

.chat__empty {
  color: var(--muted);
  font-size: 13.5px;
  line-height: 1.6;
  padding: 28px 6px;
  max-width: 62ch;
}

.turn {
  margin-bottom: 6px;
}

.turn--user {
  display: flex;
  justify-content: flex-end;
  margin: 16px 0 10px;
}

.bubble {
  background: color-mix(in srgb, var(--accent) 18%, var(--panel));
  border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border));
  border-radius: 14px 14px 4px 14px;
  padding: 9px 13px;
  max-width: 78%;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
}

.notice {
  margin: 6px 0;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-2);
  color: var(--muted);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.errbox {
  margin: 8px 0;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--bad) 45%, var(--border));
  border-radius: 10px;
  background: color-mix(in srgb, var(--bad) 10%, transparent);
  color: var(--bad);
  font-size: 13px;
  line-height: 1.5;
}

.status {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 13px;
  padding: 6px 0;
}

.status__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: status-pulse 1.1s ease-in-out infinite;
}

@keyframes status-pulse {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

.chat__composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px;
}

.chat__input {
  flex: 1;
  resize: none;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  line-height: 1.55;
  padding: 6px 4px;
  outline: none;
  max-height: 220px;
}

.chat__input::placeholder {
  color: var(--muted);
}

.chat__send,
.chat__stop {
  flex: none;
}

.chat__send:disabled {
  opacity: 0.45;
  cursor: default;
}

@media (max-width: 640px) {
  .chat {
    height: calc(100vh - 132px);
  }

  .bubble {
    max-width: 92%;
  }
}
</style>

<style>
/* Not scoped: these style the markdown that v-html injects. */
.md {
  line-height: 1.62;
  word-break: break-word;
}

.md > *:first-child {
  margin-top: 0;
}

.md > *:last-child {
  margin-bottom: 0;
}

.md p {
  margin: 0 0 10px;
}

.md h3,
.md h4,
.md h5,
.md h6 {
  margin: 18px 0 8px;
  line-height: 1.35;
}

.md ul,
.md ol {
  margin: 0 0 10px;
  padding-left: 22px;
}

.md li {
  margin: 3px 0;
}

.md code {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 1px 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
}

.md pre.md-code {
  margin: 0 0 12px;
  padding: 11px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow-x: auto;
}

.md pre.md-code code {
  background: none;
  border: 0;
  padding: 0;
  font-size: 12.5px;
  line-height: 1.55;
}
</style>
