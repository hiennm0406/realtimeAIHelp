<template>
  <div class="gridWrap">
    <div class="gridTop">
      <div class="muted">{{ items.length }} items</div>
    </div>

    <div class="grid">
      <button
        v-for="it in items"
        :key="it.id"
        class="card itemCard"
        :class="{ active: it.id === selectedId }"
        @click="$emit('select', it.id)"
        type="button"
      >
        <div class="icon" :class="rarityClass(it.rarity)">
          <img v-if="it.icon" :src="it.icon" alt="" loading="lazy" decoding="async" />
          <div v-else class="icon__placeholder">{{ initials(it.name) }}</div>
        </div>

        <div class="meta">
          <div class="name">{{ it.name }}</div>
          <div class="sub">
            <span v-if="it.stats?.isActive">Active</span>
            <span v-else>Passive</span>
            <span class="dot">•</span>
            <span v-if="it.stats?.cooldownSeconds">{{ it.stats.cooldownSeconds }}s CD</span>
            <span v-else>—</span>
          </div>
        </div>
      </button>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    items: { type: Array, required: true },
    selectedId: { type: Number, default: null },
  },
  emits: ['select'],
  methods: {
    initials(name) {
      const s = String(name ?? '').trim()
      if (!s) return '?'
      const parts = s.split(/\s+/g)
      return (parts[0]?.[0] ?? '?').toUpperCase() + (parts[1]?.[0] ?? '')
    },
    rarityClass(rarity) {
      const r = String(rarity ?? '').toLowerCase()
      if (r === 'legendary') return 'legendary'
      if (r === 'epic') return 'epic'
      if (r === 'rare') return 'rare'
      return 'common'
    },
  },
}
</script>

<style scoped>
.gridWrap {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.gridTop {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.muted {
  color: var(--text-soft);
  font-size: 12px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.itemCard {
  padding: 12px;
  display: grid;
  grid-template-columns: 52px 1fr;
  gap: 12px;
  align-items: center;
  cursor: pointer;
  text-align: left;
  color: var(--text);
  background: var(--panel);
}

.itemCard:hover {
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: color-mix(in srgb, var(--panel) 88%, #1e293b);
}

.itemCard.active {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 14%, transparent);
}

.icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  border: 1px solid var(--border);
  overflow: hidden;
}

.icon.common {
  background: rgba(148, 163, 184, 0.08);
}
.icon.rare {
  background: rgba(96, 165, 250, 0.12);
}
.icon.epic {
  background: rgba(167, 139, 250, 0.14);
}
.icon.legendary {
  background: rgba(251, 191, 36, 0.14);
}

.icon img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.icon__placeholder {
  font-weight: 800;
  letter-spacing: 0.6px;
  color: var(--muted);
}

.name {
  font-weight: 700;
  color: var(--text);
  line-height: 1.25;
}

.sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-soft);
  display: flex;
  gap: 6px;
  align-items: center;
}

.dot {
  opacity: 0.7;
}
</style>

