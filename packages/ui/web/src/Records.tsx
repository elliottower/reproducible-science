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

const STOP = new Set(['about', 'after', 'their', 'there', 'these', 'those', 'which', 'while', 'where', 'other', 'being', 'paper', 'results'])

/** The quote with every word it shares with the manuscript's sentences marked, so a reader sees at a
 * glance which words the paper carried over. Words of five letters or more, common ones left out. */
function Marked({ text, against }: { text: string; against: Set<string> }) {
  const parts = text.split(/(\s+)/)
  return (
    <>
      {parts.map((w, i) => {
        const key = w.toLowerCase().replace(/[^a-z0-9-]/g, '')
        return key.length >= 5 && !STOP.has(key) && against.has(key) ? <mark key={i}>{w}</mark> : <span key={i}>{w}</span>
      })}
    </>
  )
}

/** What the person who pinned the quotes wrote about the source: where the paper's reading and the
 * source differ, what the quote does not show, or where the words came from. Shown, because it is
 * the evidence that someone read the source. */
function Note({ text }: { text: string }) {
  return (
    <div className="note-wrap">
      <span className="note-label">Note</span>
      <div className="cite-note">{text}</div>
    </div>
  )
}

type Source = NonNullable<Graph['tabs']>['citations']['sources'][number]

/** "Abeysooriya et al. 2021" from a .bib author field, or the organization's name when it is one. */
function byline(s: Source): string {
  const names = (s.bib.author ?? '').split(/\s+and\s+/).filter(Boolean)
  const surname = (n: string) => (n.includes(',') ? n.split(',')[0] : n.split(' ').slice(-1)[0]).trim()
  const who = names.length === 0 ? '' : names.length === 1 ? (names[0].includes(',') ? surname(names[0]) : names[0]) : names.length === 2 ? `${surname(names[0])} and ${surname(names[1])}` : `${surname(names[0])} et al.`
  return [who, s.bib.year].filter(Boolean).join(' ')
}

function SourceCell({ s, onOpen }: { s: Source; onOpen: (s: Source) => void }) {
  return (
    <div className="src-cell">
      <button className="src-title" onClick={() => onOpen(s)} title="Details">{s.bib.title || s.citation}</button>
      <div className="small muted">{byline(s)}{s.link && <> · <a className="src-link" href={s.link} target="_blank" rel="noreferrer">open ↗</a></>}</div>
      <div className="src-meta">
        <span className="mono">{s.citation}</span>
        {s.sha256 ? <span className="pin" title={`${s.local} · sha256 ${s.sha256.slice(0, 12)}…`}>Pinned</span> : <span className="pin bad">Not pinned</span>}
      </div>
    </div>
  )
}

function SourcePanel({ s, onClose }: { s: Source; onClose: () => void }) {
  const venue = s.bib.journal || s.bib.booktitle || s.bib.publisher || s.bib.howpublished || s.bib.organization || ''
  return (
    <aside className="panel">
      <button className="close" onClick={onClose}>×</button>
      <div className="kicker">SOURCE</div>
      <h2>{s.bib.title || s.citation}</h2>
      {s.link && <p><a className="src-link" href={s.link} target="_blank" rel="noreferrer">Open the source ↗</a></p>}
      <dl>
        {s.bib.author && (<><dt>Authors</dt><dd>{s.bib.author.split(/\s+and\s+/).join('; ')}</dd></>)}
        {s.bib.year && (<><dt>Year</dt><dd>{s.bib.year}</dd></>)}
        {venue && (<><dt>Venue</dt><dd>{venue}</dd></>)}
        {s.bib.doi && (<><dt>DOI</dt><dd className="mono small">{s.bib.doi}</dd></>)}
        {s.link && (<><dt>Link</dt><dd><a className="src-link" href={s.link} target="_blank" rel="noreferrer">{s.link}</a></dd></>)}
        <dt>Key</dt><dd className="mono">{s.citation}</dd>
        <dt>Pinned</dt><dd>{s.sha256 ? <><span className="mono small">{s.local}</span><div className="mono small muted">sha256 {s.sha256}</div></> : 'Not pinned'}</dd>
        <dt>Claims file</dt><dd className="mono small">{s.file}</dd>
      </dl>
      <h3>{s.pinned} quotation{s.pinned === 1 ? '' : 's'} · cited {s.cited_in.length === 1 ? 'once' : `${s.cited_in.length} times`}</h3>
      {s.cited_in.map((c, k) => (
        <div key={k} className="ms-sentence">“{c.text}”{c.section && <div className="muted">(section: {c.section})</div>}</div>
      ))}
    </aside>
  )
}

function Quotes({ st, words }: { st: Source['statements'][number]; words: Set<string> }) {
  return (
    <>
      {st.quotes.map((qq, k) => (
        <div key={k} className="src-words">
          <span className="quote">“<Marked text={qq.exact} against={words} />”</span>
          {qq.section && <div className="muted small">(section: {qq.section})</div>}
        </div>
      ))}
    </>
  )
}

function Interpretation({ st }: { st: Source['statements'][number] }) {
  return (
    <>
      {st.statement}
      {st.notes && <Note text={st.notes} />}
    </>
  )
}

const sentenceWords = (texts: string[]) =>
  new Set(texts.flatMap((t) => t.toLowerCase().split(/\s+/).map((w) => w.replace(/[^a-z0-9-]/g, ''))))

function CitationsByClaim({ graph, query, onOpen }: { graph: Graph; query: string; onOpen: (s: Source) => void }) {
  const q = query.trim().toLowerCase()
  const sources = (graph.tabs?.citations.sources ?? []).filter((s) => !q || JSON.stringify(s).toLowerCase().includes(q))
  const [groupBy, setGroupBy] = useState<'source' | 'section'>('source')
  const [openSecs, setOpenSecs] = useState<Set<string>>(new Set())
  const flipSec = (n: string) => setOpenSecs((prev) => { const x = new Set(prev); if (x.has(n)) x.delete(n); else x.add(n); return x })
  const head = (
    <thead><tr><th style={{ width: '16%' }}>Source</th><th style={{ width: '28%' }}>Source quotations</th><th style={{ width: '20%' }}>Interpretation</th><th>
      <div className="ms-grid ms-grid-head"><span>Manuscript text</span><span>Manuscript section</span></div>
    </th></tr></thead>
  )
  const switcher = (
    <div className="seg-right">
      {groupBy === 'section' && (
        <>
          <button className="link-btn" onClick={() => setOpenSecs(new Set([...Array.from({ length: 200 }, (_, i) => `${i}`), 'uncited']))}>Expand all</button>
          <button className="link-btn" onClick={() => setOpenSecs(new Set())}>Collapse all</button>
        </>
      )}
      <span className="muted small">Group by</span>
      <div className="seg small-seg">
        <button className={groupBy === 'source' ? 'on' : ''} onClick={() => setGroupBy('source')}>Source</button>
        <button className={groupBy === 'section' ? 'on' : ''} onClick={() => setGroupBy('section')}>Manuscript section</button>
      </div>
    </div>
  )

  if (groupBy === 'section') {
    // Every citing sentence, in reading order, under the section it sits in.
    const items = sources.flatMap((s) => s.cited_in.map((c) => ({ s, c })))
      .sort((a, b) => a.c.order[0] - b.c.order[0] || a.c.order[1] - b.c.order[1])
    const sections: { name: string; items: typeof items }[] = []
    for (const it of items) {
      const name = it.c.section || 'Before the first section'
      const last = sections[sections.length - 1]
      if (last && last.name === name) last.items.push(it)
      else sections.push({ name, items: [it] })
    }
    const uncited = sources.filter((s) => s.cited_in.length === 0)
    return (
      <>
        {switcher}
        <table className="cite-table">
          {head}
          <tbody>
            {sections.map((sec, si) => (
              <Fragment key={`sec-${si}`}>
                <tr className={`sec-head clickable ${openSecs.has(`${si}`) ? 'open' : ''}`} onClick={() => flipSec(`${si}`)}>
                  <td colSpan={4}>
                    <span className="sec-caret">{openSecs.has(`${si}`) ? '▾' : '▸'}</span> {sec.name}
                    <span className="sec-count"> · {sec.items.length} citation{sec.items.length === 1 ? '' : 's'} · {new Set(sec.items.map((x) => x.s.citation)).size} source{new Set(sec.items.map((x) => x.s.citation)).size === 1 ? '' : 's'}</span>
                  </td>
                </tr>
                {openSecs.has(`${si}`) && sec.items.map(({ s, c }, k) => {
                  const words = sentenceWords([c.text])
                  return (
                    <tr key={`${si}-${k}`} className="static src-start">
                      <td><SourceCell s={s} onOpen={onOpen} /></td>
                      <td>{s.statements.map((st) => <Quotes key={st.id} st={st} words={words} />)}</td>
                      <td className="small">{s.statements.map((st) => <div key={st.id} className="interp-block"><Interpretation st={st} /></div>)}</td>
                      <td className="small"><div className="ms-sentence">“{c.text}”</div></td>
                    </tr>
                  )
                })}
              </Fragment>
            ))}
            {uncited.length > 0 && (
              <Fragment key="uncited">
                <tr className={`sec-head clickable ${openSecs.has('uncited') ? 'open' : ''}`} onClick={() => flipSec('uncited')}>
                  <td colSpan={4}>
                    <span className="sec-caret">{openSecs.has('uncited') ? '▾' : '▸'}</span> Not cited in any .tex file
                    <span className="sec-count"> · {uncited.length} source{uncited.length === 1 ? '' : 's'} · {uncited.reduce((a, s) => a + s.pinned, 0)} quotations</span>
                  </td>
                </tr>
                {openSecs.has('uncited') && uncited.map((s) => (
                  <tr key={s.file} className="static src-start">
                    <td><SourceCell s={s} onOpen={onOpen} /></td>
                    <td>{s.statements.map((st) => <Quotes key={st.id} st={st} words={new Set()} />)}</td>
                    <td className="small">{s.statements.map((st) => <div key={st.id} className="interp-block"><Interpretation st={st} /></div>)}</td>
                    <td className="small muted">Not cited in any .tex file repro.yaml pins.</td>
                  </tr>
                ))}
              </Fragment>
            )}
          </tbody>
        </table>
      </>
    )
  }

  return (
    <>
      {switcher}
      <table className="cite-table">
        {head}
        <tbody>
          {sources.map((s) => {
            const words = sentenceWords(s.cited_in.map((c) => c.text))
            return s.statements.map((st, i) => (
              <tr key={`${s.file}-${st.id}`} className={`static ${i === 0 ? 'src-start' : ''}`}>
                {i === 0 && <td rowSpan={s.statements.length}><SourceCell s={s} onOpen={onOpen} /></td>}
                <td><Quotes st={st} words={words} /></td>
                <td className="small"><Interpretation st={st} /></td>
                {i === 0 && (
                  <td rowSpan={s.statements.length} className="small">
                    {s.cited_in.length ? s.cited_in.map((c, k) => (
                      <div key={k} className="ms-grid">
                        <span className="ms-sentence">“{c.text}”</span>
                        <span className="ms-section">{c.section || '—'}</span>
                      </div>
                    )) : <span className="muted">Not cited in any .tex file pinned in repro.yaml.</span>}
                  </td>
                )}
              </tr>
            ))
          })}
        </tbody>
      </table>
    </>
  )
}

export function CitationsTab({ graph, query }: { graph: Graph; query: string }) {
  const [panel, setPanel] = useState<Source | null>(null)
  return (
    <div className="rec">
      <Head cmd="citations" line={graph.status?.citations.text ?? '—'}
        what="Passages quoted from other people's work, the paper's interpretation of them, and the sentences of the manuscript that cite each source. Click a title for the source's details. Highlighted words appear in both the source and the manuscript. The interpretations and notes are ours; citations verify checks only the quoted passages. A source is pinned when its file is saved with a hash." />
      <CitationsByClaim graph={graph} query={query} onOpen={setPanel} />
      {panel && <SourcePanel s={panel} onClose={() => setPanel(null)} />}
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
