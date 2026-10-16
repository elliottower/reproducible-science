import { useContext, useEffect, useRef, useState } from 'react'
import { STATIC } from './api'
import { FixCtx } from './fix'
import { auditPrompt, fixPrompt, staticMessage, terminalCommand } from './format'
import { IssueRow } from './issues'
import { PromptCard } from './menus'
import { useCopy, useToast } from './toast'
import type { Graph, IssueOpen } from './types'

/** The bar's right side to try: `?bar=issues` in the address. The layout without it stays the
 * default until one is picked. */
export const ISSUES_BAR = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('bar') === 'issues'

type Card = 'audit' | 'fix' | null

/** `N issues ▾`, or `No issues ▾`: the issue rows, as the issues pill has them, with what the
 * Ask AI and repro verify menus held above them: Audit paper and Fix issues as prompt cards, and
 * Run repro verify again with its command. */
export function IssuesBarPill({ graph, onOpen, busy, serverless, verify }: {
  graph: Graph
  onOpen: (o: IssueOpen) => void
  busy: boolean
  serverless: boolean
  verify: () => void
}) {
  const rows = graph.issues ?? []
  const { project } = useContext(FixCtx)
  const toast = useToast()
  const copy = useCopy()
  const [open, setOpen] = useState(false)
  const [card, setCard] = useState<Card>(null)
  const box = useRef<HTMLDivElement>(null)
  const close = () => { setOpen(false); setCard(null) }
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) close() }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  const dir = project ?? graph.project_dir ?? null
  const n = rows.length
  return (
    <div className="issues" ref={box}>
      <button className={`pill big pill-btn ${n ? 'bad' : 'good'}`} onClick={() => (open ? close() : setOpen(true))}
        title="What prereg, results and citations report, and the prompts and check to act on them">
        ● {n ? `${n} issue${n === 1 ? '' : 's'}` : 'No issues'} <span className="caret">▾</span>
      </button>
      {open && (
        <div className="issues-menu">
          {card === 'audit' ? (
            <PromptCard title="Audit paper"
              about="Your AI agent reads the manuscript and finds every number, quote and claim with no record behind it. It lays out what to record and changes nothing until you say so."
              prompt={auditPrompt(dir, graph.manuscript_path)} onCopied={close} />
          ) : card === 'fix' ? (
            <PromptCard title="Fix issues"
              about="Your AI agent looks into each open issue, explains what it found and lays out the options. It changes nothing until you say so."
              prompt={fixPrompt(rows, dir)} onCopied={close} />
          ) : (
            <>
              <div className="issue-top">
                <button className="dd-item" onClick={() => setCard('audit')}>
                  <b>Audit paper</b><span>Find numbers, quotes and claims with no record behind them.</span>
                </button>
                {n > 0 && (
                  <button className="dd-item" onClick={() => setCard('fix')}>
                    <b>Fix issues</b><span>Lay out the options for each open issue.</span>
                  </button>
                )}
                <div className="dd-item issue-verify">
                  <b>Run repro verify again</b>
                  <span>Check every claim, and that prereg, results and citations verify with no errors.</span>
                  <div className="issue-actions">
                    <button className="repro-main" disabled={busy}
                      onClick={() => { close(); if (serverless || STATIC) toast(staticMessage('verify')); else { toast('Running repro verify…'); verify() } }}>
                      {busy ? 'Verifying…' : 'Run repro verify'}
                    </button>
                    <button className="copy-prompt small" onClick={() => copy(terminalCommand(graph.project_dir ?? undefined, 'repro verify'), 'Copied the command')}>Copy command</button>
                  </div>
                </div>
              </div>
              {rows.map((r) => <IssueRow key={r.id} row={r} onOpen={(o) => { close(); onOpen(o) }} />)}
            </>
          )}
        </div>
      )}
    </div>
  )
}
