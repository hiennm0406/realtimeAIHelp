<template>
  <div class="app">
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

.content {
  padding: 16px;
}
</style>
