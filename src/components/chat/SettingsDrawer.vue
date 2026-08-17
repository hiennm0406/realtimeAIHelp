<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="drawer card" role="dialog" aria-modal="true">
    <div class="drawer__head">
      <b>Bridge settings</b>
      <button class="btn" type="button" @click="$emit('close')">Close</button>
    </div>

    <p class="drawer__hint">
      Paste the access token <code>bridge/server.py</code> printed on startup. That is
      all a device needs — the bridge address is baked into this build.
    </p>

    <div class="drawer__fixed">
      <span class="drawer__fixedlabel">Bridge</span>
      <code class="drawer__fixedurl">{{ bridgeUrl }}</code>
    </div>

    <label class="drawer__label" for="bridge-token">Access token</label>
    <input
      id="bridge-token"
      class="input"
      type="password"
      :value="form.token"
      placeholder="printed by bridge/server.py on startup"
      autocomplete="off"
      spellcheck="false"
      @input="update('token', $event.target.value)"
    />

    <div class="drawer__grid">
      <div>
        <label class="drawer__label" for="bridge-model">Model</label>
        <select
          id="bridge-model"
          class="input"
          :value="form.model"
          @change="update('model', $event.target.value)"
        >
          <option value="">Claude Code default</option>
          <option value="opus">Opus</option>
          <option value="sonnet">Sonnet</option>
          <option value="haiku">Haiku</option>
        </select>
      </div>

      <div>
        <label class="drawer__label" for="bridge-effort">Effort</label>
        <select
          id="bridge-effort"
          class="input"
          :value="form.effort"
          @change="update('effort', $event.target.value)"
        >
          <option value="">Default</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="xhigh">xhigh</option>
          <option value="max">max</option>
        </select>
      </div>
    </div>

    <label class="drawer__label" for="bridge-perm">Permission mode</label>
    <select
      id="bridge-perm"
      class="input"
      :value="form.permissionMode"
      @change="update('permissionMode', $event.target.value)"
    >
      <option value="">Bridge default</option>
      <option value="bypassPermissions">bypassPermissions — run everything, no prompts</option>
      <option value="acceptEdits">acceptEdits — auto-approve file edits</option>
      <option value="plan">plan — read only, no changes</option>
      <option value="dontAsk">dontAsk</option>
    </select>

    <div class="drawer__checks">
      <label>
        <input
          type="checkbox"
          :checked="form.showThinking"
          @change="update('showThinking', $event.target.checked)"
        />
        Show thinking blocks
      </label>
      <label>
        <input
          type="checkbox"
          :checked="form.showToolIO"
          @change="update('showToolIO', $event.target.checked)"
        />
        Show tool input and output
      </label>
    </div>

    <div class="drawer__actions">
      <button class="btn" type="button" :disabled="testing" @click="test">
        {{ testing ? 'Testing…' : 'Test connection' }}
      </button>
    </div>

    <p v-if="testError" class="drawer__bad">{{ testError }}</p>
    <div v-else-if="health" class="drawer__ok">
      <div>Connected. Claude Code {{ health.claudeFound ? 'found' : 'NOT found' }}.</div>
      <div class="drawer__meta">
        working dir <code>{{ health.cwd }}</code>
      </div>
      <div class="drawer__meta">
        permissions <code>{{ health.defaultPermissionMode }}</code> · model
        <code>{{ health.defaultModel }}</code>
      </div>
    </div>
    </div>
  </div>
</template>

<script>
import { BRIDGE_URL, checkHealth } from '../../lib/bridge.js'

export default {
  props: {
    settings: { type: Object, required: true },
  },
  emits: ['close', 'update'],
  data() {
    return {
      form: { ...this.settings },
      bridgeUrl: BRIDGE_URL,
      testing: false,
      testError: '',
      health: null,
    }
  },
  methods: {
    update(key, value) {
      this.form[key] = value
      this.$emit('update', { ...this.form })
    },
    async test() {
      this.testing = true
      this.testError = ''
      this.health = null
      try {
        this.health = await checkHealth(this.form)
      } catch (error) {
        this.testError =
          `${error.message} ` +
          'If the token looks right, check that the bridge is running, that its ' +
          'tunnel is up, and that its allowed_origins includes this site.'
      } finally {
        this.testing = false
      }
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
  margin-bottom: 10px;
}

.drawer__hint {
  margin: 0 0 12px;
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.5;
}

.drawer__label {
  display: block;
  margin: 12px 0 6px;
  font-size: 12px;
  color: var(--muted);
}

/* The bridge address is a build-time constant, so it is shown for reference
   rather than offered as a field. */
.drawer__fixed {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel-2);
}

.drawer__fixedlabel {
  flex: none;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}

.drawer__fixedurl {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 11.5px;
  color: var(--text-soft);
}

.drawer__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.drawer__checks {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin-top: 14px;
  font-size: 13px;
  color: var(--text-soft);
}

.drawer__checks label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.drawer__actions {
  margin-top: 14px;
}

.drawer__bad {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--bad);
  line-height: 1.5;
}

.drawer__ok {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--good);
}

.drawer__meta {
  color: var(--muted);
  margin-top: 3px;
}

code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
</style>
