import { Fragment, useEffect, useMemo, useState } from 'react'
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
  const [panel, setPanel] = useState<Run | null>(null)
  const q = query.trim().toLowerCase()
  const runs = useMemo(
    () => [...(t?.runs ?? [])].reverse().filter((r) => !q || `${r.run_id} ${r.note} ${r.outputs.join(' ')}`.toLowerCase().includes(q)),
    [t, q],
  )
  return (
    <div className="rec">
      <Head cmd="results" line={graph.status?.results.counts ? `${fmt(graph.status.results.counts.sealed)}/${fmt(graph.status.results.counts.runs)} runs sealed` : graph.status?.results.text ?? '—'}
        what="The results ledger, a hash chain of events. results seal hashes a run's inputs before it runs; results run records the files the run wrote, with their hashes. Click a run for its details, or a file to read it." />
      <table>
        <thead><tr><th>Run</th><th>Recorded</th><th>Inputs</th><th>Outputs</th><th>Files written</th><th>Outside records</th><th>Manuscript</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={`${r.run_id}${r.timestamp}`} className={`static ${panel === r ? 'sel' : ''}`}>
              <td className="clickable" onClick={() => setPanel(r)} title="Details">
                <button className="file-link mono strong">{r.run_id}</button>
                <div className="small muted claim-cell">{r.note}</div>
              </td>
              <td className="small nowrap">{when(r.timestamp)}</td>
              <td>{r.sealed_before ? <span className="pill good">Sealed</span> : <span className="pill bad">Not sealed</span>}</td>
              <td>{r.outputs.length ? <span className="pill good">Recorded</span> : <span className="pill bad">None</span>}</td>
              <td className="mono small">
                {r.outputs.map((o) => (
                  <div key={o}><button className="file-link" onClick={() => setViewing(o)}>{o}</button></div>
                ))}
              </td>
              <td className="small"><OutsideLinks r={r} /></td>
              <td className="small nowrap">{claimsReading(graph, r).length ? `${fmt(claimsReading(graph, r).length)} claims` : <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {viewing && <FileViewer path={viewing} onClose={() => setViewing(null)} />}
      {panel && <RunPanel graph={graph} r={panel} onClose={() => setPanel(null)} onView={setViewing} />}
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

type Run = NonNullable<Graph['tabs']>['results']['runs'][number]

/** The manuscript claims that read a file this run wrote. */
function claimsReading(graph: Graph, r: Run) {
  const paths = new Set(r.outputs)
  return graph.nodes.filter((n) => n.type === 'artifact' && n.path && paths.has(n.path)).flatMap((n) => n.claims)
}

/** The run's links to records outside the ledger: a W&B run the ledger names, and every
 * `results annotate` link on one of its files. A dash when there are none. */
function OutsideLinks({ r }: { r: Run }) {
  const links = r.links ?? []
  if (!r.wandb_url && links.length === 0) return <span className="muted">—</span>
  return (
    <>
      {r.wandb_url && <div><a className="src-link" href={r.wandb_url} target="_blank" rel="noreferrer" title={r.wandb_url}>W&amp;B run ↗</a></div>}
      {links.map((l, i) => (
        <div key={i}>
          {l.url && !/doi\.org\//.test(l.url)
            ? <a className="src-link" href={l.url} target="_blank" rel="noreferrer" title={l.ref}>{kindLabel(l.kind)} ↗</a>
            : <span title={l.ref}>{kindLabel(l.kind)}</span>}
        </div>
      ))}
    </>
  )
}

/** The commit holding the bytes the run recorded, linked when the project has a remote, and the
 * run's W&B page when the ledger names one. A run whose bytes no commit holds says so. */
function CommitCell({ r }: { r: Run }) {
  const short = r.commit?.slice(0, 7)
  return (
    <>
      {!short ? <span className="muted">not committed</span>
        : r.remote_url ? <a className="src-link" href={r.remote_url} target="_blank" rel="noreferrer" title={r.commit ?? ''}>{short}</a>
        : <span title={r.commit ?? ''}>{short}</span>}
      {short && !r.committed && <div className="muted">some outputs not committed</div>}
      {r.wandb_url && <div><a className="src-link" href={r.wandb_url} target="_blank" rel="noreferrer" title={r.wandb_url}>W&amp;B</a></div>}
    </>
  )
}

/** "W&B run", "DOI dataset" from a `namespace:type` kind such as wandb:run or doi:dataset. */
function kindLabel(kind: string): string {
  const [ns, type] = kind.split(':')
  const name: Record<string, string> = { wandb: 'W&B', mlflow: 'MLflow', doi: 'DOI', zenodo: 'Zenodo', osf: 'OSF', hf: 'Hugging Face' }
  return `${name[ns] ?? ns} ${type ?? ''}`.trim()
}

/** One run: its note, when it ran, the commit holding its bytes, each file it wrote, the records
 * outside the ledger it was linked to, and the manuscript claims that read its files. */
function RunPanel({ graph, r, onClose, onView }: { graph: Graph; r: Run; onClose: () => void; onView: (path: string) => void }) {
  const [allClaims, setAllClaims] = useState(false)
  const files = r.files ?? r.outputs.map((path) => ({ path, sha256: '', on_disk: true }))
  const claims = claimsReading(graph, r)
  const shown = allClaims ? claims : claims.slice(0, 20)
  return (
    <aside className="panel">
      <button className="close" onClick={onClose}>×</button>
      <div className="kicker">RUN</div>
      <h2 className="mono">{r.run_id}</h2>
      {r.note && <p className="small">{r.note}</p>}
      <dl>
        <dt>Recorded</dt><dd>{when(r.timestamp)}</dd>
        <dt>Inputs</dt><dd>{r.sealed_before ? 'Sealed before the run' : 'Nothing sealed before the run'}</dd>
        <dt>Commit</dt><dd className="mono small"><CommitCell r={r} /></dd>
      </dl>
      <h3>{files.length} file{files.length === 1 ? '' : 's'} written</h3>
      {files.map((f) => (
        <div key={f.path} className="run-file">
          <button className="file-link mono small" onClick={() => onView(f.path)}>{f.path}</button>
          {f.sha256 && <div className="mono small muted">sha256 {f.sha256}</div>}
          {!f.on_disk && <div className="small stale-text">The file on disk is no longer these bytes.</div>}
        </div>
      ))}
      <h3>Outside records</h3>
      {(r.links ?? []).length === 0 ? (
        <p className="small muted">None linked. <span className="mono">results annotate --kind wandb:run --ref &lt;url&gt; &lt;file&gt;</span> links a file to a W&amp;B run, a DOI or another record.</p>
      ) : (r.links ?? []).map((l, i) => (
        <div key={i} className="run-link">
          <span className="lab">{kindLabel(l.kind)}</span>{' '}
          {l.url && !/doi\.org\//.test(l.url)
            ? <a className="src-link" href={l.url} target="_blank" rel="noreferrer" title={l.url}>{l.ref} ↗</a>
            : <span className="mono small">{l.ref}</span>}
          <div className="small muted">Linked, not checked{l.same_bytes ? '' : ', and stated of other bytes than this run wrote'}{l.by ? ` · by ${l.by}` : ''}</div>
          {l.note && <div className="small">{l.note}</div>}
        </div>
      ))}
      <h3>{claims.length ? `${fmt(claims.length)} manuscript claim${claims.length === 1 ? '' : 's'} read these files` : 'No manuscript claim reads these files'}</h3>
      {shown.map((c) => (
        <div key={c.id} className="run-claim small">
          <span className={c.ok ? 'good-text' : 'stale-text'}>{c.ok ? '✓' : '✗'}</span> {c.text} <span className="muted">({c.where})</span>
        </div>
      ))}
      {claims.length > shown.length && <button className="link-btn" onClick={() => setAllClaims(true)}>Show all {fmt(claims.length)}</button>}
    </aside>
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

/** Where a link goes: the site's base address (github.com, aclanthology.org, arxiv.org), so a
 * reader sees the site itself. A raw file on GitHub reads as github.com. */
function linkLabel(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '')
    return /githubusercontent\.com$/.test(host) ? 'github.com' : host
  } catch {
    return 'link'
  }
}

/** The source's DOI: the .bib entry's, or the one in the claims file's address when that is a doi.org link. */
function doiOf(s: Source): string {
  return s.bib.doi || (s.url.match(/doi\.org\/(10\.[^\s?#]+)/)?.[1] ?? '')
}

function SourceCell({ s, files, onOpen }: { s: Source; files?: Source[]; onOpen: (s: Source) => void }) {
  const all = files ?? [s]
  const pinned = all.every((f) => f.sha256)
  return (
    <div className="src-cell">
      <button className="src-title" onClick={() => onOpen(s)} title="Details">{s.bib.title || s.citation}</button>
      <div className="small muted">{byline(s)}</div>
      <div className="src-rows small">
        <span className="lab">Link:</span>
        {s.link ? <a className="src-link" href={s.link} target="_blank" rel="noreferrer" title={s.link}>{linkLabel(s.link)}</a> : <span className="muted">none</span>}
        <span className="lab">DOI:</span>
        {doiOf(s)
          ? (s.doi_link && !/doi\.org\//.test(s.doi_link)
              ? <a className="src-link mono" href={s.doi_link} target="_blank" rel="noreferrer" title={s.doi_link}>{doiOf(s)}</a>
              : <span className="mono">{doiOf(s)}</span>)
          : <span className="muted">No DOI</span>}
        <span className="lab">Key:</span>
        <span className="mono">{s.citation}</span>
      </div>
      <div className="src-meta">
        {pinned ? (
          <span className="pin" title={all.map((f) => `${f.local} · sha256 ${f.sha256.slice(0, 12)}…`).join('\n')}>
            {all.length > 1 ? `${all.length} files pinned` : 'Pinned'}
          </span>
        ) : <span className="pin bad">Not pinned</span>}
      </div>
    </div>
  )
}

function SourcePanel({ s, onClose, onGo }: { s: Source; onClose: () => void; onGo?: (key: string, c: Source['cited_in'][number]) => void }) {
  const venue = s.bib.journal || s.bib.booktitle || s.bib.publisher || s.bib.howpublished || s.bib.organization || ''
  return (
    <aside className="panel">
      <button className="close" onClick={onClose}>×</button>
      <div className="kicker">SOURCE</div>
      <h2>{s.bib.title || s.citation}</h2>
      {s.link && <p><a className="src-link" href={s.link} target="_blank" rel="noreferrer" title={s.link}>View source ↗</a></p>}
      <dl>
        {s.bib.author && (<><dt>Authors</dt><dd>{s.bib.author.split(/\s+and\s+/).join('; ')}</dd></>)}
        {s.bib.year && (<><dt>Year</dt><dd>{s.bib.year}</dd></>)}
        {venue && (<><dt>Venue</dt><dd>{venue}</dd></>)}
        <dt>Link</dt>
        <dd>{s.link ? <a className="src-link" href={s.link} target="_blank" rel="noreferrer" title={s.link}>{linkLabel(s.link)}</a> : <span className="muted">none</span>}</dd>
        <dt>DOI</dt>
        <dd>
          {doiOf(s)
            ? (s.doi_link && !/doi\.org\//.test(s.doi_link)
                ? <a className="src-link mono small" href={s.doi_link} target="_blank" rel="noreferrer" title={s.doi_link}>{doiOf(s)}</a>
                : <span className="mono small">{doiOf(s)}</span>)
            : <span className="muted">No DOI</span>}
        </dd>
        <dt>Key</dt><dd className="mono">{s.citation}</dd>
        <dt>Pinned</dt><dd>{s.sha256 ? <><span className="mono small">{s.local}</span><div className="mono small muted">sha256 {s.sha256}</div></> : 'Not pinned'}</dd>
        <dt>Claims file</dt><dd className="mono small">{s.file}</dd>
      </dl>
      <h3>{s.pinned} quotation{s.pinned === 1 ? '' : 's'} pinned</h3>
      <h3>{s.cited_in.length ? `Referenced ${s.cited_in.length === 1 ? 'once' : `${s.cited_in.length} times`} in the manuscript` : 'Not referenced in the manuscript'}</h3>
      {s.cited_in.map((c, k) => (
        <button key={k} className="ms-ref" onClick={() => onGo?.(s.citation, c)} title="Show it on the page">
          <span className="ms-sentence">“{c.text}”</span>
          {c.section && <span className="muted small">(section: {c.section}) · show it →</span>}
        </button>
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

function CitationsByClaim({ graph, query, onOpen, focus }: {
  graph: Graph
  query: string
  onOpen: (s: Source) => void
  focus?: { key: string; order: string; at: number } | null
}) {
  const q = query.trim().toLowerCase()
  const sources = (graph.tabs?.citations.sources ?? []).filter((s) => !q || JSON.stringify(s).toLowerCase().includes(q))
  const groupBy = 'section' as 'source' | 'section'
  // Every section starts closed, so the page opens on the list of sections.
  const [openSecs, setOpenSecs] = useState<Set<string>>(new Set())
  const flipSec = (n: string) => setOpenSecs((prev) => { const x = new Set(prev); if (x.has(n)) x.delete(n); else x.add(n); return x })
  const head = (
    <thead><tr><th style={{ width: '16%' }}>Source</th><th style={{ width: '28%' }}>Source quotations</th><th style={{ width: '20%' }}>Interpretation</th><th>Manuscript text</th></tr></thead>
  )
  const switcher = (
    <div className="seg-right">
      <button className="link-btn" onClick={() => setOpenSecs(new Set([...Array.from({ length: 200 }, (_, i) => `${i}`), 'uncited']))}>Expand all</button>
      <button className="link-btn" onClick={() => setOpenSecs(new Set())}>Collapse all</button>
    </div>
  )

  if (groupBy === 'section') {
    // Every citing sentence, in reading order, under the section it sits in. A key whose quotes live
    // in several claims files (Paperclip's docs, map and README) is one source here.
    type Item = { key: string; c: Source['cited_in'][number]; files: Source[] }
    const byKey = new Map<string, Item>()
    for (const s of sources) {
      for (const c of s.cited_in) {
        const k = `${s.citation}::${c.file}::${c.order.join(',')}`
        const it = byKey.get(k)
        if (it) it.files.push(s)
        else byKey.set(k, { key: s.citation, c, files: [s] })
      }
    }
    const items = [...byKey.values()].sort((a, b) => a.c.order[0] - b.c.order[0] || a.c.order[1] - b.c.order[1])
    const sections: { name: string; items: Item[] }[] = []
    for (const it of items) {
      const name = it.c.section || 'Before the first section'
      const last = sections[sections.length - 1]
      if (last && last.name === name) last.items.push(it)
      else sections.push({ name, items: [it] })
    }
    const uncited = sources.filter((s) => s.cited_in.length === 0)
    const rowId = (it: Item) => `cite-${it.key}-${it.c.order.join('-')}`
    // A reference picked in the source panel: open its section, scroll to it, and flash it.
    useEffect(() => {
      if (!focus) return
      const si = sections.findIndex((sec) => sec.items.some((it) => it.key === focus.key && it.c.order.join(',') === focus.order))
      if (si < 0) return
      setOpenSecs((prev) => new Set([...prev, `${si}`]))
      const id = `cite-${focus.key}-${focus.order.replace(',', '-')}`
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const el = document.getElementById(id)
        if (!el) return
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el.classList.add('flash')
        setTimeout(() => el.classList.remove('flash'), 1800)
      }))
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focus?.at])
    const rowsFor = (files: Source[]) => files.flatMap((s) => s.statements.map((st) => ({ s, st })))
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
                    <span className="sec-count"> · {sec.items.length} citation{sec.items.length === 1 ? '' : 's'} · {new Set(sec.items.map((x) => x.key)).size} source{new Set(sec.items.map((x) => x.key)).size === 1 ? '' : 's'}</span>
                  </td>
                </tr>
                {openSecs.has(`${si}`) && sec.items.map((it, k) => {
                  const words = sentenceWords([it.c.text])
                  const rows = rowsFor(it.files)
                  return rows.map(({ s, st }, i) => (
                    <tr key={`${si}-${k}-${i}`} id={i === 0 ? rowId(it) : undefined} className={`static ${i === 0 ? 'src-start' : 'interp-row'}`}>
                      {i === 0 && <td rowSpan={rows.length}><SourceCell s={it.files[0]} files={it.files} onOpen={onOpen} /></td>}
                      <td><Quotes st={st} words={words} /></td>
                      <td className="small"><Interpretation st={st} /></td>
                      {i === 0 && <td rowSpan={rows.length} className="small"><div className="ms-sentence">“{it.c.text}”</div></td>}
                    </tr>
                  ))
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
                {openSecs.has('uncited') && uncited.map((s) => s.statements.map((st, i) => (
                  <tr key={`${s.file}-${st.id}`} className={`static ${i === 0 ? 'src-start' : 'interp-row'}`}>
                    {i === 0 && <td rowSpan={s.statements.length}><SourceCell s={s} onOpen={onOpen} /></td>}
                    <td><Quotes st={st} words={new Set()} /></td>
                    <td className="small"><Interpretation st={st} /></td>
                    {i === 0 && <td rowSpan={s.statements.length} className="small muted">Not cited in any .tex file repro.yaml pins.</td>}
                  </tr>
                )))}
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
  const [focus, setFocus] = useState<{ key: string; order: string; at: number } | null>(null)
  return (
    <div className="rec">
      <Head cmd="citations" line={graph.status?.citations.text ?? '—'}
        what="Passages quoted from other people's work, the paper's interpretation of them, and the sentences of the manuscript that cite each source. Click a title for the source's details. Highlighted words appear in both the source and the manuscript. The interpretations and notes are ours; citations verify checks only the quoted passages. A source is pinned when its file is saved with a hash." />
      <CitationsByClaim graph={graph} query={query} onOpen={setPanel} focus={focus} />
      {panel && <SourcePanel s={panel} onClose={() => setPanel(null)} onGo={(key, c) => setFocus({ key, order: c.order.join(','), at: Date.now() })} />}
    </div>
  )
}

export function ReproduceTab({ graph, query }: { graph: Graph; query: string }) {
  const t = graph.tabs?.reproduce
  const q = query.trim().toLowerCase()
  const steps = [...(t?.steps ?? [])].filter((s) => !q || `${s.id} ${s.command} ${s.state}`.toLowerCase().includes(q)).sort((a, b) => (a.state === 'current' ? 1 : 0) - (b.state === 'current' ? 1 : 0) || a.id.localeCompare(b.id))
  const need = steps.filter((s) => s.state !== 'current').length
  const rp = graph.reproduce
  const [panel, setPanel] = useState<Step | null>(null)
  const [viewing, setViewing] = useState<string | null>(null)
  return (
    <div className="rec">
      <Head cmd="repro reproduce" line={rp?.runs ? `${fmt(rp.last.reproduced ?? 0)}/${fmt(rp.last_steps)} reproduced${rp.last_at ? ` ${new Date(rp.last_at).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })}` : ''}${need ? ` · ${need} of ${steps.length} steps need re-running` : ''}` : 'never run'}
        what="A rebuild step is a command repro.yaml declares that turns input files into an output file, such as detex.py or a derive script. repro reproduce runs every step again and checks the output comes out identical. repro stale, run on every check, compares each step with the last re-run without running anything: that is the state column. Click a step for its details." />
      <table>
        <thead><tr><th>Step</th><th>State</th><th>What changed</th><th>Command</th></tr></thead>
        <tbody>
          {steps.map((s) => {
            const [label, tone] = STATE[s.state] ?? [s.state, 'none']
            return (
              <tr key={s.id} className={`static ${panel === s ? 'sel' : ''}`}>
                <td className="clickable" onClick={() => setPanel(s)} title="Details"><button className="file-link mono strong">{s.id}</button></td>
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
        <thead><tr><th>Finished</th><th>Took</th><th>Steps</th><th>Result</th><th>Toolkit</th></tr></thead>
        <tbody>
          {[...(t?.reruns ?? [])].reverse().map((r, i) => (
            <tr key={i} className="static">
              <td className="small">{r.ended_at ? when(r.ended_at) : '—'}</td>
              <td className="small nowrap">{r.started_at && r.ended_at ? `${Math.max(0, (Date.parse(r.ended_at) - Date.parse(r.started_at)) / 1000).toFixed(1)} s` : '—'}</td>
              <td className="num">{r.steps}</td>
              <td className="small">{Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(', ')}</td>
              <td className="mono small muted">{r.tool_version}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {panel && <StepPanel s={panel} onClose={() => setPanel(null)} onView={setViewing} />}
      {viewing && <FileViewer path={viewing} onClose={() => setViewing(null)} />}
    </div>
  )
}

type Step = NonNullable<Graph['tabs']>['reproduce']['steps'][number]

const RERUN: Record<string, string> = { reproduced: 'Reproduced', differs: 'Output differs', failed: 'Failed', skipped: 'Skipped' }

/** One rebuild step: the command, the files it reads and writes, what changed since its last re-run,
 * and every re-run of it on record. */
function StepPanel({ s, onClose, onView }: { s: Step; onClose: () => void; onView: (path: string) => void }) {
  const [label, tone] = STATE[s.state] ?? [s.state, 'none']
  const file = (artifact: string, path?: string) => path
    ? <button className="file-link mono small" onClick={() => onView(path)} title={artifact}>{path}</button>
    : <span className="mono small">{artifact}</span>
  return (
    <aside className="panel">
      <button className="close" onClick={onClose}>×</button>
      <div className="kicker">REBUILD STEP</div>
      <h2 className="mono">{s.id}</h2>
      <p><span className={`pill ${tone === 'warn' ? 'stale' : tone}`}>{label}</span></p>
      <dl>
        <dt>Command</dt><dd className="mono small">{s.command}</dd>
        <dt>Writes</dt><dd>{file(s.artifact, s.output_path)}</dd>
        <dt>Reads</dt><dd>{(s.inputs ?? []).map((i) => <div key={i.artifact}>{file(i.artifact, i.path)}</div>)}</dd>
        <dt>Last re-run</dt><dd>{s.rerun_at ? when(s.rerun_at) : 'never'}</dd>
      </dl>
      {s.causes.length > 0 && (
        <>
          <h3>Changed since the last re-run</h3>
          {s.causes.map((c, i) => <div key={i} className="small">{CAUSE[c.cause] ?? c.cause}: <span className="mono">{c.artifact}</span></div>)}
        </>
      )}
      <h3>{(s.history ?? []).length ? `Re-runs of this step (${(s.history ?? []).length}${(s.history ?? []).length === 20 ? ', latest' : ''})` : 'Never re-run'}</h3>
      {(s.history ?? []).map((h, i) => (
        <div key={i} className="run-claim small">
          <span className={h.state === 'reproduced' ? 'good-text' : 'stale-text'}>{h.state === 'reproduced' ? '✓' : '✗'}</span>{' '}
          {RERUN[h.state] ?? h.state} · {h.ended_at ? when(h.ended_at) : '—'}
          <span className="muted">{h.duration_seconds != null ? ` · ${h.duration_seconds.toFixed(2)} s` : ''}{h.exit_code ? ` · exit ${h.exit_code}` : ''} · {h.tool_version}</span>
          {h.detail && <div className="muted">{h.detail}</div>}
        </div>
      ))}
    </aside>
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
