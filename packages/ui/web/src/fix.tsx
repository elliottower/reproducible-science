import { createContext, useContext, useState } from 'react'
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

export function FixButtons({ subject, kind, prompt }: { subject: string; kind: 'claim' | 'stale'; prompt: string }) {
  const { available, project } = useContext(FixCtx)
  const [note, setNote] = useState<string | null>(null)
  const copy = () =>
    navigator.clipboard.writeText(prompt).then(
      () => setNote('Copied'),
      () => setNote('Could not copy'),
    )
  const send = () =>
    fetch('api/fix-request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, subject, kind, prompt }),
    })
      .then((r) => r.json())
      .then((res) => setNote(res.ok ? 'Sent to Claude Code' : `Not sent: ${res.error}`))
      .catch((e) => setNote(`Not sent: ${e}`))
  return (
    <div className="fix">
      <button onClick={copy}>Copy fix prompt</button>
      {available && <button className="primary-sm" onClick={send}>Send to Claude Code</button>}
      {note && <span className="muted small">{note}</span>}
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

/** Claude Code button: sends the prompt to the queue the repro-fixes mod reads, or copies it. The
 * arrow switches which; the choice is remembered in this browser. */
export function ClaudeButton({ prompt, subject }: { prompt: string; subject: string }) {
  const { available, project } = useContext(FixCtx)
  const [mode, setMode] = useState<'send' | 'copy'>(() => {
    try {
      return (localStorage.getItem('claude-mode') as 'send' | 'copy') ?? 'send'
    } catch {
      return 'send'
    }
  })
  const [note, setNote] = useState<string | null>(null)
  const effective = available ? mode : 'copy'
  const act = () => {
    if (effective === 'copy') {
      navigator.clipboard.writeText(prompt).then(() => setNote('Copied'), () => setNote('Could not copy'))
      return
    }
    fetch('api/fix-request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, subject, kind: 'claim', prompt }),
    })
      .then((r) => r.json())
      .then((res) => setNote(res.ok ? 'Sent' : `Not sent: ${res.error}`))
      .catch((e) => setNote(`Not sent: ${e}`))
  }
  const flip = () => {
    const next = mode === 'send' ? 'copy' : 'send'
    setMode(next)
    try { localStorage.setItem('claude-mode', next) } catch { /* private window */ }
  }
  return (
    <span className="split">
      <button className="split-main" onClick={act} title={note ?? undefined}>
        {note ?? (effective === 'send' ? 'Send to Claude Code' : 'Copy prompt')}
      </button>
      {available && <button className="split-arrow" onClick={flip} title={mode === 'send' ? 'Switch to copying the prompt' : 'Switch to sending it to Claude Code'}>⇄</button>}
    </span>
  )
}
