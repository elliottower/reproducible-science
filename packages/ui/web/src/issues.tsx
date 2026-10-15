import { useContext, useEffect, useRef, useState } from 'react'
import { CopyPrompt, FixCtx } from './fix'
import { STATIC } from './api'
import { issuePrompt, staticMessage } from './format'
import { useToast } from './toast'
import type { Graph, Issue, IssueOpen } from './types'

/** `● 2 issues ▾`, shown only when prereg, results or citations report a problem. N counts kinds
 * of problem, one row each, not the items under them. Claims and re-runs are never issues: each
 * has its own pill. */
export function IssuesPill({ graph, onOpen }: { graph: Graph; onOpen: (o: IssueOpen) => void }) {
  const rows = graph.issues ?? []
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])
  if (rows.length === 0) return null
  const go = (o: IssueOpen) => { setOpen(false); onOpen(o) }
  return (
    <div className="issues" ref={box}>
      <button className="pill big pill-btn bad" onClick={() => setOpen((v) => !v)}
        title="What prereg, results and citations report, one row per kind of problem">
        ● {rows.length} issue{rows.length === 1 ? '' : 's'} <span className="caret">▾</span>
      </button>
      {open && (
        <div className="issues-menu">
          {rows.map((r) => <IssueRow key={r.id} row={r} onOpen={go} />)}
        </div>
      )}
    </div>
  )
}

function IssueRow({ row, onOpen }: { row: Issue; onOpen: (o: IssueOpen) => void }) {
  const { project } = useContext(FixCtx)
  const first = row.items[0]
  return (
    <div className="issue-row">
      <div className="issue-title"><span className="issue-tool mono">{row.tool}</span> · {row.title}</div>
      <div className="issue-note">{row.note}</div>
      {row.items.length > 1 && (
        <div className="issue-items">
          {row.items.slice(0, 8).map((i, k) => (
            <button key={k} className="link-btn mono small" onClick={() => onOpen(i.open)} title="Open in UI">{i.label}</button>
          ))}
          {row.items.length > 8 && <span className="muted small">and {row.items.length - 8} more</span>}
        </div>
      )}
      {row.fix && (
        <div className="issue-actions">
          {first && <button className="repro-main" onClick={() => onOpen(first.open)}>Open in UI</button>}
          <CopyPrompt prompt={issuePrompt(row, project)} small />
        </div>
      )}
    </div>
  )
}

interface Diff {
  ok: boolean
  error?: string
  path: string
  commit: string | null
  old: { sha256: string; size: number } | null
  new: { sha256: string | null; size: number } | null
  binary: boolean
  diff: string
  note: string
}

const size = (n: number) => `${n.toLocaleString('en-US')} bytes`

/** The recorded bytes of a file against the file now, from the server's diff endpoint, which
 * serves only paths the issues list names. A binary file shows each side's hash and size. */
export function DiffView({ issue, path, label }: { issue: string; path: string; label: string }) {
  const [d, setD] = useState<Diff | null>(null)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()
  useEffect(() => {
    if (STATIC) {
      toast(staticMessage('file'))
      setError(staticMessage('file'))
      return
    }
    setD(null)
    setError(null)
    fetch(`api/diff?issue=${encodeURIComponent(issue)}&path=${encodeURIComponent(path)}`)
      .then((r) => r.json())
      .then((res: Diff) => (res.ok ? setD(res) : setError(res.error ?? 'refused')))
      .catch((e) => setError(String(e)))
  }, [issue, path])
  if (error) return <div className="diff-box"><div className="small stale-text">{error}</div></div>
  if (!d) return <div className="diff-box"><div className="small muted">Loading…</div></div>
  return (
    <div className="diff-box">
      <div className="diff-head small">
        <span className="strong">{label}</span>
        {d.commit && <span className="muted"> · from commit <span className="mono">{d.commit.slice(0, 12)}</span></span>}
      </div>
      {d.note && <div className="small diff-note">{d.note}</div>}
      {(d.binary || !d.old) && (
        <table className="kv small mono">
          <tbody>
            <tr><td>recorded</td><td>{d.old ? `${d.old.sha256} · ${size(d.old.size)}` : 'no copy kept'}</td></tr>
            <tr><td>now</td><td>{d.new ? `${d.new.sha256 ?? '—'} · ${size(d.new.size)}` : 'no file'}</td></tr>
          </tbody>
        </table>
      )}
      {!d.binary && d.old && (
        d.diff
          ? <pre className="diff-body">{d.diff.split('\n').map((ln, i) => (
              <span key={i} className={ln.startsWith('+') && !ln.startsWith('+++') ? 'add' : ln.startsWith('-') && !ln.startsWith('---') ? 'del' : ln.startsWith('@@') ? 'hunk' : ''}>{ln || ' '}</span>
            ))}</pre>
          : <div className="small muted">No difference in the text.</div>
      )}
    </div>
  )
}
