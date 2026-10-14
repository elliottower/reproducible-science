import { Fragment, useMemo, useState } from 'react'
import { fmt, when } from './shared'
import type { Graph } from './types'

/** One page per record, each opening with the line the Overview shows and a sentence on what the
 * record is, then the record itself as a table. */

function Head({ cmd, line, what }: { cmd: string; line: string; what: string }) {
  return (
    <div className="rec-head">
      <div className="mono rec-line"><span className="ov-cmd">{cmd}:</span> {line}</div>
      <p className="rec-what">{what}</p>
    </div>
  )
}

const CAUSE: Record<string, string> = {
  input_changed: 'input changed',
  output_changed: 'output changed',
  command_changed: 'command changed',
}
const STATE: Record<string, [string, string]> = {
  current: ['Reproduced', 'good'],
  stale: ['Changed since re-run', 'warn'],
  never_rerun: ['Never re-run', 'warn'],
}

export function PreregTab({ graph }: { graph: Graph }) {
  const lines = graph.tabs?.prereg.lines ?? []
  return (
    <div className="rec">
      <Head cmd="prereg" line={graph.status?.prereg.text ?? '—'}
        what="A preregistration is the analysis plan, frozen against a commit and a content hash before the analysis runs. Every later change is logged as an amendment or a deviation. Optional: a project without a plan is not failing." />
      {graph.status?.prereg.next && (
        <p className="rec-next">To preregister: <span className="mono">prereg new</span>, then <span className="mono">prereg freeze</span>.</p>
      )}
      <pre className="rec-pre">{lines.map((l) => (/^no PREREG\.md/i.test(l) ? 'No PREREG.md' : l)).join('\n') || 'No PREREG.md'}</pre>
    </div>
  )
}

export function ResultsTab({ graph, query }: { graph: Graph; query: string }) {
  const t = graph.tabs?.results
  const [showBound, setShowBound] = useState(false)
  const [viewing, setViewing] = useState<string | null>(null)
  const q = query.trim().toLowerCase()
  const runs = useMemo(
    () => [...(t?.runs ?? [])].reverse().filter((r) => !q || `${r.run_id} ${r.note} ${r.outputs.join(' ')}`.toLowerCase().includes(q)),
    [t, q],
  )
  return (
    <div className="rec">
      <Head cmd="results" line={graph.status?.results.counts ? `${fmt(graph.status.results.counts.sealed)}/${fmt(graph.status.results.counts.runs)} runs sealed` : graph.status?.results.text ?? '—'}
        what="The results ledger, a hash chain of events. results seal hashes a run's inputs before it runs; results run records the files the run wrote, with their hashes. Click a file to read it." />
      <table>
        <thead><tr><th>Run</th><th>Recorded</th><th>Inputs</th><th>Outputs</th><th>Files written</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={`${r.run_id}${r.timestamp}`} className="static">
              <td><div className="mono strong">{r.run_id}</div><div className="small muted claim-cell">{r.note}</div></td>
              <td className="small nowrap">{when(r.timestamp)}</td>
              <td>{r.sealed_before ? <span className="pill good">Sealed</span> : <span className="pill bad">Not sealed</span>}</td>
              <td>{r.outputs.length ? <span className="pill good">Recorded</span> : <span className="pill bad">None</span>}</td>
              <td className="mono small">
                {r.outputs.map((o) => (
                  <div key={o}><button className="file-link" onClick={() => setViewing(o)}>{o}</button></div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {viewing && <FileViewer path={viewing} onClose={() => setViewing(null)} />}
      <button className="more rec-more" onClick={() => setShowBound((v) => !v)}>
        {showBound ? 'Hide' : 'Show'} the {fmt(t?.bound.length ?? 0)} sentences bound with results claim
      </button>
      {showBound && (
        <>
          <p className="rec-what">Sentences tied to a run by hand with results claim. A separate, older record from the claims repro verify checks, and not checked against the current paper.</p>
          <table>
            <thead><tr><th>Sentence</th><th>Run</th><th>Where</th></tr></thead>
            <tbody>
              {(t?.bound ?? []).map((b, i) => (
                <tr key={i} className="static">
                  <td className="small claim-cell">{b.claim}</td>
                  <td className="mono small">{b.run_id}</td>
                  <td className="small muted">{b.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

export function CitationsTab({ graph, query }: { graph: Graph; query: string }) {
  const sources = graph.tabs?.citations.sources ?? []
  const q = query.trim().toLowerCase()
  // One row per quote, in the claims files' own order: source, then statement, then quote.
  const rows = sources.flatMap((s) =>
    s.statements.flatMap((st) =>
      st.quotes.map((qq, i) => ({ s, st, qq, first: i === 0 })),
    ),
  ).filter(({ s, st, qq }) => !q || `${s.citation} ${qq.section} ${qq.exact} ${st.statement} ${st.notes}`.toLowerCase().includes(q))
  // A source, and a statement, is written once and spans the rows of its quotes.
  const span = (i: number, key: (r: (typeof rows)[number]) => string) => {
    if (i > 0 && key(rows[i - 1]) === key(rows[i])) return 0
    let n = 1
    while (i + n < rows.length && key(rows[i + n]) === key(rows[i])) n += 1
    return n
  }
  const bySource = (r: (typeof rows)[number]) => r.s.file
  const byStatement = (r: (typeof rows)[number]) => `${r.s.file}::${r.st.id}`
  return (
    <div className="rec">
      <Head cmd="citations" line={graph.status?.citations.text ?? '—'}
        what="Passages quoted from other people's work. Each row is one quotation: the source and the section it comes from, the exact words, and the statement the paper reads into them. A source is pinned when its file is saved with a hash, so the words can be checked against it; citations verify does that check, which reads every source and takes minutes." />
      <table className="cite-table">
        <thead><tr><th>Source</th><th>Section</th><th style={{ width: '38%' }}>Quoted text</th><th>Statement</th><th>Pinned</th></tr></thead>
        <tbody>
          {rows.map(({ s, st, qq }, i) => {
            const srcSpan = span(i, bySource)
            const stSpan = span(i, byStatement)
            return (
              <tr key={`${s.file}-${st.id}-${i}`} className={`static ${srcSpan ? 'src-start' : ''}`}>
                {srcSpan > 0 && (
                  <td rowSpan={srcSpan}>{s.url ? <a className="mono src-link" href={s.url} target="_blank" rel="noreferrer">{s.citation}</a> : <span className="mono">{s.citation}</span>}</td>
                )}
                <td className="small">{qq.section || <span className="muted">—</span>}</td>
                <td className="quote">“{qq.exact}”</td>
                {stSpan > 0 && (
                  <td className="small" rowSpan={stSpan}>
                    {st.statement}
                    {st.notes && <div className="cite-note">{st.notes}</div>}
                  </td>
                )}
                {srcSpan > 0 && (
                  <td rowSpan={srcSpan}>{s.sha256 ? <span className="pill good" title={`${s.local} · sha256 ${s.sha256.slice(0, 12)}…`}>Pinned</span> : <span className="pill bad">Not pinned</span>}</td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
      {rows.length === 0 && <div className="empty muted">Nothing here{q ? ` matches “${query}”` : ''}.</div>}
    </div>
  )
}

export function ReproduceTab({ graph, query }: { graph: Graph; query: string }) {
  const t = graph.tabs?.reproduce
  const q = query.trim().toLowerCase()
  const steps = [...(t?.steps ?? [])].filter((s) => !q || `${s.id} ${s.command} ${s.state}`.toLowerCase().includes(q)).sort((a, b) => (a.state === 'current' ? 1 : 0) - (b.state === 'current' ? 1 : 0) || a.id.localeCompare(b.id))
  const need = steps.filter((s) => s.state !== 'current').length
  const rp = graph.reproduce
  return (
    <div className="rec">
      <Head cmd="repro reproduce" line={rp?.runs ? `${fmt(rp.last.reproduced ?? 0)}/${fmt(rp.last_steps)} reproduced${rp.last_at ? ` ${new Date(rp.last_at).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })}` : ''}${need ? ` · ${need} of ${steps.length} steps need re-running` : ''}` : 'never run'}
        what="A rebuild step is a command repro.yaml declares that turns input files into an output file, such as detex.py or a derive script. repro reproduce runs every step again and checks the output comes out identical. repro stale, run on every check, compares each step with the last re-run without running anything: that is the state column." />
      <table>
        <thead><tr><th>Step</th><th>State</th><th>What changed</th><th>Command</th></tr></thead>
        <tbody>
          {steps.map((s) => {
            const [label, tone] = STATE[s.state] ?? [s.state, 'none']
            return (
              <tr key={s.id} className="static">
                <td className="mono strong">{s.id}</td>
                <td><span className={`pill ${tone === 'warn' ? 'stale' : tone}`}>{label}</span></td>
                <td className="small">{s.causes.map((c, i) => <div key={i}>{CAUSE[c.cause] ?? c.cause}: <span className="mono">{c.artifact}</span></div>)}</td>
                <td className="mono small muted claim-cell">{s.command}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <h3 className="rec-h3">Re-runs recorded</h3>
      <table>
        <thead><tr><th>Finished</th><th>Steps</th><th>Result</th><th>Toolkit</th></tr></thead>
        <tbody>
          {[...(t?.reruns ?? [])].reverse().map((r, i) => (
            <tr key={i} className="static">
              <td className="small">{r.ended_at ? when(r.ended_at) : '—'}</td>
              <td className="num">{r.steps}</td>
              <td className="small">{Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(', ')}</td>
              <td className="mono small muted">{r.tool_version}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** A recorded file, read through the local server: JSON indented, anything else as text. */
function FileViewer({ path, onClose }: { path: string; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useMemo(() => {
    fetch(`api/file?path=${encodeURIComponent(path)}`)
      .then((r) => r.json())
      .then((res) => {
        if (!res.ok) return setError(res.error)
        try {
          setText(JSON.stringify(JSON.parse(res.text), null, 2))
        } catch {
          setText(res.text)
        }
      })
      .catch((e) => setError(String(e)))
  }, [path])
  return (
    <div className="viewer-back" onClick={onClose}>
      <div className="viewer" onClick={(e) => e.stopPropagation()}>
        <div className="viewer-head">
          <span className="mono">{path}</span>
          <button className="close" onClick={onClose}>×</button>
        </div>
        <pre className="viewer-body">{error ?? text ?? 'Loading…'}</pre>
      </div>
    </div>
  )
}
