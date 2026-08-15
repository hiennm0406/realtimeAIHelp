<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="brand__title">realtimeAIHelp</div>
        <div class="brand__sub">Claude Code, from any device</div>
      </div>

      <nav class="nav">
        <RouterLink class="nav__link" :to="{ name: 'chat' }">Chat</RouterLink>
        <RouterLink class="nav__link" :to="{ name: 'items' }">Items</RouterLink>
        <RouterLink class="nav__link" :to="{ name: 'itemdetail' }">Item Detail</RouterLink>
      </nav>
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

.nav {
  display: flex;
  gap: 10px;
}

.nav__link {
  padding: 8px 10px;
  border-radius: 10px;
  color: var(--text);
  text-decoration: none;
  border: 1px solid transparent;
}

.nav__link.router-link-active {
  border-color: var(--border);
  background: var(--panel);
}

.content {
  padding: 16px;
}
</style>
