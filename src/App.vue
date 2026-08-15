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
  },
  beforeUnmount() {
    const vv = window.visualViewport
    if (vv) {
      vv.removeEventListener('resize', this.applyViewport)
      vv.removeEventListener('scroll', this.applyViewport)
    }
    window.removeEventListener('resize', this.applyViewport)
    window.removeEventListener('orientationchange', this.applyViewport)
  },
  methods: {
    // Mirror the *visible* viewport (which shrinks when the mobile keyboard
    // opens) into a CSS var so the layout can size itself to it and keep the
    // composer above the keyboard.
    applyViewport() {
      const vv = window.visualViewport
      const height = vv ? vv.height : window.innerHeight
      document.documentElement.style.setProperty('--app-vh', `${Math.round(height)}px`)
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
  .app {
    height: var(--app-vh, 100vh);
    overflow: hidden;
  }

  .content {
    height: 100%;
    padding: 8px;
  }
}
</style>
