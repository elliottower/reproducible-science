import { createContext, useContext, useState, type ReactNode } from 'react'
import { post } from './api'
import type { ClaimRow, GNode, Graph } from './types'

/** Whether the page is served by builder/serve.py, which can queue a request for Claude Code. */
export const FixCtx = createContext<{ available: boolean; project: string | null }>({ available: false, project: null })

const CAUSE: Record<string, string> = {
  input_changed: 'an input changed',
  output_changed: 'the output changed',
  command_changed: 'the command changed',
}

export function claimPrompt(c: ClaimRow, project: string | null): string {
  const failing = c.assertions.filter((a) => !a.ok)
  const lines = [
    `In ${project ?? 'this project'}, the claim \`${c.id}\` (${c.where}) fails \`repro verify\`.`,
    `Claim: ${c.text}`,
    ...failing.map(
      (a) => `- ${a.kind} assertion on \`${a.artifact}\`: ${a.comparison} (${a.reason})${a.detail ? `; ${a.detail}` : ''}${a.extracted ? `; read ${a.extracted}` : ''}`,
    ),
    '',
    `Run \`repro why ${c.id}\` first. Find out whether the manuscript, the file, or the claim's declaration drifted, and show me what you would change before changing it. Do not repin a file or edit a sealed result to make the check pass.`,
  ]
  return lines.join('\n')
}

export function stalePrompt(n: GNode, project: string | null): string {
  const causes = (n.causes ?? []).map((c) => `- ${CAUSE[c.cause] ?? c.cause}: \`${c.artifact}\``)
  return [
    `In ${project ?? 'this project'}, the rebuild step for \`${n.id}\` (${n.path}) is stale under \`repro stale\`: since its last re-run${n.rerun_at ? ` (${n.rerun_at})` : ''},`,
    ...causes,
    '',
    `Rebuilt by: ${n.regenerated_by ?? 'no command declared'}`,
    `${n.ok + n.fail} claims read this file.`,
    '',
    'Say whether the change is expected (a new paper version, an edited script) or a drift, then propose the re-run (`repro reproduce`) and what it should show. Ask before running anything that writes to the record.',
  ].join('\n')
}

export function FixButtons({ subject, prompt }: { subject: string; kind: 'claim' | 'stale'; prompt: string }) {
  return (
    <div className="fix">
      <ClaudeButton prompt={prompt} subject={subject} small />
    </div>
  )
}

/** One prompt for the whole project: every failing claim and every stale rebuild step. */
export function projectPrompt(g: Graph, project: string | null): string {
  const claims = new Map<string, ClaimRow>()
  for (const n of g.nodes) for (const c of n.claims) if (!c.ok) claims.set(c.id, c)
  const stale = g.nodes.filter((n) => n.type === 'artifact' && n.freshness === 'stale')
  const status = g.status
    ? Object.entries(g.status).map(([k, v]) => `- ${k}: ${v.text}`).join('\n')
    : ''
  return [
    `Here is the state of ${project ?? 'this project'} from the lineage view.`,
    status,
    '',
    claims.size ? `${claims.size} failing claim${claims.size === 1 ? '' : 's'}:` : 'No claim fails.',
    ...[...claims.values()].slice(0, 30).map((c) => `- \`${c.id}\` (${c.where}): ${c.assertions.filter((a) => !a.ok).map((a) => `${a.kind} on ${a.artifact}: ${a.comparison}${a.detail ? `, ${a.detail}` : ''}`).join('; ')}`),
    '',
    stale.length ? `${stale.length} stale rebuild step${stale.length === 1 ? '' : 's'} (repro stale):` : 'No rebuild step is stale.',
    ...stale.map((n) => `- \`${n.id}\`: ${(n.causes ?? []).map((c) => `${c.cause.replace('_', ' ')} (${c.artifact})`).join(', ')}`),
    '',
    'Start with the failing claims: run `repro why <claim>` for each and show me what drifted before changing anything. For the stale steps, say which changes are expected and propose the re-run. Ask before anything that writes to the records.',
  ].join('\n')
}

/** The two ways to hand a fix prompt over. Sending queues it for the repro-fixes mod, which shows it
 * above the prompt of the Claude Code session open in the project; copying puts it on the clipboard.
 * Without the local server only copying is offered. */
function useFix(prompt: string, subject: string) {
  const { available, project } = useContext(FixCtx)
  const [note, setNote] = useState<string | null>(null)
  const done = (text: string) => {
    setNote(text)
    setTimeout(() => setNote(null), 2500)
  }
  const copy = () => navigator.clipboard.writeText(prompt).then(() => done('Prompt copied'), () => done('Could not copy'))
  const send = () =>
    post('api/fix-request', { project, subject, kind: 'claim', prompt })
      .then((r) => r.json())
      .then((res) => done(res.ok ? 'Sent to Claude Code' : `Not sent: ${res.error}`))
      .catch((e) => done(`Not sent: ${e}`))
  return { available, note, copy, send }
}

function FixMenu({ fix, what, onDone }: { fix: ReturnType<typeof useFix>; what?: ReactNode; onDone: () => void }) {
  return (
    <div className="menu" onMouseLeave={onDone}>
      {what && <div className="menu-what">{what}</div>}
      {fix.available && (
        <button onClick={() => { fix.send(); onDone() }}>
          <b>Fix with Claude Code</b>
          <span>Appears above the prompt of the Claude Code session open in this project</span>
        </button>
      )}
      <button onClick={() => { fix.copy(); onDone() }}>
        <b>Copy prompt to fix</b>
        <span>Paste it into Claude Code, Codex, or an agent connected to repro mcp</span>
      </button>
    </div>
  )
}

/** Fix with Claude Code, for one claim or one stale file inside a panel. */
export function ClaudeButton({ prompt, subject, small }: { prompt: string; subject: string; small?: boolean }) {
  const fix = useFix(prompt, subject)
  const [open, setOpen] = useState(false)
  return (
    <span className={`fixmenu ${small ? 'small' : ''}`}>
      <button className="fix-main" onClick={() => setOpen((o) => !o)}>
        {fix.note ?? 'Fix with Claude Code'} <span className="caret">▾</span>
      </button>
      {open && <FixMenu fix={fix} onDone={() => setOpen(false)} />}
    </span>
  )
}

/** A status pill in the top bar that names a problem ("3 failing", "10 need re-run"). Clicking it
 * says what is wrong and offers the fix, so the fix appears only where there is something to fix. */
export function ProblemPill({ className, label, what, prompt, subject, title }: {
  className: string; label: string; what: ReactNode; prompt: string; subject: string; title?: string
}) {
  const fix = useFix(prompt, subject)
  const [open, setOpen] = useState(false)
  return (
    <span className="fixmenu">
      <button className={`pill big pill-btn ${className}`} title={title} onClick={() => setOpen((o) => !o)}>
        {fix.note ?? label} <span className="caret">▾</span>
      </button>
      {open && <FixMenu fix={fix} what={what} onDone={() => setOpen(false)} />}
    </span>
  )
}
