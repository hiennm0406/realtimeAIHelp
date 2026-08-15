<template>
  <div class="app">
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<script>
export default {
  mounted() {
    this.applyViewport()
    const vv = window.visualViewport
    if (vv) {
      vv.addEventListener('resize', this.applyViewport)
      vv.addEventListener('scroll', this.applyViewport)
    }
    window.addEventListener('resize', this.applyViewport)
    window.addEventListener('orientationchange', this.applyViewport)
    // The keyboard often opens/closes a beat after focus changes, and some
    // browsers don't emit a viewport event for it — re-measure a few times
    // around each focus change so we still catch the settled size.
    window.addEventListener('focusin', this.remeasure)
    window.addEventListener('focusout', this.remeasure)
  },
  beforeUnmount() {
    const vv = window.visualViewport
    if (vv) {
      vv.removeEventListener('resize', this.applyViewport)
      vv.removeEventListener('scroll', this.applyViewport)
    }
    window.removeEventListener('resize', this.applyViewport)
    window.removeEventListener('orientationchange', this.applyViewport)
    window.removeEventListener('focusin', this.remeasure)
    window.removeEventListener('focusout', this.remeasure)
    this.clearRemeasure()
  },
  methods: {
    // Pin the app to the *visible* viewport. When the mobile keyboard opens the
    // visual viewport both shrinks (height) and can be scrolled down within the
    // layout viewport (offsetTop); mirroring both into CSS vars lets us fix the
    // app exactly over the visible area so the composer stays above the keyboard.
    applyViewport() {
      const vv = window.visualViewport
      const height = vv ? vv.height : window.innerHeight
      const top = vv ? vv.offsetTop : 0
      const root = document.documentElement.style
      root.setProperty('--app-vh', `${Math.round(height)}px`)
      root.setProperty('--app-top', `${Math.round(top)}px`)
    },

    remeasure() {
      this.clearRemeasure()
      this.applyViewport()
      this._remeasure = [80, 200, 400, 700].map((ms) =>
        setTimeout(this.applyViewport, ms)
      )
    },

    clearRemeasure() {
      ;(this._remeasure || []).forEach(clearTimeout)
      this._remeasure = []
    },
  },
}
</script>

<style>
@import "./css/global.css";

.app {
  min-height: 100vh;
  min-height: var(--app-vh, 100vh);
  background: var(--bg);
  color: var(--text);
}

.content {
  padding: 16px;
}

@media (max-width: 640px) {
  /* Lock the document so only the app owns the visible area; without this the
     page itself can scroll and slide the composer back under the keyboard. */
  html,
  body {
    height: var(--app-vh, 100dvh);
    overflow: hidden;
  }

  /* Fix the app over the visible viewport so the on-screen keyboard can never
     cover the composer — it simply sits at the bottom of the visible area. */
  .app {
    position: fixed;
    left: 0;
    right: 0;
    top: var(--app-top, 0px);
    height: var(--app-vh, 100dvh);
    min-height: 0;
    overflow: hidden;
  }

  .content {
    height: 100%;
    padding: 8px;
  }
}
</style>
