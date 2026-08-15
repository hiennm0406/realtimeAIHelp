<template>
  <div class="itemDetailPage">
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

    <section class="list">
      <div v-if="filteredItems.length === 0" class="listEmpty card">
        Không có item nào khớp bộ lọc.
      </div>

      <template v-else>
        <p class="listMeta">
          Hiển thị <b>{{ visibleItems.length }}</b> / {{ filteredItems.length }} items
          <span v-if="hasMore"> — cuộn xuống để tải thêm</span>
        </p>

        <article v-for="it in visibleItems" :key="it.id" class="listRow card">
          <ItemDetailPanel :item="it" :tag-by-id="tagById" />
        </article>

        <div v-if="hasMore" ref="sentinel" class="loadSentinel" aria-hidden="true">
          <span class="loadSentinel__spinner" />
          <span class="loadSentinel__text">Đang tải thêm…</span>
        </div>

        <p v-else class="listDone">Đã hiển thị tất cả {{ filteredItems.length }} items.</p>
      </template>
    </section>
  </div>
</template>

<script>
import ItemFilters from './ItemFilters.vue'
import ItemDetailPanel from './ItemDetailPanel.vue'
import { filterItems, loadItemDatabase } from './../../data/itemDb'

const INITIAL_VISIBLE = 12
const LOAD_BATCH = 12

export default {
  components: { ItemFilters, ItemDetailPanel },
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
      visibleCount: INITIAL_VISIBLE,
      loadObserver: null,
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
    visibleItems() {
      return this.filteredItems.slice(0, this.visibleCount)
    },
    hasMore() {
      return this.visibleCount < this.filteredItems.length
    },
  },
  watch: {
    filteredItems() {
      this.resetVisibleBatch()
    },
    hasMore(ready) {
      this.$nextTick(() => {
        if (ready) this.observeSentinel()
        else this.unobserveSentinel()
      })
    },
  },
  mounted() {
    this.loadObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) this.loadMore()
      },
      { root: null, rootMargin: '320px 0px', threshold: 0 },
    )
    this.$nextTick(() => this.observeSentinel())
  },
  beforeUnmount() {
    this.unobserveSentinel()
    this.loadObserver?.disconnect()
    this.loadObserver = null
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
    resetVisibleBatch() {
      this.visibleCount = INITIAL_VISIBLE
    },
    loadMore() {
      if (!this.hasMore) return
      this.visibleCount = Math.min(this.visibleCount + LOAD_BATCH, this.filteredItems.length)
    },
    observeSentinel() {
      const el = this.$refs.sentinel
      if (!el || !this.loadObserver) return
      this.loadObserver.disconnect()
      this.loadObserver.observe(el)
    },
    unobserveSentinel() {
      this.loadObserver?.disconnect()
    },
  },
}
</script>

<style scoped>
.itemDetailPage {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  align-items: start;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.listMeta {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}

.listRow {
  padding: 14px;
}

.listEmpty {
  padding: 24px;
  color: var(--muted);
  text-align: center;
}

.loadSentinel {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  color: var(--muted);
  font-size: 13px;
}

.loadSentinel__spinner {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  animation: spin 0.7s linear infinite;
}

.listDone {
  margin: 0;
  padding: 8px 0 16px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .itemDetailPage {
    grid-template-columns: 1fr;
  }
}
</style>
