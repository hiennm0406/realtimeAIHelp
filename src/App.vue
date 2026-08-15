<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="brand__title">realtimeAIHelp</div>
        <div class="brand__sub">Claude Code, from any device</div>
      </div>
    </header>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<script>
export default {}
</script>

<style>
@import "./css/global.css";

.app {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 86%, black);
  backdrop-filter: blur(6px);
}

.brand__title {
  font-weight: 700;
  letter-spacing: 0.3px;
}

.brand__sub {
  font-size: 12px;
  color: var(--muted);
}

.content {
  padding: 16px;
}
</style>
