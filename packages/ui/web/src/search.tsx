import { useEffect, useMemo, useRef, useState } from 'react'
import type { Graph } from './types'

/** Where a search result takes the page. */
export type Jump =
  | { kind: 'claim'; id: string }
  | { kind: 'quote'; file: string; statement: string; index: number }
  | { kind: 'source'; file: string }
  | { kind: 'file'; id: string }
  | { kind: 'step'; id: string }

interface Hit { kind: Jump['kind']; label: string; sub: string; text: string; jump: Jump }

const KIND: Record<Jump['kind'], string> = { claim: 'Claim', quote: 'Quote', source: 'Source', file: 'File', step: 'Step' }

/** Everything the search box can jump to, with the text it is matched on. */
export function searchIndex(graph: Graph): Hit[] {
  const hits: Hit[] = []
  const seen = new Set<string>()
  for (const n of graph.nodes) {
    for (const c of n.claims) {
      if (seen.has(c.id)) continue
      seen.add(c.id)
      hits.push({ kind: 'claim', label: c.id, sub: c.text, text: `${c.id} ${c.text} ${c.where}`, jump: { kind: 'claim', id: c.id } })
    }
    if (n.type === 'artifact') {
      hits.push({ kind: 'file', label: n.path ?? n.id, sub: n.id, text: `${n.id} ${n.path ?? ''}`, jump: { kind: 'file', id: n.id } })
    }
  }
  for (const s of graph.tabs?.citations.sources ?? []) {
    hits.push({ kind: 'source', label: s.bib.title || s.citation, sub: s.citation, text: `${s.citation} ${s.bib.title ?? ''} ${s.bib.author ?? ''}`, jump: { kind: 'source', file: s.file } })
    for (const st of s.statements) {
      st.quotes.forEach((q, index) =>
        hits.push({ kind: 'quote', label: q.exact, sub: s.citation, text: q.exact, jump: { kind: 'quote', file: s.file, statement: st.id, index } }))
    }
  }
  for (const st of graph.tabs?.reproduce.steps ?? []) {
    hits.push({ kind: 'step', label: st.id, sub: st.command, text: `${st.id} ${st.command}`, jump: { kind: 'step', id: st.id } })
  }
  return hits
}

/** The best matches for `query`: every word must appear; a match at the start of the label first. */
export function search(index: Hit[], query: string, limit = 12): Hit[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return []
  const found = index.filter((h) => {
    const t = h.text.toLowerCase()
    return words.every((w) => t.includes(w))
  })
  const q = words.join(' ')
  return found
    .map((h) => ({ h, rank: h.label.toLowerCase().startsWith(q) ? 0 : h.label.toLowerCase().includes(q) ? 1 : 2 }))
    .sort((a, b) => a.rank - b.rank)
    .slice(0, limit)
    .map((x) => x.h)
}

/** The search box in the top bar. ⌘K (or Ctrl-K) focuses it; arrows pick, Enter jumps. */
export function SearchBox({ graph, onJump }: { graph: Graph; onJump: (j: Jump) => void }) {
  const index = useMemo(() => searchIndex(graph), [graph])
  const [q, setQ] = useState('')
  const [at, setAt] = useState(0)
  const [open, setOpen] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const hits = useMemo(() => search(index, q), [index, q])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        input.current?.focus()
        input.current?.select()
      }
    }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [])
  const go = (h: Hit) => { onJump(h.jump); setOpen(false); input.current?.blur() }
  return (
    <div className="top-search">
      <span>⌕</span>
      <input ref={input} value={q} placeholder="Search claims, quotes, files, steps"
        onChange={(e) => { setQ(e.target.value); setAt(0); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setAt((a) => Math.min(a + 1, hits.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setAt((a) => Math.max(a - 1, 0)) }
          else if (e.key === 'Enter' && hits[at]) go(hits[at])
          else if (e.key === 'Escape') { setOpen(false); input.current?.blur() }
        }} />
      <kbd>⌘K</kbd>
      {open && q.trim() && (
        <div className="search-results">
          {hits.length === 0 && <div className="search-none">Nothing matches.</div>}
          {hits.map((h, i) => (
            <button key={`${h.kind}-${i}`} className={`search-hit ${i === at ? 'on' : ''}`} onMouseDown={(e) => { e.preventDefault(); go(h) }} onMouseEnter={() => setAt(i)}>
              <span className="search-kind">{KIND[h.kind]}</span>
              <span className="search-label">{h.label}</span>
              <span className="search-sub">{h.sub}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
