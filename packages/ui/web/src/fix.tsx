import { createContext, useState, type ReactNode } from 'react'
import type { ClaimRow, Graph } from './types'

/** The project folder, for the prompts below to name. */
export const FixCtx = createContext<{ project: string | null }>({ project: null })

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

/** One prompt for every failing claim in the project. */
export function failingPrompt(g: Graph, project: string | null): string {
  const claims = new Map<string, ClaimRow>()
  for (const n of g.nodes) for (const c of n.claims) if (!c.ok) claims.set(c.id, c)
  return [
    `In ${project ?? 'this project'}, ${claims.size} claim${claims.size === 1 ? '' : 's'} fail \`repro verify\`:`,
    ...[...claims.values()].slice(0, 30).map((c) => `- \`${c.id}\` (${c.where}): ${c.assertions.filter((a) => !a.ok).map((a) => `${a.kind} on ${a.artifact}: ${a.comparison}${a.detail ? `, ${a.detail}` : ''}`).join('; ')}`),
    '',
    'Run `repro why <claim>` for each and show me what drifted before changing anything. Do not repin a file or edit a sealed result to make the check pass.',
  ].join('\n')
}

/** Copies a prompt to paste into any agent: Claude Code, Codex, or one connected to repro mcp. */
export function CopyPrompt({ prompt, small }: { prompt: string; small?: boolean }) {
  const [note, setNote] = useState<string | null>(null)
  const copy = () =>
    navigator.clipboard.writeText(prompt).then(
      () => setNote('Prompt copied'),
      () => setNote('Could not copy'),
    ).finally(() => setTimeout(() => setNote(null), 2500))
  return (
    <button className={`copy-prompt ${small ? 'small' : ''}`} onClick={copy}
      title="Paste it into Claude Code, Codex, or an agent connected to repro mcp">
      {note ?? 'Copy prompt to fix'}
    </button>
  )
}

/** The failing-claims pill. Clicking it says what is wrong and offers the prompt to copy. */
export function ProblemPill({ className, label, what, prompt, title }: {
  className: string; label: string; what: ReactNode; prompt: string; title?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <span className="fixmenu">
      <button className={`pill big pill-btn ${className}`} title={title} onClick={() => setOpen((o) => !o)}>
        {label} <span className="caret">▾</span>
      </button>
      {open && (
        <div className="menu" onMouseLeave={() => setOpen(false)}>
          <div className="menu-what">{what}</div>
          <div className="menu-act"><CopyPrompt prompt={prompt} /></div>
        </div>
      )}
    </span>
  )
}
