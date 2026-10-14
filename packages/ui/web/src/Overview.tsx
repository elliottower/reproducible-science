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
      headline: s?.prereg?.text === 'none drafted' ? 'No plan drafted' : s?.prereg?.text ?? '—',
      what: 'A plan frozen before the analysis it governs, against a commit and a content hash. Optional: a project without one is not failing.',
      next: s?.prereg?.next,
    },
    {
      step: '2', title: 'Runs', tool: 'results', tone: tone(s?.results),
      headline: r ? `${fmt(r.sealed)} of ${fmt(r.runs)} runs had their inputs sealed first` : s?.results?.text ?? '—',
      detail: `${fmt(t.run_backed ?? 0)} of ${fmt(t.claims)} claims read a number from a file a recorded run wrote${r?.changed ? ` · ${fmt(r.changed)} sealed files changed` : ''}`,
      what: 'Every run recorded in the results ledger. Sealing hashes a run\'s inputs before it runs. A claim is backed by a run when the file it reads was written by one; the other claims read files pinned by hash with no run recorded.',
    },
    {
      step: '3', title: 'Claims in the paper', tool: 'repro verify', tone: t.failing ? 'bad' : 'good',
      headline: `${fmt(t.claims - t.failing)} of ${fmt(t.claims)} claims verified`,
      detail: `${fmt(t.assertions)} checks over ${fmt(t.artifacts)} files${graph.checked_at ? ` · checked ${when(graph.checked_at)}` : ''}`,
      what: 'Each claim is a sentence repro.yaml declares. Most carry two checks: the sentence is still in the paper, and its number matches the file it came from.',
      link: ['Open the catalog', () => onOpen('catalog')],
    },
    {
      step: '4', title: 'Quotations', tool: 'citations', tone: tone(s?.citations),
      headline: s?.citations?.counts ? `${fmt(s.citations.counts.pinned)} quotations pinned to their sources` : s?.citations?.text ?? '—',
      detail: s?.citations?.counts ? 'Not re-checked here: that reads every source and takes minutes' : undefined,
      what: "Passages quoted from other people's work, each pinned to the source it comes from.",
      next: s?.citations?.next,
    },
    {
      step: '5', title: 'Rebuild steps', tool: 'repro stale', tone: staleFiles ? 'warn' : 'good',
      headline: staleFiles ? `${staleFiles} stale since their last re-run` : 'All match their last re-run',
      detail: `${t.reruns} recorded re-runs`,
      what: 'A rebuild step is a declared command that makes a file. It is stale when its command, inputs or output changed since repro reproduce last re-ran it.',
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
              <div className="ov-title">
                <span className={`dot ${row.tone}`} />
                <h3>{row.title}</h3>
                <span className="ov-tool mono">{row.tool}</span>
              </div>
              <div className="ov-headline">{row.headline}</div>
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
