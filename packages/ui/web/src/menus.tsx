import { useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { ORIGINAL, STATIC } from './api'
import { FixCtx } from './fix'
import {
  auditPrompt, cloneInstructions, cloneToast, fixPrompt, PAGES_WORKFLOW, pagesAddress, pagesCommand, pagesPrompt, pagesSteps,
  presubmitPrompt, staticMessage, type Presubmit,
} from './format'
import { useCopy, useToast } from './toast'
import type { Graph } from './types'

/** A button that opens a menu below it; a click outside, or Escape, closes it. */
function Dropdown({ label, className, children, width, onClosed, disabled }: {
  label: ReactNode
  className: string
  /** The button cannot open its menu, as while the check it starts is going. */
  disabled?: boolean
  width?: number
  children: (close: () => void) => ReactNode
  /** Called whenever the menu closes, so a card opened inside it starts over next time. */
  onClosed?: () => void
}) {
  const [open, setOpenState] = useState(false)
  const setOpen = (v: boolean | ((was: boolean) => boolean)) =>
    setOpenState((was) => {
      const next = typeof v === 'function' ? v(was) : v
      if (was && !next) onClosed?.()
      return next
    })
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div className="dd" ref={box}>
      <button className={className} disabled={disabled} onClick={() => setOpen((v) => !v)}>{label}</button>
      {open && <div className="dd-menu" style={width ? { width } : undefined}>{children(() => setOpen(false))}</div>}
    </div>
  )
}

function Item({ title, text, code, onClick, disabled }: { title: string; text: string; code?: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button className="dd-item" onClick={onClick} disabled={disabled}>
      <b>{title}</b><span>{text}</span>{code && <code>{code}</code>}
    </button>
  )
}

/** ✓ repro verify ▾: Verify, and Pre-submit check, which also flags numbers with no claim,
 * quotes not pinned and inputs not sealed. Its findings open in a card with Copy prompt. */
export function VerifyMenu({ graph, busy, serverless, run }: {
  graph: Graph
  busy: boolean
  serverless: boolean
  run: (presubmit: boolean) => Promise<void> | void
}) {
  const toast = useToast()
  const [shown, setShown] = useState(false)
  const found = graph.presubmit
  return (
    <>
      <Dropdown className="btn ghost-dark" disabled={busy}
        label={busy ? <><span className="spin" /> Checking…</> : <>✓ repro verify ▾</>}>
        {(close) => (
          <>
            <Item title="Verify" text="Check every claim, and that prereg, results and citations verify with no errors." code="repro verify"
              disabled={busy}
              onClick={() => { close(); if (serverless) toast(staticMessage('verify')); else { toast('Running repro verify…'); run(false) } }} />
            <Item title="Pre-submit check" text="Verify, and also flag numbers with no claim, quotes not pinned and inputs not sealed." code="repro verify, then repro numbers"
              disabled={busy}
              onClick={async () => {
                close()
                if (serverless) return toast(staticMessage('verify'))
                toast('Running the Pre-submit check…')
                await run(true)
                setShown(true)
              }} />
            {found && (
              <Item title="Last Pre-submit check" text={`${presubmitSaid(found)} · ${new Date(found.checked_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}`}
                onClick={() => { close(); setShown(true) }} />
            )}
          </>
        )}
      </Dropdown>
      {shown && found && <PresubmitCard found={found} graph={graph} onClose={() => setShown(false)} />}
    </>
  )
}

const presubmitSaid = (p: Presubmit) =>
  [
    p.numbers_read ? `${p.unbound_count} number${p.unbound_count === 1 ? '' : 's'} with no claim` : 'numbers could not be read',
    `${p.unpinned.length} source${p.unpinned.length === 1 ? '' : 's'} not pinned`,
    `${p.unsealed.length} run${p.unsealed.length === 1 ? '' : 's'} with nothing sealed before ${p.unsealed.length === 1 ? 'it' : 'them'}`,
  ].join(', ')

/** The Pre-submit check's findings, with what the claims check found beside them. */
function PresubmitCard({ found, graph, onClose }: { found: Presubmit; graph: Graph; onClose: () => void }) {
  const { project } = useContext(FixCtx)
  const copy = useCopy()
  const failing = new Set(graph.nodes.flatMap((n) => n.claims.filter((c) => !c.ok).map((c) => c.id))).size
  return (
    <div className="viewer-back" onClick={onClose}>
      <div className="confirm" onClick={(e) => e.stopPropagation()}>
        <div className="confirm-head">
          <h3>Pre-submit check</h3>
          <button className="close" onClick={onClose}>×</button>
        </div>
        <p className="small muted">{new Date(found.checked_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })} · repro verify: {failing ? `${failing} claims failing` : 'every claim verified'}{(graph.issues ?? []).length ? `, ${(graph.issues ?? []).length} issues open` : ''}</p>
        <p><b>{presubmitSaid(found)}</b></p>
        {!found.numbers_read && <p className="small stale-text">repro numbers printed nothing readable, so the numbers were not counted.</p>}
        {found.unbound.length > 0 && (
          <>
            <h4 className="ps-h">Numbers with no claim{found.unbound_count > found.unbound.length ? ` (first ${found.unbound.length} of ${found.unbound_count})` : ''}</h4>
            <div className="ps-list">
              {found.unbound.map((n, i) => (
                <div key={i} className="small"><span className="mono">{n.path}:{n.line ?? '?'}</span> <b>{n.text}</b> <span className="muted">{n.context}</span></div>
              ))}
            </div>
          </>
        )}
        {found.unpinned.length > 0 && (<><h4 className="ps-h">Quotes not pinned</h4><div className="small mono">{found.unpinned.join(', ')}</div></>)}
        {found.unsealed.length > 0 && (<><h4 className="ps-h">Runs with nothing sealed before them</h4><div className="small mono">{found.unsealed.join(', ')}</div></>)}
        <div className="pa" style={{ marginTop: 12 }}>
          <button className="btn primary small" onClick={() => copy(presubmitPrompt(found, project ?? graph.project_dir ?? null), 'Prompt copied. Paste it into Claude Code or another coding agent.')}>Copy prompt</button>
          <span className="ph">Paste into Claude Code or another coding agent</span>
        </div>
      </div>
    </div>
  )
}

/** A prompt shown in full, with Copy prompt under it. */
export function PromptCard({ title, about, prompt, onCopied }: { title: string; about: string; prompt: string; onCopied: () => void }) {
  const copy = useCopy()
  return (
    <div className="pop">
      <b className="pt">{title}</b>
      <p className="pd">{about}</p>
      <pre className="pp">{prompt}</pre>
      <div className="pa">
        <button className="btn primary small" onClick={() => { copy(prompt, 'Prompt copied. Paste it into Claude Code or another coding agent.'); onCopied() }}>Copy prompt</button>
        <span className="ph">Paste into Claude Code or another coding agent</span>
      </div>
    </div>
  )
}

/** Ask AI ▾: Audit paper, and Fix issues · N open. Each shows its prompt before it is copied. */
export function AskAIMenu({ graph }: { graph: Graph }) {
  const { project } = useContext(FixCtx)
  const [pick, setPick] = useState<'audit' | 'fix' | null>(null)
  const issues = graph.issues ?? []
  const dir = project ?? graph.project_dir ?? null
  return (
    <Dropdown className="btn ghost-dark" label="Ask AI ▾" width={pick ? 560 : 340} onClosed={() => setPick(null)}>
      {(close) => pick === null ? (
        <>
          <Item title="Audit paper" text="Find numbers, quotes and claims with no record behind them." onClick={() => setPick('audit')} />
          <Item title={`Fix issues · ${issues.length} open`} text={issues.length ? 'Lay out the options for each open issue.' : 'Nothing is open.'}
            disabled={issues.length === 0} onClick={() => setPick('fix')} />
        </>
      ) : pick === 'audit' ? (
        <PromptCard title="Audit paper"
          about="Your AI agent reads the manuscript and finds every number, quote and claim with no record behind it. It lays out what to record and changes nothing until you say so."
          prompt={auditPrompt(dir, graph.manuscript_path)} onCopied={close} />
      ) : (
        <PromptCard title="Fix issues"
          about="Your AI agent looks into each open issue, explains what it found and lays out the options. It changes nothing until you say so."
          prompt={fixPrompt(issues, dir)} onCopied={close} />
      )}
    </Dropdown>
  )
}

const megabytes = (n: number) => `${(n / 1_000_000).toFixed(1)} MB`

function save(name: string, html: string) {
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Share ▾: Download as HTML, Copy clone instructions, Publish on GitHub Pages. The page itself
 * never publishes anything. */
export function ShareMenu({ graph }: { graph: Graph }) {
  const toast = useToast()
  const copy = useCopy()
  const { project } = useContext(FixCtx)
  const [pages, setPages] = useState(false)
  const name = `${(graph.project_name || 'project').replace(/[^A-Za-z0-9._-]/g, '-')}.html`
  const download = async () => {
    try {
      const html = STATIC
        ? ORIGINAL
        : await fetch('api/export').then((r) => (r.ok ? r.text() : Promise.reject(new Error(`the server answered ${r.status}`))))
      save(name, html)
      toast(`Saved ${name} (${megabytes(new Blob([html]).size)})`)
    } catch (e) {
      toast(`Could not save the page: ${e}`)
    }
  }
  return (
    <Dropdown className="btn primary" label="Share ▾" width={pages ? 560 : 340} onClosed={() => setPages(false)}>
      {(close) => !pages ? (
        <>
          <Item title="Download as HTML" text="One read-only .html file with this page and its data as of now. Opens in any browser with nothing installed."
            onClick={() => { close(); download() }} />
          <Item title="Copy clone instructions" text="The commands someone runs to open this page on their own machine."
            onClick={() => { close(); copy(cloneInstructions(graph.remote, graph.project_dir), cloneToast(graph.remote)) }} />
          <Item title="Publish on GitHub Pages" text="Step-by-step instructions. Nothing is published for you." onClick={() => setPages(true)} />
        </>
      ) : (
        <div className="pop">
          <b className="pt">Publish on GitHub Pages</b>
          <p className="pd">Run these yourself, or copy them as a prompt for Claude Code. Nothing here publishes anything. A Pages site is public even when the repository is private.</p>
          <p className="pd"><b>1.</b> Add this workflow as .github/workflows/repro-pages.yml. It exports the page on every push to main.</p>
          <pre className="pp nowrap">{PAGES_WORKFLOW}</pre>
          <p className="pd"><b>2.</b> Turn on Pages with GitHub Actions as the source, in Settings → Pages, or with: <code>{pagesCommand(graph.remote)}</code></p>
          <p className="pd"><b>3.</b> Commit the workflow and push. The page appears at {pagesAddress(graph.remote)}.</p>
          <div className="pa">
            <button className="btn primary small" onClick={() => { copy(pagesSteps(graph.remote), 'Copied the steps'); close() }}>Copy steps</button>
            <button className="btn small" onClick={() => { copy(pagesPrompt(graph.remote, project ?? graph.project_dir ?? null), 'Prompt copied. Paste it into Claude Code or another coding agent.'); close() }}>Copy prompt</button>
          </div>
        </div>
      )}
    </Dropdown>
  )
}
