<template>
  <div class="workspace" :class="{ 'workspace--collapsed': !sidebarOpen }">
    <div
      v-if="sidebarOpen"
      class="sidebar__scrim"
      @click="toggleSidebar"
    ></div>

    <aside v-if="sidebarOpen" class="sidebar card">
      <div class="sidebar__head">
        <b>Chats<span v-if="history.length"> · {{ history.length }}</span></b>
        <div class="sidebar__headtools">
          <button class="btn" type="button" :disabled="running" @click="startNewChat">
            New
          </button>
          <button
            class="sidebar__collapse"
            type="button"
            title="Hide chat history"
            @click="toggleSidebar"
          >
            ‹
          </button>
        </div>
      </div>

      <p v-if="!history.length" class="sidebar__empty">
        No saved chats yet.
      </p>

      <ul v-else class="sidebar__list">
        <li
          v-for="entry in history"
          :key="entry.id"
          class="sidebar__item"
          :class="{ 'sidebar__item--active': entry.id === conversationId }"
        >
          <button
            class="sidebar__open"
            type="button"
            :disabled="running"
            :title="entry.title"
            @click="openChat(entry.id)"
          >
            <span class="sidebar__title">{{ entry.title }}</span>
            <span class="sidebar__meta">
              {{ entry.messages }} msg
              <template v-if="entry.cost"> · {{ formatCost(entry.cost) }}</template>
              · {{ formatWhen(entry.updatedAt) }}
            </span>
          </button>
          <button
            class="sidebar__del"
            type="button"
            title="Delete this chat"
            @click="removeChat(entry.id)"
          >
            ✕
          </button>
        </li>
      </ul>
    </aside>

    <div class="chat">
      <header class="chat__bar card">
        <div class="chat__id">
          <button
            v-if="!sidebarOpen"
            class="sidebar__collapse chat__reveal"
            type="button"
            title="Show chat history"
            @click="toggleSidebar"
          >
            ☰
          </button>
          <b class="chat__brand">Trợ lý của Lan Hương, phục vụ mọi nơi</b>
          <span v-if="convo.model" class="chat__pill">{{ convo.model }}</span>
          <span v-if="convo.permissionMode" class="chat__pill">{{ convo.permissionMode }}</span>
          <span v-if="convo.sessionId" class="chat__pill" :title="convo.sessionId">
            session {{ convo.sessionId.slice(0, 8) }}
          </span>
        </div>

        <div class="chat__bartools">
          <button
            v-if="configured"
            class="chat__ctx"
            type="button"
            :class="ctxClass"
            :disabled="running"
            :title="
              convo.context
                ? `${formatTokens(convo.context.used)} of ${formatTokens(convo.context.window)} context tokens used — click to run /context`
                : 'Run /context'
            "
            @click="sendCommand('/context')"
          >
            {{ convo.context ? `${convo.context.percentLeft.toFixed(0)}% context` : '/context' }}
          </button>
          <span v-if="convo.totals.cost" class="chat__total" title="Total cost this conversation">
            {{ formatCost(convo.totals.cost) }}
          </span>
          <button class="btn" type="button" @click="showRules = !showRules">
            Rule
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

    <RulesDrawer
      v-if="showRules"
      :settings="settings"
      @close="showRules = false"
    />

    <div v-if="!configured" class="chat__setup card">
      <b>Paste your access token first.</b>
      <p>
        Start <code>bridge/server.py</code> on the machine that has Claude Code, copy the
        token it prints, then open Settings above. The bridge address is already set.
      </p>
      <button class="btn" type="button" @click="showSettings = true">Open settings</button>
    </div>

    <div ref="scroller" class="chat__log">
      <div v-if="!convo.timeline.length" class="chat__empty">
        Ask anything. Claude runs on your machine with its full toolset, so it can read
        and edit files, run commands, and search the web.
      </div>

      <template v-for="item in convo.timeline" :key="item.id">
        <div v-if="item.kind === 'user'" class="turn turn--user" :data-turn-id="item.id">
          <div class="bubble">{{ item.text }}</div>
        </div>

        <div v-else-if="item.kind === 'text'" class="turn turn--claude" :data-turn-id="item.id">
          <MarkdownText :text="item.text" :done="item.done" />
        </div>

        <div
          v-else-if="item.kind === 'thinking' && settings.showThinking && (!item.done || item.text)"
          class="turn turn--claude"
          :data-turn-id="item.id"
        >
          <ThinkingBlock :item="item" />
        </div>

        <div v-else-if="item.kind === 'tool'" class="turn turn--claude" :data-turn-id="item.id">
          <ToolBlock :item="item" :show-io="settings.showToolIO" />
        </div>

        <div v-else-if="item.kind === 'result'" class="turn turn--claude" :data-turn-id="item.id">
          <ResultCard :item="item" />
        </div>

        <div v-else-if="item.kind === 'notice'" class="turn turn--claude" :data-turn-id="item.id">
          <pre class="notice">{{ item.text }}</pre>
        </div>

        <div v-else-if="item.kind === 'error'" class="turn turn--claude" :data-turn-id="item.id">
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

    <button
      v-if="showJumpUp"
      class="chat__jumpup"
      type="button"
      title="Về đầu câu trả lời"
      aria-label="Về đầu câu trả lời"
      @click="scrollToAnswerStart"
    >
      ↑
    </button>

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
        @focus="onInputFocus"
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
  </div>
</template>

<script>
import { reactive } from 'vue'
import MarkdownText from './MarkdownText.vue'
import ResultCard from './ResultCard.vue'
import RulesDrawer from './RulesDrawer.vue'
import SettingsDrawer from './SettingsDrawer.vue'
import ThinkingBlock from './ThinkingBlock.vue'
import ToolBlock from './ToolBlock.vue'
import {
  BRIDGE_URL,
  abortRun,
  clearActiveRun,
  fetchRunSnapshot,
  getActiveRun,
  loadSettings,
  newRunId,
  saveSettings,
  setActiveRun,
  streamChat,
} from '../../lib/bridge.js'
import {
  addLocalError,
  addUserMessage,
  applyClaudeEvent,
  createConversation,
  restoreConversation,
} from '../../lib/conversation.js'
import {
  deleteConversation,
  listConversations,
  loadConversation,
  newConversationId,
  saveConversation,
} from '../../lib/history.js'
import { formatCost, formatTokens } from '../../lib/format.js'

const STATUS_LABELS = {
  starting: 'Starting…',
  reconnecting: 'Resuming…',
  offline: 'Connection lost — the run continues on the bridge, retrying…',
  requesting: 'Contacting the API…',
  thinking: 'Thinking…',
  responding: 'Responding…',
}

// How long a reconnect keeps retrying through a network outage before it gives
// up and shows an error. The run itself is unaffected either way - it lives on
// the bridge - so this only decides how long the UI waits before saying so.
const RETRY_WINDOW_MS = 5 * 60 * 1000

const isMobile = () => window.matchMedia('(max-width: 640px)').matches

export default {
  components: { MarkdownText, ResultCard, RulesDrawer, SettingsDrawer, ThinkingBlock, ToolBlock },
  data() {
    return {
      settings: reactive(loadSettings()),
      convo: reactive(createConversation()),
      conversationId: newConversationId(),
      history: [],
      draft: '',
      running: false,
      runId: '',
      controller: null,
      showSettings: false,
      showRules: false,
      // Whether to show the little "jump to the start of this answer" arrow.
      showJumpUp: false,
      // On phones the history panel is an overlay, so start it closed to keep
      // the chat in full view; on desktop honor the saved preference.
      sidebarOpen: isMobile()
        ? false
        : localStorage.getItem('sidebarOpen') !== '0',
    }
  },
  computed: {
    configured() {
      // The bridge address is fixed at build time, so a device is configured as
      // soon as it has a token.
      return Boolean(this.settings.token?.trim())
    },
    statusLabel() {
      return STATUS_LABELS[this.convo.status] || 'Working…'
    },
    ctxClass() {
      const left = this.convo.context?.percentLeft ?? 100
      if (left <= 15) return 'chat__ctx--bad'
      if (left <= 35) return 'chat__ctx--warn'
      return ''
    },
  },
  created() {
    // Non-reactive scratch for stream batching, kept off `data` on purpose so it
    // never triggers a re-render on its own.
    this._pending = [] // claude events awaiting a coalesced flush
    this._raf = null // pending requestAnimationFrame id
    this._pinned = true // is the view following the bottom of the log?
    this._lastRx = 0 // performance.now() of the last stream chunk (liveness)
  },
  mounted() {
    if (!this.configured) this.showSettings = true
    this.refreshHistory()
    // Reopen the most recent chat so a reload doesn't look like data loss.
    const latest = this.history[0]
    if (latest) this.openChat(latest.id)
    // Coming back to a backgrounded tab: keep a live stream to the run, so an
    // answer that is still being written continues on screen as usual.
    this.onVisible = () => {
      if (document.visibilityState !== 'visible') return
      const active = getActiveRun(this.conversationId)
      if (!active?.runId) return
      if (!this.running) {
        // No live reader - reconnect and tail the run.
        this.maybeResume()
      } else if (performance.now() - this._lastRx > 15000) {
        // A backgrounded tab often leaves a dead socket that still looks
        // "running". If nothing (not even a keepalive) has arrived for a while,
        // drop it; runStream's finally then reconnects a fresh live stream.
        this.controller?.abort()
      }
    }
    document.addEventListener('visibilitychange', this.onVisible)

    // Signal came back (tunnel, wifi, cellular): pick the run back up straight
    // away instead of waiting for the next poll to time out.
    this.onOnline = () => {
      if (!this.running) this.maybeResume()
    }
    window.addEventListener('online', this.onOnline)

    // One persistent scroll listener drives both auto-follow and the jump arrow.
    this.$nextTick(() => {
      const el = this.$refs.scroller
      if (el) el.addEventListener('scroll', this.onLogScroll, { passive: true })
    })
  },
  beforeUnmount() {
    // Abort only the local reader. The run keeps going on the bridge so we can
    // reconnect to it when the user returns.
    this.controller?.abort()
    if (this.onVisible) document.removeEventListener('visibilitychange', this.onVisible)
    if (this.onOnline) window.removeEventListener('online', this.onOnline)
    this.$refs.scroller?.removeEventListener('scroll', this.onLogScroll)
    if (this._raf != null) cancelAnimationFrame(this._raf)
  },
  methods: {
    formatCost,
    formatTokens,

    applySettings(next) {
      Object.assign(this.settings, next)
      saveSettings({ ...this.settings })
    },

    refreshHistory() {
      this.history = listConversations()
    },

    toggleSidebar() {
      this.sidebarOpen = !this.sidebarOpen
      // Only remember the choice on desktop; the mobile overlay always
      // reopens closed so the chat stays in view.
      if (!isMobile()) {
        localStorage.setItem('sidebarOpen', this.sidebarOpen ? '1' : '0')
      }
    },

    persist() {
      saveConversation(this.conversationId, this.convo)
      this.refreshHistory()
    },

    startNewChat() {
      if (this.running) return
      this.conversationId = newConversationId()
      Object.assign(this.convo, createConversation())
      if (isMobile()) this.sidebarOpen = false
      this.scrollToEnd()
    },

    openChat(id) {
      if (this.running || id === this.conversationId) return
      const body = loadConversation(id)
      if (!body) {
        // Index entry without a body: the body was evicted for space.
        deleteConversation(id)
        this.refreshHistory()
        return
      }
      this.conversationId = id
      Object.assign(this.convo, restoreConversation(body))
      if (isMobile()) this.sidebarOpen = false
      this.scrollToEnd()
      // If this chat has a run still working in the background, reconnect to it.
      this.maybeResume()
    },

    removeChat(id) {
      deleteConversation(id)
      this.refreshHistory()
      if (id === this.conversationId) this.startNewChat()
    },

    formatWhen(ts) {
      if (!ts) return ''
      const diff = Date.now() - ts
      if (diff < 60_000) return 'just now'
      if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
      if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
      const days = Math.floor(diff / 86_400_000)
      if (days < 7) return `${days}d ago`
      return new Date(ts).toLocaleDateString()
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

    onInputFocus() {
      // The mobile keyboard shrinks the viewport a beat after focus; wait for
      // it to settle, then bring the latest messages back into view above it.
      setTimeout(() => this.scrollToEnd(), 350)
    },

    scrollToEnd() {
      this.$nextTick(() => {
        const el = this.$refs.scroller
        if (el) el.scrollTop = el.scrollHeight
        this.updateJumpUp()
      })
    },

    onLogScroll() {
      const el = this.$refs.scroller
      if (!el) return
      // Auto-follow only while the user is near the bottom, so scrolling back
      // through a long transcript isn't yanked down by new output.
      const gap = el.scrollHeight - el.scrollTop - el.clientHeight
      this._pinned = gap < 120
      this.updateJumpUp()
    },

    /** The DOM node of the first rendered block of the latest answer. */
    answerStartEl() {
      const scroller = this.$refs.scroller
      const timeline = this.convo.timeline
      if (!scroller || !timeline.length) return null
      let from = 0
      for (let i = timeline.length - 1; i >= 0; i -= 1) {
        if (timeline[i].kind === 'user') {
          from = i + 1
          break
        }
      }
      // Scan forward to the first block that actually has an element - some
      // (e.g. hidden thinking) render nothing.
      for (let i = from; i < timeline.length; i += 1) {
        const el = scroller.querySelector(`[data-turn-id="${timeline[i].id}"]`)
        if (el) return el
      }
      return null
    },

    updateJumpUp() {
      const el = this.$refs.scroller
      const startEl = this.answerStartEl()
      // Offer the jump only once the answer's first line has scrolled out of
      // view above - i.e. the answer is long and you're reading further down.
      this.showJumpUp = Boolean(el && startEl && el.scrollTop > startEl.offsetTop + 40)
    },

    scrollToAnswerStart() {
      const el = this.$refs.scroller
      const startEl = this.answerStartEl()
      if (!el || !startEl) return
      el.scrollTo({ top: Math.max(0, startEl.offsetTop - 8), behavior: 'smooth' })
    },

    /** Drain buffered stream events into the timeline in one repaint. */
    flushClaude() {
      this._raf = null
      if (!this._pending.length) return
      const batch = this._pending
      this._pending = []
      for (const data of batch) applyClaudeEvent(this.convo, data)
      this.afterStreamUpdate()
    },

    scheduleClaude() {
      if (this._raf == null) this._raf = requestAnimationFrame(this.flushClaude)
    },

    afterStreamUpdate() {
      if (this._pinned) this.scrollToEnd()
      else this.updateJumpUp()
    },

    async stop() {
      // Explicit stop really does kill the run, so drop its background marker.
      // `runId` is set before the request goes out, so this also works in the
      // window before the bridge's first frame comes back - the bridge records
      // the id as cancelled and refuses to launch it.
      const runId = this.runId
      clearActiveRun(this.conversationId)
      this.controller?.abort()
      await abortRun(this.settings, runId)
    },

    sendCommand(text) {
      if (this.running || !this.configured) return
      this.draft = text
      this.send()
    },

    /**
     * setTimeout as a promise, cancellable by an AbortSignal.
     *
     * The listener is removed on the normal path too. `{ once: true }` only
     * detaches it when the event actually fires, so a long poll loop (one sleep
     * per iteration, all sharing the run's signal) used to pile up thousands of
     * listeners on it over the life of a background run.
     */
    _sleep(ms, signal) {
      return new Promise((resolve, reject) => {
        if (signal?.aborted) {
          reject(new DOMException('Aborted', 'AbortError'))
          return
        }
        const onAbort = () => {
          clearTimeout(timer)
          reject(new DOMException('Aborted', 'AbortError'))
        }
        const timer = setTimeout(() => {
          signal?.removeEventListener('abort', onAbort)
          resolve()
        }, ms)
        signal?.addEventListener('abort', onAbort, { once: true })
      })
    },

    /** Resolves when the device reports a network again (or the run is stopped). */
    waitForOnline(signal) {
      if (navigator.onLine) return Promise.resolve()
      return new Promise((resolve) => {
        const done = () => {
          window.removeEventListener('online', done)
          signal?.removeEventListener('abort', done)
          resolve()
        }
        window.addEventListener('online', done, { once: true })
        signal?.addEventListener('abort', done, { once: true })
      })
    },

    /**
     * Reconnect to a run this conversation left working in the background.
     *
     * Uses short polling of /api/run rather than a long-lived stream: quick
     * tunnels routinely buffer or drop the streaming reconnect (the byte can
     * arrive tens of seconds late, or not at all -> "network error"), whereas a
     * plain request/response gets through. Truncates back to where the run
     * started and rebuilds the in-progress turn, then keeps catching up until
     * the run finishes.
     */
    maybeResume() {
      if (!this.configured || this.running) return
      const active = getActiveRun(this.conversationId)
      if (!active?.runId) return

      const anchor = Number.isFinite(active.anchor) ? active.anchor : this.convo.timeline.length
      if (anchor >= 0 && anchor < this.convo.timeline.length) {
        this.convo.timeline.splice(anchor)
      }
      // The run is replayed from its first frame, so anything it already
      // contributed to the running totals has to come off first - otherwise a
      // reconnect that lands after the run's `result` frame counts its cost and
      // tokens twice. `active.totals` is the snapshot taken when the run started.
      if (active.totals) Object.assign(this.convo.totals, active.totals)
      // Blocks and tools key off a live run's message ids; clear them so the
      // replay rebuilds instead of merging into stale entries.
      this.convo.blocks = {}
      this.convo.tools = {}
      this.convo.currentMessageId = ''

      this.runId = active.runId
      this.convo.status = 'reconnecting'
      this._pinned = true
      this.pollResume(active.runId, anchor)
    },

    async pollResume(runId, anchor) {
      this.running = true
      this.controller = new AbortController()
      const signal = this.controller.signal
      const conversationId = this.conversationId
      this._lastRx = performance.now()

      const dispatch = (event, data) => {
        if (event === 'claude') applyClaudeEvent(this.convo, data)
        else if (event === 'bridge') {
          // Re-arm the marker; setActiveRun keeps the original totals snapshot
          // for a run id it already knows.
          if (data.type === 'started') setActiveRun(conversationId, runId, anchor)
        } else if (event === 'notice') {
          this.convo.timeline.push({
            id: `n${Date.now()}${this.convo.timeline.length}`,
            kind: 'notice',
            text: data.text,
          })
        } else if (event === 'error') {
          addLocalError(this.convo, data.message || 'The bridge reported an error.')
        }
      }

      let offset = 0
      let failures = 0
      let failingSince = 0
      let ended = 'resolved'
      try {
        while (true) {
          let snap
          try {
            snap = await fetchRunSnapshot(this.settings, runId, offset, signal)
            failures = 0
            failingSince = 0
            if (this.convo.status === 'offline') this.convo.status = 'reconnecting'
            this._lastRx = performance.now()
          } catch (error) {
            if (error.name === 'AbortError' || error.status === 404) throw error
            // A blip in the tunnel, the mobile signal, or a laptop lid closing.
            // The run is still working on the bridge, so give up only after a
            // sustained outage rather than after a handful of quick retries -
            // a phone changing cells can easily lose a minute.
            failures += 1
            if (!failingSince) failingSince = Date.now()
            if (Date.now() - failingSince > RETRY_WINDOW_MS) throw error
            this.convo.status = 'offline'
            if (!navigator.onLine) {
              // The device's radio is off - waiting is free and burning retries
              // against it is pointless. Time spent with no network at all does
              // not count towards the give-up window either: it is not evidence
              // the bridge is unreachable, so an hour in a tunnel should still
              // reconnect on the way out rather than surface an error.
              await this.waitForOnline(signal)
              failures = 0
              failingSince = 0
              continue
            }
            // 2s, 4s, 8s, then every 15s.
            await this._sleep(Math.min(2000 * 2 ** (failures - 1), 15000), signal)
            continue
          }

          for (const [event, data] of snap.frames) dispatch(event, data)
          offset = snap.next
          this.afterStreamUpdate()

          // The bridge caps how many frames one snapshot carries, so `done` on
          // its own is not "caught up" - there may still be a backlog to pull.
          // An older bridge omits `total`, in which case there never is one.
          const total = Number.isFinite(snap.total) ? snap.total : offset
          const behind = offset < total

          if (snap.done && !behind) {
            clearActiveRun(conversationId)
            break
          }
          if (this.conversationId !== conversationId) break
          // Still catching up: ask again immediately rather than idling 1.5s
          // between pages.
          if (!behind) await this._sleep(1500, signal)
        }
      } catch (error) {
        if (error.name === 'AbortError') {
          ended = 'aborted'
          if (!getActiveRun(conversationId)) addLocalError(this.convo, 'Stopped.')
        } else if (error.status === 404) {
          ended = 'error'
          clearActiveRun(conversationId)
          this.convo.timeline.push({
            id: `n${Date.now()}${this.convo.timeline.length}`,
            kind: 'notice',
            text: 'The background run finished a while ago and its transcript is no longer available to replay.',
          })
        } else {
          ended = 'error'
          addLocalError(
            this.convo,
            `${error.message} Check that the bridge is running and reachable at ${BRIDGE_URL}.`
          )
        }
      } finally {
        this.running = false
        this.runId = ''
        this.controller = null
        this.convo.status = ''
        this.persist()
        this.afterStreamUpdate()

        // Self-heal: if we dropped a still-active run while on screen, resume.
        if (
          ended !== 'error' &&
          this.conversationId === conversationId &&
          document.visibilityState === 'visible' &&
          getActiveRun(conversationId)
        ) {
          setTimeout(() => {
            if (this.conversationId === conversationId) this.maybeResume()
          }, 800)
        }
      }
    },

    async send() {
      const prompt = this.draft.trim()
      if (!prompt || this.running || !this.configured) return

      addUserMessage(this.convo, prompt)
      this.draft = ''
      this.$nextTick(this.autosize)
      this.scrollToEnd()
      // Save immediately so the chat appears in history even if the run fails.
      this.persist()

      // Where the answer begins - what a reconnect truncates back to before it
      // replays this run - and the counters as they stood at that point.
      const anchor = this.convo.timeline.length
      const totals = { ...this.convo.totals }
      const sessionId = this.convo.sessionId
      const conversationId = this.conversationId

      // Name the run before asking for it, so Stop can abort it even while the
      // POST is still in flight.
      const runId = newRunId()
      this.runId = runId

      this.convo.status = 'starting'
      this._pinned = true
      await this.runStream({
        anchor,
        totals,
        start: ({ signal, handlers, onActivity }) =>
          streamChat({
            settings: this.settings,
            prompt,
            runId,
            sessionId,
            conversationId,
            handlers,
            signal,
            onActivity,
          }),
      })
    },

    /**
     * Shared machinery for both a fresh run and a reconnect: wire the stream's
     * events into the timeline, keep the view pinned to the bottom, and record
     * or clear the background-run marker as the run starts and finishes.
     */
    async runStream({ start, anchor = 0, totals = null }) {
      this.running = true
      this.controller = new AbortController()
      this._pending = []
      this._lastRx = performance.now()
      // How the stream ended decides whether we auto-reconnect: 'resolved' (the
      // socket closed) and 'aborted' (we dropped a stale one) are recoverable;
      // 'error' (bridge unreachable) is not, so we don't hammer it.
      let ended = 'resolved'
      const conversationId = this.conversationId

      try {
        await start({
          signal: this.controller.signal,
          onActivity: () => {
            this._lastRx = performance.now()
          },
          handlers: {
            onBridge: (data) => {
              if (data.type === 'started') {
                this.runId = data.runId
                // Remember the run so a return trip can reconnect to it.
                setActiveRun(this.conversationId, data.runId, anchor, totals)
              }
            },
            // High-frequency: buffer and apply at most once per animation frame,
            // so a fast stream doesn't trigger a render per token.
            onClaude: (data) => {
              this._pending.push(data)
              this.scheduleClaude()
            },
            onNotice: (data) => {
              this.flushClaude()
              this.convo.timeline.push({
                id: `n${Date.now()}${this.convo.timeline.length}`,
                kind: 'notice',
                text: data.text,
              })
              this.afterStreamUpdate()
            },
            onError: (data) => {
              this.flushClaude()
              addLocalError(this.convo, data.message || 'The bridge reported an error.')
              this.afterStreamUpdate()
            },
            onDone: () => {
              this.flushClaude()
              // The run is finished on the bridge; nothing left to reconnect to.
              this.convo.status = ''
              clearActiveRun(this.conversationId)
            },
          },
        })
      } catch (error) {
        if (error.name === 'AbortError') {
          ended = 'aborted'
          // Left mid-run: don't write an error, the run is still going in the
          // background and can be picked back up.
          if (!getActiveRun(this.conversationId)) addLocalError(this.convo, 'Stopped.')
        } else {
          ended = 'error'
          addLocalError(
            this.convo,
            `${error.message} Check that the bridge is running and reachable at ${BRIDGE_URL}.`
          )
        }
      } finally {
        this.flushClaude() // drain anything the last frame didn't cover
        this.running = false
        this.runId = ''
        this.controller = null
        this.convo.status = ''
        this.persist()
        this.afterStreamUpdate()

        // Self-heal: the run is still active (no 'done' cleared its marker) and
        // we're on screen, so a dropped/aborted socket means reconnect and keep
        // streaming the answer live - not sit frozen "in the background".
        if (
          ended !== 'error' &&
          this.conversationId === conversationId &&
          document.visibilityState === 'visible' &&
          getActiveRun(conversationId)
        ) {
          setTimeout(() => {
            if (this.conversationId === conversationId) this.maybeResume()
          }, 500)
        }
      }
    },
  },
}
</script>

<style scoped>
.workspace {
  display: flex;
  gap: 12px;
  height: calc(100vh - 44px);
  height: calc(var(--app-vh, 100vh) - 44px);
}

.sidebar__scrim {
  display: none;
}

.sidebar {
  flex: none;
  width: 232px;
  display: flex;
  flex-direction: column;
  padding: 12px;
  overflow: hidden;
}

.chat {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: relative;
}

.chat__jumpup {
  position: absolute;
  right: 18px;
  bottom: 82px;
  z-index: 12;
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.9;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
}

.chat__jumpup:hover {
  opacity: 1;
  background: var(--panel);
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

.chat__ctx {
  font: inherit;
  font-size: 11.5px;
  color: var(--good);
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--good) 40%, var(--border));
  border-radius: 999px;
  padding: 2px 9px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}

.chat__ctx:hover:not(:disabled) {
  background: color-mix(in srgb, var(--good) 12%, transparent);
}

.chat__ctx:disabled {
  opacity: 0.5;
  cursor: default;
}

.chat__ctx--warn {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
}

.chat__ctx--bad {
  color: var(--bad);
  border-color: color-mix(in srgb, var(--bad) 45%, var(--border));
}

.sidebar__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.sidebar__headtools {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sidebar__collapse {
  flex: none;
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--muted);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}

.sidebar__collapse:hover {
  color: var(--text);
  background: var(--panel-2);
}

.chat__reveal {
  margin-right: 2px;
}

.sidebar__empty {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.5;
}

.sidebar__list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.sidebar__item {
  display: flex;
  align-items: stretch;
  gap: 2px;
  border-radius: 9px;
  border: 1px solid transparent;
}

.sidebar__item:hover {
  border-color: var(--border);
  background: var(--panel-2);
}

.sidebar__item--active {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.sidebar__open {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 7px 9px;
  background: none;
  border: 0;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.sidebar__open:disabled {
  cursor: default;
}

.sidebar__title {
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar__meta {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar__del {
  flex: none;
  padding: 0 8px;
  background: none;
  border: 0;
  color: var(--muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  border-radius: 9px;
}

.sidebar__del:hover {
  color: var(--bad);
  background: color-mix(in srgb, var(--bad) 12%, transparent);
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
  /* Anchor for the jump button's offsetTop math. */
  position: relative;
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
  /* Dedicated mobile layout: the chat owns the full width and height of the
     visible viewport, and the history panel slides in as an overlay. */
  .workspace {
    height: 100%;
    gap: 0;
    position: relative;
  }

  .chat {
    gap: 8px;
    height: 100%;
  }

  .chat__bar {
    padding: 8px 10px;
  }

  .chat__brand {
    font-size: 14px;
  }

  .chat__log {
    padding: 4px 0;
  }

  .bubble {
    max-width: 92%;
  }

  /* History becomes a slide-in drawer over the chat instead of a fixed column
     that steals horizontal space. */
  .sidebar {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 30;
    width: min(84%, 300px);
    padding: 12px;
    border-radius: 0 14px 14px 0;
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.55);
  }

  .sidebar__scrim {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 20;
    background: rgba(2, 6, 12, 0.5);
  }

  .chat__composer {
    padding: 8px;
  }

  .chat__jumpup {
    right: 12px;
    bottom: 72px;
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

.md blockquote {
  margin: 0 0 12px;
  padding: 2px 0 2px 12px;
  border-left: 3px solid color-mix(in srgb, var(--accent) 45%, var(--border));
  color: var(--text-soft);
}

.md hr {
  margin: 16px 0;
  border: 0;
  border-top: 1px solid var(--border);
}

.md del {
  opacity: 0.65;
}

/* Tables scroll inside their own box: a wide one must never make the whole
   chat column scroll sideways, which is what happens on a phone otherwise. */
.md .md-tablewrap {
  margin: 0 0 12px;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
}

.md table.md-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 12.5px;
}

.md table.md-table th,
.md table.md-table td {
  padding: 7px 10px;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border);
  line-height: 1.5;
}

.md table.md-table th {
  background: var(--panel-2);
  font-weight: 600;
  white-space: nowrap;
}

.md table.md-table tr:last-child td {
  border-bottom: 0;
}
</style>
