import { useContext, useMemo, useState } from 'react'
import { CopyPrompt, failingPrompt, FixCtx } from './fix'
import { ClaimList, ClaimText, fmt, Freshness, HistoryStrip, Panel, when } from './shared'
import type { ClaimRow, GNode, Graph } from './types'

type View =
  | { kind: 'files'; group: string | null }
  | { kind: 'claims'; filter: 'all' | 'failing' | 'stale'; group?: string }

const FRESH_ORDER: Record<string, number> = { stale: 0, never_rerun: 1, current: 2, no_producer: 3 }

function ClaimPanel({ claim, onClose }: { claim: ClaimRow; onClose: () => void }) {
  return (
    <aside className="panel">
      <button className="close" onClick={onClose}>×</button>
      <div className="kicker">CLAIM</div>
      <h2 className="mono">{claim.id}</h2>
      <ClaimList claims={[claim]} />
    </aside>
  )
}

export default function Catalog({ graph, query }: { graph: Graph; query: string }) {
  const [view, setView] = useState<View>({ kind: 'claims', filter: 'all' })
  const { project } = useContext(FixCtx)
  const [selected, setSelected] = useState<string | null>(null)
  const q = query.trim().toLowerCase()

  const files = graph.nodes.filter((n) => n.type === 'artifact')
  const fileGroups = graph.groups.filter((g) => g.kind === 'files')
  const paperGroups = graph.groups.filter((g) => g.kind === 'sections')

  const claims = useMemo(() => {
    const seen = new Map<string, ClaimRow>()
    for (const n of graph.nodes) if (n.type === 'section') for (const c of n.claims) seen.set(c.id, c)
    return [...seen.values()]
  }, [graph])

  const staleFiles = new Set(files.filter((f) => f.freshness === 'stale').map((f) => f.id))
  const readsStale = (c: ClaimRow) => c.assertions.some((a) => staleFiles.has(a.artifact) && a.artifact !== 'manuscript-text')

  const rows: GNode[] = useMemo(() => {
    if (view.kind !== 'files') return []
    return files
      .filter((f) => view.group === null || f.group === view.group)
      .filter((f) => !q || `${f.id} ${f.path}`.toLowerCase().includes(q))
      .sort((a, b) => b.fail - a.fail || (FRESH_ORDER[a.freshness ?? ''] ?? 9) - (FRESH_ORDER[b.freshness ?? ''] ?? 9) || a.id.localeCompare(b.id))
  }, [files, view, q])

  const claimRows: ClaimRow[] = useMemo(() => {
    if (view.kind !== 'claims') return []
    const sections = view.group ? new Set(graph.nodes.filter((n) => n.group === view.group).map((n) => n.label)) : null
    return claims
      .filter((c) => !sections || sections.has(c.section))
      .filter((c) => view.filter === 'all' || (view.filter === 'failing' ? !c.ok : readsStale(c)))
      .filter((c) => !q || `${c.id} ${c.text} ${c.where}`.toLowerCase().includes(q))
      .sort((a, b) => Number(a.ok) - Number(b.ok) || a.where.localeCompare(b.where, 'en', { numeric: true }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claims, view, q, graph])

  const is = (v: View) => JSON.stringify(v) === JSON.stringify(view)
  const go = (v: View) => { setView(v); setSelected(null) }
  const selectedClaim = claims.find((c) => c.id === selected)

  return (
    <div className="catalog">
      <nav className="side">
        <div className="side-head">CLAIMS</div>
        <button className={is({ kind: 'claims', filter: 'all' }) ? 'on' : ''} onClick={() => go({ kind: 'claims', filter: 'all' })}>
          All claims <span className="count">{fmt(claims.length)}</span>
        </button>
        <button className={is({ kind: 'claims', filter: 'failing' }) ? 'on' : ''} onClick={() => go({ kind: 'claims', filter: 'failing' })}>
          Failing <span className="count">{claims.filter((c) => !c.ok).length}</span>
        </button>
        <button className={is({ kind: 'claims', filter: 'stale' }) ? 'on' : ''} onClick={() => go({ kind: 'claims', filter: 'stale' })} title="Claims reading a data file whose rebuild step is stale (the manuscript text itself is left out)">
          Reading a stale file <span className="count">{claims.filter(readsStale).length}</span>
        </button>
        <div className="side-head">PAPER</div>
        {paperGroups.map((g) => (
          <button key={g.id} className={is({ kind: 'claims', filter: 'all', group: g.id }) ? 'on' : ''} onClick={() => go({ kind: 'claims', filter: 'all', group: g.id })}>
            {g.id.replace('Paper: ', '')}
            <span className="count">{graph.nodes.filter((n) => n.group === g.id).reduce((a, n) => a + n.ok + n.fail, 0)}</span>
          </button>
        ))}
        <div className="side-head">FILES</div>
        <button className={is({ kind: 'files', group: null }) ? 'on' : ''} onClick={() => go({ kind: 'files', group: null })}>
          All files <span className="count">{files.length}</span>
        </button>
        {fileGroups.map((g) => {
          const m = files.filter((f) => f.group === g.id)
          const st = m.filter((f) => f.freshness === 'stale').length
          return (
            <button key={g.id} className={is({ kind: 'files', group: g.id }) ? 'on' : ''} onClick={() => go({ kind: 'files', group: g.id })}>
              {g.id}
              {st > 0 && <span className="stale-dot" title={`${st} stale`} />}
              <span className="count">{m.length}</span>
            </button>
          )
        })}
      </nav>

      <main className="table-wrap">
        <div className="rec-head">
          <div className="mono rec-line">
            <span className="ov-cmd">repro verify:</span> {fmt(claims.filter((x) => x.ok).length)}/{fmt(claims.length)} claims verified ({fmt(graph.totals.assertions)} checks)
          </div>
          {claims.some((x) => !x.ok) && (
            <div className="fix">
              <span className="small muted">{claims.filter((x) => !x.ok).length} failing. Click a claim for its own prompt, or:</span>
              <CopyPrompt prompt={failingPrompt(graph, project)} small />
            </div>
          )}
        </div>
        {view.kind === 'files' ? (
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Group</th>
                <th className="num">Claims</th>
                <th>Status</th>
                <th>Freshness</th>
                <th>Last check</th>
                <th>Rebuilt by</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.id} className={selected === f.id ? 'sel' : ''} onClick={() => setSelected(f.id)}>
                  <td>
                    <div className="mono strong">{f.id}</div>
                    <div className="mono muted small">{f.path}</div>
                  </td>
                  <td className="small">{f.group}</td>
                  <td className="num">{fmt(f.ok + f.fail)}</td>
                  <td>{f.fail ? <span className="pill bad">{f.fail} failing</span> : f.ok ? <span className="pill good">Verified</span> : <span className="muted small">unread</span>}</td>
                  <td><Freshness node={f} /></td>
                  <td className="small">{f.last_checked ? when(f.last_checked) : '—'}</td>
                  <td className="mono small muted">{f.code?.[0]?.split('/').pop() ?? (f.regenerated_by ? f.regenerated_by.split(' ')[1]?.split('/').pop() : '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Where</th>
                <th>Status</th>
                <th>Reads</th>
                <th>Check history</th>
              </tr>
            </thead>
            <tbody>
              {claimRows.slice(0, 600).map((c) => (
                <tr key={c.id} className={selected === c.id ? 'sel' : ''} onClick={() => setSelected(c.id)}>
                  <td>
                    <div className="mono strong">{c.id}</div>
                    <div className="small claim-cell"><ClaimText text={c.text} /></div>
                  </td>
                  <td className="small nowrap">{c.where}</td>
                  <td>{c.ok ? <span className="pill good">Verified</span> : <span className="pill bad">Failing</span>}</td>
                  <td className="mono small muted">
                    {[...new Set(c.assertions.map((a) => a.artifact))].map((a) => (
                      <div key={a} className={staleFiles.has(a) ? 'stale-text' : ''}>{a}</div>
                    ))}
                  </td>
                  <td><HistoryStrip points={c.history} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {(view.kind === 'files' ? rows.length : claimRows.length) === 0 && <div className="empty muted">Nothing here{q ? ` matches “${query}”` : ''}.</div>}
      </main>

      {selected && view.kind === 'files' && <Panel graph={graph} id={selected} onClose={() => setSelected(null)} />}
      {selectedClaim && view.kind === 'claims' && <ClaimPanel claim={selectedClaim} onClose={() => setSelected(null)} />}
    </div>
  )
}
