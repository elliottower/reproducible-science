import { fmt, when } from './shared'
import type { Graph, StatusField } from './types'

type Tone = 'good' | 'warn' | 'bad' | 'none'

const tone = (f: StatusField | undefined): Tone => (f?.ok === true ? 'good' : f?.ok === false ? 'bad' : 'none')

/** The project's records, in the order the work happens: the plan, the runs, the claims the
 * paper makes from them, the quotations it takes from others, and whether the rebuild steps still
 * match their last re-run. Each row says in words what its number counts. */
export default function Overview({ graph, onOpen }: { graph: Graph; onOpen: (m: 'graph' | 'catalog') => void }) {
  const s = graph.status
  const t = graph.totals
  const r = s?.results?.counts
  const staleFiles = graph.nodes.filter((n) => n.type === 'artifact' && n.freshness === 'stale').length

  const rows: { step: string; title: string; tool: string; tone: Tone; headline: string; detail?: string; what: string; next?: string; link?: [string, () => void] }[] = [
    {
      step: '1', title: 'Plan', tool: 'prereg', tone: tone(s?.prereg),
      headline: s?.prereg?.text === 'none drafted' ? 'no plan drafted' : s?.prereg?.text ?? '—',
      what: 'The plan, frozen before the analysis it governs against a commit and a content hash. Optional: a project without one is not failing.',
      next: s?.prereg?.next,
    },
    {
      step: '2', title: 'Runs', tool: 'results', tone: tone(s?.results),
      headline: r ? `${fmt(r.sealed)}/${fmt(r.runs)} runs sealed` : s?.results?.text ?? '—',
      detail: `${fmt(t.run_backed ?? 0)} of ${fmt(t.claims)} claims read a number from a file a recorded run wrote${r?.changed ? ` · ${fmt(r.changed)} sealed files changed` : ''}`,
      what: 'The runs recorded in the ledger. A sealed run had its inputs hashed before it ran. A claim is backed by a run when the file it reads was written by one; the other claims read files pinned by hash with no run recorded.',
    },
    {
      step: '3', title: 'Claims in the paper', tool: 'claims verify', tone: t.failing ? 'bad' : 'good',
      headline: `${fmt(t.claims - t.failing)}/${fmt(t.claims)} claims verified`,
      detail: `${fmt(t.assertions)} checks over ${fmt(t.artifacts)} files${graph.checked_at ? ` · checked ${when(graph.checked_at)}` : ''}`,
      what: 'The claims the paper makes: each a sentence repro.yaml declares. Same check as repro verify. Most carry two checks: the sentence is still in the paper, and its number matches the file it came from.',
      link: ['Open the catalog', () => onOpen('catalog')],
    },
    {
      step: '4', title: 'Quotations', tool: 'citations', tone: tone(s?.citations),
      headline: s?.citations?.counts ? `${fmt(s.citations.counts.pinned)} quotes pinned, not verified` : s?.citations?.text ?? '—',
      what: "Passages quoted from other people's work, each pinned to its source. Not re-checked here: that reads every source and takes minutes.",
      next: s?.citations?.next,
    },
    {
      step: '5', title: 'Rebuild steps', tool: 'claims stale', tone: staleFiles ? 'warn' : 'good',
      headline: staleFiles ? `${staleFiles} rebuild steps changed since their last re-run` : 'every rebuild step matches its last re-run',
      detail: `${t.reruns} recorded re-runs`,
      what: 'The declared commands that make files. A step is stale when its command, inputs or output changed since repro reproduce last re-ran it. Same check as repro stale.',
      link: ['Open the graph', () => onOpen('graph')],
    },
  ]

  return (
    <div className="overview">
      <div className="ov-list">
        {rows.map((row) => (
          <section key={row.step} className={`ov-row ${row.tone}`}>
            <div className="ov-step">{row.step}</div>
            <div className="ov-main">
              <div className="ov-headline">
                <span className={`dot ${row.tone}`} />
                <span className="mono ov-name">{row.tool}:</span> {row.headline}
              </div>
              {row.detail && <div className="ov-sub">{row.detail}</div>}
              <p className="ov-what">{row.what}</p>
              <div className="ov-actions">
                {row.next && <span className="ov-next">Next: <span className="mono">{row.next}</span></span>}
                {row.link && <button className="ov-link" onClick={row.link[1]}>{row.link[0]} →</button>}
              </div>
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
