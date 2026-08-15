<template>
  <div class="drawer card">
    <div class="drawer__head">
      <b>Bridge settings</b>
      <button class="btn" type="button" @click="$emit('close')">Close</button>
    </div>

    <p class="drawer__hint">
      Point this at the machine running <code>bridge/server.py</code>. Over the internet
      that means your tunnel URL; on the same network it can be
      <code>http://&lt;pc-ip&gt;:8787</code>.
    </p>

    <label class="drawer__label" for="bridge-url">Bridge URL</label>
    <input
      id="bridge-url"
      class="input"
      :value="form.url"
      placeholder="https://your-tunnel.trycloudflare.com"
      autocomplete="off"
      spellcheck="false"
      @input="update('url', $event.target.value)"
    />

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
</template>

<script>
import { checkHealth } from '../../lib/bridge.js'

export default {
  props: {
    settings: { type: Object, required: true },
  },
  emits: ['close', 'update'],
  data() {
    return {
      form: { ...this.settings },
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
          'If the URL and token look right, check that the bridge is running and ' +
          'that its allowed_origins includes this site.'
      } finally {
        this.testing = false
      }
    },
  },
}
</script>

<style scoped>
.drawer {
  padding: 16px;
  margin-bottom: 14px;
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
