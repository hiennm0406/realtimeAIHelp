<template>
  <div class="md" v-html="rendered"></div>
</template>

<script>
import { renderMarkdown } from '../../lib/markdown.js'

/**
 * Renders one assistant text block.
 *
 * The old approach called renderMarkdown() inline in the parent template, so
 * every streamed token re-parsed the markdown of *every* text block on screen -
 * O(n²) work that made long answers stutter. Here each block is its own
 * component, so only the block currently streaming re-parses; finished blocks
 * keep their cached HTML. While streaming we also throttle the re-parse to ~10x
 * a second, and always render the final markdown once the block completes.
 */
const THROTTLE_MS = 100

export default {
  props: {
    text: { type: String, default: '' },
    done: { type: Boolean, default: false },
  },
  data() {
    return { rendered: '' }
  },
  created() {
    this._last = 0
    this._timer = null
    this.render()
  },
  watch: {
    text() {
      this.schedule()
    },
    done(value) {
      if (value) this.renderNow()
    },
  },
  beforeUnmount() {
    if (this._timer) clearTimeout(this._timer)
  },
  methods: {
    render() {
      this.rendered = renderMarkdown(this.text)
    },
    renderNow() {
      if (this._timer) {
        clearTimeout(this._timer)
        this._timer = null
      }
      this._last = performance.now()
      this.render()
    },
    schedule() {
      if (this.done) return this.renderNow()
      const now = performance.now()
      const since = now - this._last
      if (since >= THROTTLE_MS) {
        this._last = now
        this.render()
      } else if (!this._timer) {
        this._timer = setTimeout(() => {
          this._timer = null
          this._last = performance.now()
          this.render()
        }, THROTTLE_MS - since)
      }
    },
  },
}
</script>
