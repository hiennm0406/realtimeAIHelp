<template>
  <div class="detail">
    <template v-if="item">
      <div class="hero card">
        <div class="hero__main">
          <div class="name">{{ item.name }}</div>
          <div class="metaLine">ID {{ item.id }}</div>

          <div class="primaryBadges">
            <span class="pill">{{ item.stats?.isActive ? 'Active' : 'Passive' }}</span>
            <span class="pill pill--muted">CD {{ item.stats?.cooldownSeconds ? item.stats.cooldownSeconds + 's' : '-' }}</span>
            <span class="pill pill--muted">Price {{ item.stats?.shopPrice ?? '-' }}</span>
          </div>

          <div class="tags">
            <span v-for="t in item.tags ?? []" :key="t" class="tag" :style="{ '--tag': tagColor(t) }">
              {{ tagName(t) }}
            </span>
          </div>
        </div>

        <div class="hero__image icon" :class="rarityClass(item.rarity)">
          <img v-if="item.icon" :src="item.icon" alt="" loading="lazy" decoding="async" />
          <div v-else class="icon__placeholder">{{ initials(item.name) }}</div>
        </div>
      </div>

      <div class="section">
        <div class="section__title">Effects</div>
        <div v-if="(item.effects ?? []).length === 0" class="empty">No effects.</div>

        <div v-else class="effects">
          <div v-for="(e, idx) in item.effects" :key="idx" class="effect">
            <div class="effect__meta">
              <span class="pill">{{ e.trigger }}</span>
              <span class="pill pill--muted">{{ e.type }}</span>
            </div>
            <div class="effect__text">{{ e.text }}</div>
            <div v-if="(e.fields ?? []).length > 0" class="fieldList">
              <span v-for="f in e.fields" :key="f.key + f.value" class="fieldChip"> {{ f.key }}: {{ f.value }} </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="(item.heroOwners ?? []).length > 0" class="section">
        <div class="owners">
          <span v-for="hero in item.heroOwners" :key="hero" class="ownerChip">{{ hero }}</span>
        </div>
      </div>
    </template>

    <div v-else class="empty">Select an item.</div>
  </div>
</template>

<script>
export default {
  props: {
    item: { type: Object, default: null },
    tagById: { type: Object, required: true },
  },
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
    tagName(id) {
      return this.tagById?.[id]?.name ?? id
    },
    tagColor(id) {
      return this.tagById?.[id]?.color ?? 'rgba(148,163,184,0.35)'
    },
  },
}
</script>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hero {
  padding: 14px;
  display: grid;
  grid-template-columns: 1fr 130px;
  gap: 14px;
  align-items: stretch;
}

.icon {
  width: 100%;
  height: 100%;
  min-height: 130px;
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
  font-weight: 900;
  letter-spacing: 0.8px;
  color: var(--muted);
  font-size: 20px;
}

.name {
  font-weight: 800;
  font-size: 24px;
}

.metaLine {
  color: var(--muted);
  font-size: 12px;
  margin-top: 4px;
}

.primaryBadges {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.section__title {
  font-weight: 700;
  margin-bottom: 8px;
}

.tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--tag) 50%, var(--border));
  background: color-mix(in srgb, var(--tag) 14%, var(--panel));
  color: var(--text);
  font-size: 12px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.stat {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel-2);
}

.stat__k {
  font-size: 12px;
  color: var(--muted);
}

.stat__v {
  margin-top: 4px;
  font-weight: 800;
}

.effects {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.effect {
  border: 1px solid var(--border);
  background: var(--panel-2);
  border-radius: 12px;
  padding: 10px;
}

.effect__meta {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.pill {
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
}

.pill--muted {
  color: var(--muted);
}

.effect__text {
  line-height: 1.35;
}

.fieldList {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.fieldChip {
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--muted);
}

.owners {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ownerChip {
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--panel-2);
}

.empty {
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 520px) {
  .hero {
    grid-template-columns: 1fr;
  }
}
</style>

