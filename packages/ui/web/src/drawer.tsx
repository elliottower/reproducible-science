import { useEffect, useMemo, useRef, useState } from 'react'
import { useToast } from './toast'

/** A project `repro ui` has been run in, as GET /api/projects reports it. */
export interface Project {
  path: string
  name: string
  title: string | null
  opened_at: string
  current: boolean
  available: boolean
  claims: { verified: number; total: number } | null
}

/** How many cards show before "View all N projects →". */
export const CARDS_SHOWN = 6

/** The projects matching `q` (title, name or folder, every word), newest opened first. */
export function arrange(list: Project[], q: string): Project[] {
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return list
    .filter((p) => words.every((w) => `${p.name} ${p.title ?? ''} ${p.path}`.toLowerCase().includes(w)))
    .sort((a, b) => b.opened_at.localeCompare(a.opened_at))
}

/** "claims: 531/531 verified", or null when the project was never checked. */
export const claimsLine = (p: Project) =>
  p.claims ? `claims: ${p.claims.verified.toLocaleString('en-US')}/${p.claims.total.toLocaleString('en-US')} verified` : null

/** The ☰ drawer: Search all projects, then every project `repro ui` has been run in as a card,
 * newest opened first, the first six and then View all. Picking one switches the page to it; a
 * run going in another keeps going. */
export function Drawer({ open, onClose, onOpen, onVerify }: {
  open: boolean
  onClose: () => void
  /** Switch the page to the project at this folder. */
  onOpen: (path: string) => Promise<boolean>
  /** Switch to the project, then run repro verify there. */
  onVerify: (path: string) => Promise<void>
}) {
  const toast = useToast()
  const [list, setList] = useState<Project[] | null>(null)
  const [q, setQ] = useState('')
  const [everything, setEverything] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const search = useRef<HTMLInputElement>(null)
  const read = () =>
    fetch('api/projects')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`the server answered ${r.status}`))))
      .then((b) => { setList(b.projects); setError(null) })
      .catch((e) => { setList([]); setError(`The projects could not be read: ${e.message ?? e}`) })
  useEffect(() => {
    if (!open) return
    read()
    requestAnimationFrame(() => search.current?.focus())
  }, [open])
  useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [open])
  const all = useMemo(() => arrange(list ?? [], q), [list, q])
  const shown = everything || q ? all : all.slice(0, CARDS_SHOWN)
  const pick = (p: Project) => {
    if (p.current) return onClose()
    if (!p.available) return toast(`${p.path} holds no repro.yaml now`)
    onClose()
    onOpen(p.path)
  }
  return (
    <>
      <div className={`scrim ${open ? 'open' : ''}`} onClick={onClose} />
      <aside className={`drawer ${open ? 'open' : ''}`} aria-hidden={!open} inert={!open}>
        <header><b>Projects</b><button className="x" onClick={onClose}>×</button></header>
        <div className="cards">
          <input ref={search} className="dsearch" placeholder="Search all projects" value={q} onChange={(e) => setQ(e.target.value)} />
          {list === null && <div className="small muted">Loading…</div>}
          {error && <div className="small stale-text">{error}</div>}
          {shown.map((p) => (
            <div key={p.path} className={`card ${p.current ? 'here' : ''}`} onClick={() => pick(p)} title={p.path}>
              <div className="t">{p.title ?? p.name}</div>
              <div className="r mono">{p.name}{p.current && <span className="now">Viewing</span>}{!p.available && <span className="gone">not found</span>}</div>
              <div className="l">
                <div>
                  <i style={{ background: p.claims ? (p.claims.verified === p.claims.total ? '#1f9d55' : '#c7321c') : '#9aa1ae' }} />
                  {claimsLine(p) ?? (
                    <>claims: not checked · <a className="lnk" onClick={(e) => { e.stopPropagation(); onClose(); onVerify(p.path) }}>Verify (repro verify)</a></>
                  )}
                </div>
              </div>
            </div>
          ))}
          {!everything && !q && all.length > CARDS_SHOWN && (
            <div className="row more" onClick={() => setEverything(true)}>View all {all.length} projects →</div>
          )}
        </div>
      </aside>
    </>
  )
}
