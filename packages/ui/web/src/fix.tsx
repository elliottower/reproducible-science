import { createContext, useState } from 'react'
import { ASK_FIRST } from './format'
import { fmt, when } from './shared'
import type { ClaimRow, Graph } from './types'

/** The project folder, for the prompts below to name. */
export const FixCtx = createContext<{ project: string | null }>({ project: null })

const failingLines = (c: ClaimRow) =>
  c.assertions.filter((a) => !a.ok).map(
    (a) => `- ${a.kind} assertion on \`${a.artifact}\`: ${a.comparison} (${a.reason})${a.detail ? `; ${a.detail}` : ''}${a.extracted ? `; read ${a.extracted}` : ''}`,
  )

export function claimPrompt(c: ClaimRow, project: string | null): string {
  return [
    `In ${project ?? 'this project'}, the claim \`${c.id}\` (${c.where}) fails \`repro verify\`.`,
    `Claim: ${c.text}`,
    ...failingLines(c),
    '',
    `\`repro why ${c.id}\` shows what the record establishes for it. Find out whether the manuscript, the file, or the claim's declaration drifted.`,
    '',
    ASK_FIRST,
  ].join('\n')
}

/** One prompt for every failing claim in the project. */
export function failingPrompt(g: Graph, project: string | null): string {
  const claims = new Map<string, ClaimRow>()
  for (const n of g.nodes) for (const c of n.claims) if (!c.ok) claims.set(c.id, c)
  return [
    `In ${project ?? 'this project'}, ${claims.size} claim${claims.size === 1 ? '' : 's'} fail \`repro verify\`:`,
    ...[...claims.values()].slice(0, 30).map((c) => `- \`${c.id}\` (${c.where}): ${c.assertions.filter((a) => !a.ok).map((a) => `${a.kind} on ${a.artifact}: ${a.comparison}${a.detail ? `, ${a.detail}` : ''}`).join('; ')}`),
    '',
    '`repro why <claim>` shows what the record establishes for each. Find out, for each, whether the manuscript, the file, or the declaration drifted.',
    '',
    ASK_FIRST,
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
      title="A prompt asking an agent to look into this and lay out your options. Paste it into Claude Code, Codex, or an agent connected to repro mcp.">
      {note ?? 'Copy prompt'}
    </button>
  )
}

/** `● 528/531 claims verified`: green when every claim passes, red otherwise. Opens the Claims tab. */
export function ClaimsPill({ graph, openClaims }: { graph: Graph; openClaims: () => void }) {
  const failing = new Set<string>()
  for (const n of graph.nodes) for (const c of n.claims) if (!c.ok) failing.add(c.id)
  const total = graph.totals.claims
  return (
    <button className={`pill big pill-btn ${failing.size ? 'bad' : 'good'}`} onClick={openClaims}
      title={`${graph.totals.last_check ? `${fmt(graph.totals.assertions)} assertions over ${fmt(graph.totals.artifacts)} files · last check ${when(graph.totals.last_check)} · ` : ''}open the Claims tab`}>
      ● {fmt(total - failing.size)}/{fmt(total)} claims verified
    </button>
  )
}
