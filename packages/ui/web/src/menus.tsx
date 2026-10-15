import { useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { STATIC } from './api'
import { FixCtx } from './fix'
import {
  auditPrompt, cloneInstructions, fixPrompt, PAGES_WORKFLOW, pagesAddress, pagesCommand, pagesPrompt, pagesSteps, staticMessage,
} from './format'
import { useCopy, useToast } from './toast'
import type { Graph } from './types'

/** A button that opens a menu below it; a click outside, or Escape, closes it. */
function Dropdown({ label, className, children, width, onClosed }: {
  label: ReactNode
  className: string
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
      <button className={className} onClick={() => setOpen((v) => !v)}>{label}</button>
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

/** ✓ repro verify ▾: one entry, Verify. */
export function VerifyMenu({ busy, run }: { busy: boolean; run: () => void }) {
  const toast = useToast()
  return (
    <Dropdown className="btn ghost-dark" label={<>{busy ? 'Verifying…' : '✓ repro verify'} ▾</>}>
      {(close) => (
        <Item title="Verify" text="Check every claim, and that prereg, results and citations verify with no errors." code="repro verify"
          disabled={busy}
          onClick={() => { close(); if (STATIC) toast(staticMessage('verify')); else { toast('Running repro verify…'); run() } }} />
      )}
    </Dropdown>
  )
}

/** A prompt shown in full, with Copy prompt under it. */
function PromptCard({ title, about, prompt, onCopied }: { title: string; about: string; prompt: string; onCopied: () => void }) {
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
        ? `<!doctype html>\n${document.documentElement.outerHTML}`
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
            onClick={() => { close(); copy(cloneInstructions(graph.remote, graph.project_dir), 'Copied: git clone, pip install, repro ui') }} />
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
