import { statusLines, type StatusKey } from './format'
import type { Graph } from './types'

export type Tab = 'overview' | 'prereg' | 'results' | 'citations' | 'claims' | 'reproduce' | 'graph'

/** The tab each status line opens. */
export const TAB_OF: Record<StatusKey, Tab> = {
  prereg: 'prereg', results: 'results', citations: 'citations', claims: 'claims', repro: 'reproduce',
}
const TAB_NAME: Record<string, string> = { prereg: 'Prereg', results: 'Results', citations: 'Citations', claims: 'Claims', reproduce: 'Reproduce' }

/** The five lines, one per record, in the order prereg, results, citations, claims, repro. Each opens its tab. */
export default function Overview({ graph, onOpen }: { graph: Graph; onOpen: (m: Tab) => void }) {
  return (
    <div className="overview">
      <div className="ov-summary mono">
        <div className="ov-proj">{graph.project_name}</div>
        {statusLines(graph.status).map((l) => (
          <button key={l.key} className={`ov-line ${l.tone}`} onClick={() => onOpen(TAB_OF[l.key])} title={`Open ${TAB_NAME[TAB_OF[l.key]]}`}>
            <span className={`dot ${l.tone}`} />
            <span className="ov-cmd">{l.key}:</span> {l.text}
            {l.next && <span className="ov-next">  →  {l.next}</span>}
            <span className="ov-go">{TAB_NAME[TAB_OF[l.key]]} →</span>
          </button>
        ))}
      </div>
      <p className="ov-hint">The first three are records written as the work happens. repro verify checks every claim against them in seconds, on every commit. repro reproduce re-runs the code, now and then. The graph shows how files, claims and rebuild steps connect.</p>
    </div>
  )
}
