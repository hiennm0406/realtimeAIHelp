import db from './items.generated.json'

export const TAG_COLORS = {
  weapon: '#f59e0b',
  armor: '#94a3b8',
  food: '#34d399',
  magic: '#a78bfa',
  fire: '#fb7185',
  ice: '#60a5fa',
  lightning: '#fbbf24',
  heal: '#22c55e',
}

export function normalize(s) {
  return String(s ?? '').toLowerCase()
}

export function buildTerms(query) {
  return normalize(query)
    .split('|')
    .map((x) => x.trim())
    .filter(Boolean)
}

export function collectHeroes(items) {
  const names = new Set()
  for (const it of items) {
    for (const hero of it.heroOwners ?? []) {
      const name = String(hero ?? '').trim()
      if (name) names.add(name)
    }
  }
  return Array.from(names).sort((a, b) => a.localeCompare(b))
}

export function loadItemDatabase() {
  const tags = (db.tags ?? []).map((t) => ({
    ...t,
    color: t.color ?? TAG_COLORS[t.id] ?? '#64748b',
  }))
  const items = db.items ?? []
  const tagById = Object.fromEntries(tags.map((t) => [t.id, t]))
  const heroes = collectHeroes(items)
  return { tags, tagById, items, heroes }
}

export function filterItems(
  items,
  { query = '', selectedTags = [], selectedHeroes = [], matchMode = 'any' },
) {
  const terms = buildTerms(query)
  const needTags = Array.isArray(selectedTags) ? selectedTags : Array.from(selectedTags)
  const needHeroes = Array.isArray(selectedHeroes) ? selectedHeroes : Array.from(selectedHeroes)
  const mode = matchMode

  return items.filter((it) => {
    if (needTags.length > 0) {
      const tags = it.tags ?? []
      const ok =
        mode === 'all' ? needTags.every((t) => tags.includes(t)) : needTags.some((t) => tags.includes(t))
      if (!ok) return false
    }

    if (needHeroes.length > 0) {
      const owners = it.heroOwners ?? []
      const ok =
        mode === 'all'
          ? needHeroes.every((h) => owners.includes(h))
          : needHeroes.some((h) => owners.includes(h))
      if (!ok) return false
    }

    if (terms.length > 0) {
      const hay =
        normalize(it.name) +
        ' ' +
        normalize((it.effects ?? []).map((e) => e.text).join(' ')) +
        ' ' +
        normalize((it.effects ?? []).flatMap((e) => (e.fields ?? []).map((f) => `${f.key} ${f.value}`)).join(' ')) +
        ' ' +
        normalize((it.heroOwners ?? []).join(' '))
      const ok = mode === 'all' ? terms.every((t) => hay.includes(t)) : terms.some((t) => hay.includes(t))
      if (!ok) return false
    }

    return true
  })
}
