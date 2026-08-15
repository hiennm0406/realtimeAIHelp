<template>
  <aside class="filters card">
    <div class="filters__title">Filters</div>

    <label class="filters__label">Name & text</label>
    <input
      class="input"
      :value="query"
      placeholder="Use | for multiple terms (e.g. fire | sword)"
      autocomplete="off"
      @input="$emit('update:query', $event.target.value.trim())"
    />

    <div class="filters__row">
      <button class="btn" type="button" @click="$emit('toggle-match-mode')">
        {{ matchModeLabel }}
      </button>
      <button class="btn" type="button" @click="$emit('clear')">Clear</button>
    </div>

    <div class="filters__label">Tags</div>
    <div class="tagGrid">
      <button
        v-for="t in allTags"
        :key="t.id"
        type="button"
        class="tagPick"
        :class="{ active: selectedTagIds.has(t.id) }"
        :style="{ '--tag': t.color }"
        @click="$emit('toggle-tag', t.id)"
      >
        {{ t.name }}
      </button>
    </div>

    <div v-if="allHeroes.length > 0" class="filters__label">Heroes</div>
    <div v-if="allHeroes.length > 0" class="heroGrid">
      <button
        v-for="hero in allHeroes"
        :key="hero"
        type="button"
        class="heroPick"
        :class="{ active: selectedHeroIds.has(hero) }"
        @click="$emit('toggle-hero', hero)"
      >
        {{ hero }}
      </button>
    </div>

    <div class="filters__hint">
      Showing <b>{{ filteredCount }}</b> / {{ totalCount }} items.
    </div>
  </aside>
</template>

<script>
export default {
  props: {
    allTags: { type: Array, required: true },
    allHeroes: { type: Array, default: () => [] },
    query: { type: String, default: '' },
    matchMode: { type: String, default: 'any' },
    selectedTagIds: { type: Object, required: true },
    selectedHeroIds: { type: Object, default: () => new Set() },
    filteredCount: { type: Number, required: true },
    totalCount: { type: Number, required: true },
  },
  emits: ['update:query', 'toggle-match-mode', 'toggle-tag', 'toggle-hero', 'clear'],
  computed: {
    matchModeLabel() {
      return this.matchMode === 'all' ? 'Match All' : 'Match Any'
    },
  },
}
</script>

<style scoped>
.filters {
  padding: 14px;
}

.filters__title {
  font-weight: 700;
  margin-bottom: 10px;
}

.filters__label {
  display: block;
  margin: 10px 0 6px;
  font-size: 12px;
  color: var(--muted);
}

.filters__row {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.filters__hint {
  margin-top: 12px;
  font-size: 12px;
  color: var(--muted);
}

.tagGrid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.tagPick {
  text-align: left;
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
}

.tagPick.active {
  border-color: color-mix(in srgb, var(--tag) 75%, var(--border));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--tag) 22%, transparent);
}

.heroGrid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.heroPick {
  text-align: left;
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  cursor: pointer;
}

.heroPick.active {
  border-color: color-mix(in srgb, var(--accent) 75%, var(--border));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 22%, transparent);
}
</style>
