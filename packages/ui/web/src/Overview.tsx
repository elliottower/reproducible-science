import { fmt } from './shared'
import type { Graph, StatusField } from './types'

type Tone = 'good' | 'warn' | 'bad' | 'none'
export type Tab = 'overview' | 'prereg' | 'results' | 'citations' | 'claims' | 'reproduce' | 'graph'

const tone = (f: StatusField | undefined): Tone => (f?.ok === true ? 'good' : f?.ok === false ? 'bad' : 'none')

/** The five lines, one per command, in the order of the paper's commands figure. Each opens its tab. */
export default function Overview({ graph, onOpen }: { graph: Graph; onOpen: (m: Tab) => void }) {
  const s = graph.status
  const t = graph.totals
  const r = s?.results?.counts
  const rp = graph.reproduce
  const needRerun = graph.nodes.filter((n) => n.type === 'artifact' && (n.freshness === 'stale' || n.freshness === 'never_rerun')).length
  const day = (ts: string) => new Date(ts).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
  const lines: [string, string, Tone, Tab, string?][] = [
    ['prereg', s?.prereg?.text ?? '—', tone(s?.prereg), 'prereg', s?.prereg?.next],
    ['results', r ? `${fmt(r.sealed)}/${fmt(r.runs)} runs sealed` : s?.results?.text ?? '—', tone(s?.results), 'results'],
    ['citations', s?.citations?.counts ? `${fmt(s.citations.counts.pinned)} quotes pinned, not verified` : s?.citations?.text ?? '—', tone(s?.citations), 'citations', s?.citations?.next],
    ['repro verify', `${fmt(t.claims - t.failing)}/${fmt(t.claims)} claims verified (${fmt(t.assertions)} checks)`, t.failing ? 'bad' : 'good', 'claims'],
    ['repro reproduce', rp?.runs
      ? `${fmt(rp.last.reproduced ?? 0)}/${fmt(rp.last_steps)} reproduced ${rp.last_at ? day(rp.last_at) : ''}${needRerun ? ` · ${needRerun} of ${fmt(rp.declared)} steps need re-running` : ''}`
      : 'never run', needRerun ? 'warn' : rp?.runs ? 'good' : 'none', 'reproduce'],
  ]
  return (
    <div className="overview">
      <div className="ov-summary mono">
        <div className="ov-proj">{graph.project_name}</div>
        {lines.map(([cmd, text, tn, tab, next]) => (
          <button key={cmd} className={`ov-line ${tn}`} onClick={() => onOpen(tab)} title={`Open ${tab}`}>
            <span className={`dot ${tn}`} />
            <span className="ov-cmd">{cmd}:</span> {text}
            {next && <span className="ov-next"> → {next}</span>}
            <span className="ov-go">open →</span>
          </button>
        ))}
      </div>
      <p className="ov-hint">The first three are records written as the work happens. repro verify checks every claim against them in seconds, on every commit. repro reproduce re-runs the code, now and then. The graph shows how files, claims and rebuild steps connect.</p>
    </div>
  )
}
