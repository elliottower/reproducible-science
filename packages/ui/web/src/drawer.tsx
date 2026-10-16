import { useEffect, useMemo, useRef, useState } from 'react'
import { post } from './api'
import { useToast } from './toast'

/** A project `repro ui` has been run in, as GET /api/projects reports it. */
export interface Project {
  path: string
  name: string
  title: string | null
  opened_at: string
  starred: boolean
  current: boolean
  available: boolean
  claims: { verified: number; total: number; checked_at: string | null } | null
}

/** How many of All projects show before "View all N projects →". */
export const ROWS_SHOWN = 8

/** The projects matching `q` (name, title or folder), and how the drawer splits them: starred
 * ones as cards, the viewed one first; every project as a row, newest opened first. */
export function arrange(list: Project[], q: string): { starred: Project[]; all: Project[] } {
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const hit = (p: Project) => words.every((w) => `${p.name} ${p.title ?? ''} ${p.path}`.toLowerCase().includes(w))
  const shown = list.filter(hit)
  const starred = shown.filter((p) => p.starred).sort((a, b) => Number(b.current) - Number(a.current) || b.opened_at.localeCompare(a.opened_at))
  const all = [...shown].sort((a, b) => b.opened_at.localeCompare(a.opened_at))
  return { starred, all }
}

/** "claims: 531/531 verified", or that the project was never checked. */
export const claimsLine = (p: Project) =>
  p.claims ? `claims: ${p.claims.verified.toLocaleString('en-US')}/${p.claims.total.toLocaleString('en-US')} verified` : null

const opened = (ts: string) => (ts ? `opened ${new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : '')

function Star({ p, onStar }: { p: Project; onStar: (p: Project) => void }) {
  return (
    <button className={`gstar ${p.starred ? 'on' : ''}`} onClick={(e) => { e.stopPropagation(); onStar(p) }}>
      {p.starred ? '★ Starred' : '☆ Star'}
    </button>
  )
}

/** The ☰ drawer: Search projects, the starred projects as cards, then every project `repro ui`
 * has been run in. Picking one switches the page to it; a run going in another keeps going. */
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
  const { starred, all } = useMemo(() => arrange(list ?? [], q), [list, q])
  const rows = everything || q ? all : all.slice(0, ROWS_SHOWN)
  const star = (p: Project) =>
    post('api/projects/star', { path: p.path, starred: !p.starred })
      .then((r) => r.json())
      .then((res) => (res.ok ? read() : toast(`Could not star it: ${res.error}`)))
      .catch((e) => toast(`Could not star it: ${e}`))
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
          <input ref={search} className="dsearch" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} />
          {list === null && <div className="small muted">Loading…</div>}
          {error && <div className="small stale-text">{error}</div>}
          {starred.length > 0 && <div className="sec2">Starred</div>}
          {starred.map((p) => (
            <div key={p.path} className={`card ${p.current ? 'here' : ''}`} onClick={() => pick(p)} title={p.path}>
              <div className="head"><div className="t">{p.title ?? p.name}</div><Star p={p} onStar={star} /></div>
              <div className="r mono">{p.name}{p.current && <span className="now">Viewing</span>}</div>
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
          <div className="sec2">All projects · {all.length}</div>
          {rows.map((p) => (
            <div key={p.path} className="row" onClick={() => pick(p)} title={p.path}>
              <span className="mono">{p.name}</span>
              {!p.available && <span className="gone">not found</span>}
              <span className="when">{opened(p.opened_at)}</span>
              <Star p={p} onStar={star} />
            </div>
          ))}
          {!everything && !q && all.length > ROWS_SHOWN && (
            <div className="row more" onClick={() => setEverything(true)}>View all {all.length} projects →</div>
          )}
        </div>
      </aside>
    </>
  )
}
