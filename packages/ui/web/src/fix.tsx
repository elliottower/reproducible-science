import { createContext, useContext, useState } from 'react'
import { fmt, when } from './shared'
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

/** `● 528/531 claims verified ▾`: green when every claim passes, red otherwise. The menu lists the
 * failing claims first, then the counts by section, a way to the Claims tab, and the prompt to copy. */
export function ClaimsPill({ graph, openClaims }: { graph: Graph; openClaims: () => void }) {
  const [open, setOpen] = useState(false)
  const { project } = useContext(FixCtx)
  const failing = new Map<string, ClaimRow>()
  for (const n of graph.nodes) for (const c of n.claims) if (!c.ok) failing.set(c.id, c)
  const total = graph.totals.claims
  const sections = graph.nodes.filter((n) => n.type === 'section' && n.ok + n.fail > 0)
  const bad = failing.size > 0
  return (
    <span className="fixmenu">
      <button className={`pill big pill-btn ${bad ? 'bad' : 'good'}`} onClick={() => setOpen((o) => !o)}
        title={graph.totals.last_check ? `${fmt(graph.totals.assertions)} assertions over ${fmt(graph.totals.artifacts)} files · last check ${when(graph.totals.last_check)}` : undefined}>
        ● {fmt(total - failing.size)}/{fmt(total)} claims verified <span className="caret">▾</span>
      </button>
      {open && (
        <div className="menu wide" onMouseLeave={() => setOpen(false)}>
          {bad && (
            <>
              <div className="menu-head">{failing.size} failing</div>
              <div className="menu-list">
                {[...failing.values()].map((c) => (
                  <div key={c.id} className="menu-row"><span className="mono">{c.id}</span><span className="muted">{c.section || c.where}</span></div>
                ))}
              </div>
            </>
          )}
          <div className="menu-head">By section</div>
          <div className="menu-list">
            {sections.map((n) => (
              <div key={n.id} className="menu-row">
                <span>{n.label}</span>
                <span className={n.fail ? 'stale-text' : 'muted'}>{fmt(n.ok)}/{fmt(n.ok + n.fail)}</span>
              </div>
            ))}
          </div>
          <div className="menu-act">
            <button className="link-btn" onClick={() => { setOpen(false); openClaims() }}>Open the Claims tab →</button>
            {bad && <CopyPrompt prompt={failingPrompt(graph, project)} />}
          </div>
        </div>
      )}
    </span>
  )
}
