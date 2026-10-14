import { fmt, when } from './shared'
import type { Graph, StatusField } from './types'

/** What each of the project's records holds, one card per tool, in words a reader needs no
 * glossary for. The four tools count different things, so each card says what its count is. */
export default function Overview({ graph, onOpen }: { graph: Graph; onOpen: (m: 'graph' | 'catalog') => void }) {
  const s = graph.status
  const t = graph.totals
  const staleFiles = graph.nodes.filter((n) => n.type === 'artifact' && n.freshness === 'stale').length
  const card = (
    title: string,
    tool: string,
    field: StatusField | undefined,
    body: React.ReactNode,
    what: string,
    warn = false,
  ) => (
    <section className={`ov-card ${warn ? 'warn' : field?.ok === false ? 'bad' : ''}`}>
      <div className="ov-head">
        <span className={`dot ${warn ? 'warn' : field?.ok === true ? 'good' : field?.ok === false ? 'bad' : 'none'}`} />
        <h3>{title}</h3>
        <span className="ov-tool mono">{tool}</span>
      </div>
      <div className="ov-body">{body}</div>
      <p className="ov-what">{what}</p>
      {field?.next && <p className="ov-next">Next: <span className="mono">{field.next}</span></p>}
    </section>
  )
  return (
    <div className="overview">
      <div className="ov-grid">
        {card(
          'Claims in the paper',
          'repro',
          s?.repro,
          <>
            <div className="ov-big">{fmt(t.claims - t.failing)} / {fmt(t.claims)} <span>verified</span></div>
            <div className="ov-sub">{fmt(t.assertions)} checks over {fmt(t.artifacts)} files{graph.checked_at ? ` · checked ${when(graph.checked_at)}` : ''}</div>
            <button className="ov-link" onClick={() => onOpen('catalog')}>See them in the catalog →</button>
          </>,
          'Each claim is a sentence in the manuscript that repro.yaml declares. Most carry two checks: the sentence is still in the paper, and its number matches the file it came from.',
        )}
        {card(
          'Rebuild steps',
          'repro stale',
          { text: '', ok: true },
          <>
            <div className="ov-big">{staleFiles} <span>stale</span></div>
            <div className="ov-sub">{t.reruns} recorded re-runs</div>
            <button className="ov-link" onClick={() => onOpen('graph')}>See them on the graph →</button>
          </>,
          'A rebuild step is a declared command that makes a file. It is stale when its command, its inputs or its output changed since repro reproduce last re-ran it.',
          staleFiles > 0,
        )}
        {card(
          'Runs and their inputs',
          'results',
          s?.results,
          <div className="ov-big small-big">{s?.results?.text ?? '—'}</div>,
          'Each run recorded in the results ledger, and whether its inputs were sealed before it ran. A bound claim is a sentence tied to the run that produced its number with results claim, a separate record from the claims above.',
        )}
        {card(
          'Quotations from other papers',
          'citations',
          s?.citations,
          <div className="ov-big small-big">{s?.citations?.text ?? '—'}</div>,
          'Passages quoted from other people\'s work, each pinned to its source. Checking that every one still resolves reads every source, which takes minutes, so this count does not re-check them.',
        )}
        {card(
          'Preregistered plan',
          'prereg',
          s?.prereg,
          <div className="ov-big small-big">{s?.prereg?.text ?? '—'}</div>,
          'A plan frozen before the analysis it governs, against a commit and a content hash. Not every project has one.',
        )}
      </div>
    </div>
  )
}
