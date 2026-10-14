import { fmt, when } from './shared'
import type { Graph, StatusField } from './types'

type Tone = 'good' | 'warn' | 'bad' | 'none'

const tone = (f: StatusField | undefined): Tone => (f?.ok === true ? 'good' : f?.ok === false ? 'bad' : 'none')

interface Row {
  tool: string
  tone: Tone
  headline: string
  detail?: string
  what: string
  next?: string
  link?: [string, () => void]
}

/** The project's records laid out as the paper's commands figure is: the three tools that write
 * records on the left, the two fast checks that read them in the middle, the re-run on the right.
 * On a narrow window the columns stack in the same order. */
export default function Overview({ graph, onOpen }: { graph: Graph; onOpen: (m: 'graph' | 'catalog') => void }) {
  const s = graph.status
  const t = graph.totals
  const r = s?.results?.counts
  const rp = graph.reproduce
  const staleFiles = graph.nodes.filter((n) => n.type === 'artifact' && n.freshness === 'stale').length
  const needRerun = graph.nodes.filter((n) => n.type === 'artifact' && (n.freshness === 'stale' || n.freshness === 'never_rerun')).length
  const day = (ts: string) => new Date(ts).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
  const summary: [string, string, Tone, string?][] = [
    ['prereg', s?.prereg?.text ?? '—', tone(s?.prereg), s?.prereg?.next],
    ['results', r ? `${fmt(r.sealed)}/${fmt(r.runs)} runs sealed` : s?.results?.text ?? '—', tone(s?.results)],
    ['citations', s?.citations?.counts ? `${fmt(s.citations.counts.pinned)} quotes pinned, not verified` : s?.citations?.text ?? '—', tone(s?.citations), s?.citations?.next],
    ['repro verify', `${fmt(t.claims - t.failing)}/${fmt(t.claims)} claims verified (${fmt(t.assertions)} checks)`, t.failing ? 'bad' : 'good'],
    ['repro reproduce', rp?.runs
      ? `${fmt(rp.last.reproduced ?? 0)}/${fmt(rp.last_steps)} reproduced ${rp.last_at ? day(rp.last_at) : ''}${needRerun ? ` · ${needRerun} of ${fmt(rp.declared)} steps need re-running` : ''}`
      : 'never run', needRerun ? 'warn' : rp?.runs ? 'good' : 'none'],
  ]
  const failedReruns = rp ? Object.entries(rp.last).filter(([k]) => k !== 'reproduced').reduce((a, [, v]) => a + v, 0) : 0

  const columns: { title: string; sub: string; rows: Row[] }[] = [
    {
      title: 'Records',
      sub: 'written as the work happens',
      rows: [
        {
          tool: 'prereg', tone: tone(s?.prereg),
          headline: s?.prereg?.text === 'none drafted' ? 'no plan drafted' : s?.prereg?.text ?? '—',
          what: 'The plan, frozen before the analysis it governs against a commit and a content hash. Optional.',
          next: s?.prereg?.next,
        },
        {
          tool: 'results', tone: tone(s?.results),
          headline: r ? `${fmt(r.sealed)}/${fmt(r.runs)} runs sealed` : s?.results?.text ?? '—',
          detail: r?.changed ? `${fmt(r.changed)} sealed files changed` : undefined,
          what: 'The runs recorded in the ledger. A sealed run had its inputs hashed before it ran.',
        },
        {
          tool: 'citations', tone: tone(s?.citations),
          headline: s?.citations?.counts ? `${fmt(s.citations.counts.pinned)} quotes pinned, not verified` : s?.citations?.text ?? '—',
          what: "Passages quoted from other people's work, each pinned to its source. Not re-checked here: that reads every source and takes minutes.",
          next: s?.citations?.next,
        },
      ],
    },
    {
      title: 'Checks',
      sub: 'seconds, every commit',
      rows: [
        {
          tool: 'repro verify', tone: t.failing ? 'bad' : 'good',
          headline: `${fmt(t.claims - t.failing)}/${fmt(t.claims)} claims verified`,
          detail: `${fmt(t.assertions)} checks over ${fmt(t.artifacts)} files${graph.checked_at ? ` · ${when(graph.checked_at)}` : ''}`,
          what: "Each claim is a sentence of the paper that repro.yaml declares, checked against the file it came from. The paper's own sentences, not the quotations above.",
          link: ['Open the catalog', () => onOpen('catalog')],
        },
        {
          tool: 'repro stale', tone: needRerun ? 'warn' : 'good',
          headline: needRerun ? `${needRerun} of ${fmt(rp?.declared ?? 0)} steps need re-running` : 'every rebuild step matches its last re-run',
          detail: needRerun ? `${staleFiles} changed since the last re-run · ${needRerun - staleFiles} added since and never run` : undefined,
          what: 'A rebuild step is a declared command that turns input files into an output file, such as detex.py or a derive script. This compares each step with the last re-run without running anything.',
          link: ['Open the graph', () => onOpen('graph')],
        },
      ],
    },
    {
      title: 'Re-run',
      sub: 'minutes to hours, now and then',
      rows: [
        {
          tool: 'repro reproduce',
          tone: !rp?.runs ? 'none' : failedReruns ? 'bad' : 'good',
          headline: rp?.runs
            ? `${fmt(rp.last.reproduced ?? 0)}/${fmt(rp.last_steps)} steps reproduced on ${rp.last_at ? day(rp.last_at) : '—'}`
            : 'never run',
          detail: rp?.runs
            ? `last re-run ${rp.last_at ? when(rp.last_at) : ''} · ${fmt(rp.runs)} recorded · ${fmt(rp.declared)} steps declared now`
            : undefined,
          what: 'Runs every declared rebuild step again and checks that the output, and the numbers the paper prints from it, still come out the same.',
        },
      ],
    },
  ]

  return (
    <div className="overview">
      <div className="ov-summary mono">
        {summary.map(([cmd, text, tn, next]) => (
          <div key={cmd} className={`ov-line ${tn}`}>
            <span className={`dot ${tn}`} />
            <span className="ov-cmd">{cmd}:</span> {text}
            {next && <span className="ov-next"> → {next}</span>}
          </div>
        ))}
      </div>
      <div className="ov-cols">
        {columns.map((col, i) => (
          <div key={col.title} className="ov-col">
            <div className="ov-colhead">
              <span className="ov-coltitle">{col.title}</span>
              <span className="muted small">{col.sub}</span>
            </div>
            {col.rows.map((row) => (
              <section key={row.tool} className={`ov-row ${row.tone}`}>
                <div className="ov-main">
                  <div className="ov-headline">
                    <span className={`dot ${row.tone}`} />
                    <span className="mono ov-name">{row.tool}</span>
                  </div>
                  <div className="ov-big2">{row.headline}</div>
                  {row.detail && <div className="ov-sub">{row.detail}</div>}
                  <p className="ov-what">{row.what}</p>
                  <div className="ov-actions">
                    {row.next && <span className="ov-next">Next: <span className="mono">{row.next}</span></span>}
                    {row.link && <button className="ov-link" onClick={row.link[1]}>{row.link[0]} →</button>}
                  </div>
                </div>
              </section>
            ))}
            {i < columns.length - 1 && <div className="ov-arrow" aria-hidden>→</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
