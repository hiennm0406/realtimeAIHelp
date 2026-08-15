<template>
  <div class="itemsPage">
    <ItemFilters
      :all-tags="allTags"
      :all-heroes="allHeroes"
      :query="query"
      :match-mode="matchMode"
      :selected-tag-ids="selectedTags"
      :selected-hero-ids="selectedHeroes"
      :filtered-count="filteredItems.length"
      :total-count="items.length"
      @update:query="query = $event"
      @toggle-match-mode="toggleMatchMode"
      @toggle-tag="toggleTag"
      @toggle-hero="toggleHero"
      @clear="clearAll"
    />

    <section class="grid">
      <ItemGrid :items="filteredItems" :selected-id="selectedId" @select="onSelect" />
    </section>

    <aside class="detail card">
      <ItemDetailPanel :item="selectedItem" :tag-by-id="tagById" />
    </aside>
  </div>
</template>

<script>
import ItemGrid from './ItemGrid.vue'
import ItemDetailPanel from './ItemDetailPanel.vue'
import ItemFilters from './ItemFilters.vue'
import { filterItems, loadItemDatabase } from './../../data/itemDb'

export default {
  components: { ItemGrid, ItemDetailPanel, ItemFilters },
  data() {
    const { tags, tagById, items, heroes } = loadItemDatabase()
    return {
      allTags: tags,
      allHeroes: heroes,
      tagById,
      items,
      query: '',
      matchMode: 'any',
      selectedTags: new Set(),
      selectedHeroes: new Set(),
      selectedId: items[0]?.id ?? null,
    }
  },
  computed: {
    filteredItems() {
      return filterItems(this.items, {
        query: this.query,
        selectedTags: this.selectedTags,
        selectedHeroes: this.selectedHeroes,
        matchMode: this.matchMode,
      })
    },
    selectedItem() {
      return this.items.find((x) => x.id === this.selectedId) ?? null
    },
  },
  watch: {
    filteredItems(list) {
      if (list.length === 0) {
        this.selectedId = null
        return
      }
      if (!list.some((x) => x.id === this.selectedId)) {
        this.selectedId = list[0].id
      }
    },
  },
  methods: {
    toggleMatchMode() {
      this.matchMode = this.matchMode === 'all' ? 'any' : 'all'
    },
    toggleTag(id) {
      if (this.selectedTags.has(id)) this.selectedTags.delete(id)
      else this.selectedTags.add(id)
      this.selectedTags = new Set(this.selectedTags)
    },
    toggleHero(name) {
      if (this.selectedHeroes.has(name)) this.selectedHeroes.delete(name)
      else this.selectedHeroes.add(name)
      this.selectedHeroes = new Set(this.selectedHeroes)
    },
    clearAll() {
      this.query = ''
      this.selectedTags = new Set()
      this.selectedHeroes = new Set()
    },
    onSelect(id) {
      this.selectedId = id
    },
  },
}
</script>

<style scoped>
.itemsPage {
  display: grid;
  grid-template-columns: 320px 1fr 420px;
  gap: 16px;
  align-items: start;
}

.detail {
  padding: 14px;
}

@media (max-width: 1200px) {
  .itemsPage {
    grid-template-columns: 1fr;
  }
}
</style>
