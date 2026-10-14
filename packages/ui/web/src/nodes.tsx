import { createContext, useContext } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { GroupSummary } from './layout'
import { fmt, Freshness, Status, when } from './shared'
import type { ClaimRow, GNode } from './types'

export interface Ctx {
  selected: string | null
  matches: Set<string>
  related: Set<string>
  toggle: (group: string) => void
  openFiles: Set<string>
  toggleFile: (file: string) => void
}
export const UiCtx = createContext<Ctx>({
  selected: null, matches: new Set(), related: new Set(), toggle: () => {}, openFiles: new Set(), toggleFile: () => {},
})

function nodeClass(id: string, ctx: Ctx, extra = '') {
  const c = ['card', extra]
  if (ctx.selected === id) c.push('selected')
  else if (ctx.selected && !ctx.related.has(id)) c.push('dim')
  if (ctx.matches.size && ctx.matches.has(id)) c.push('match')
  return c.join(' ')
}

function ArtifactNode({ data, id }: NodeProps) {
  const ctx = useContext(UiCtx)
  const n = (data as { node: GNode }).node
  const problem = n.state === 'missing' ? 'File missing' : n.state === 'changed' ? 'Changed since pinned' : undefined
  return (
    <div className={nodeClass(id, ctx, n.freshness === 'stale' ? 'is-stale' : '')} style={{ width: 270 }}>
      <Handle type="target" position={Position.Left} />
      <div className="card-head">
        <span className="icon">▤</span>
        <span className="mono name">{n.id}</span>
      </div>
      <div className="card-sub mono">{n.path}</div>
      <div
        className={`status-click ${ctx.openFiles.has(n.id) ? 'opened' : ''}`}
        onClick={(e) => { if (n.claims.length) { e.stopPropagation(); ctx.toggleFile(n.id) } }}
        title={n.claims.length ? (ctx.openFiles.has(n.id) ? 'Hide its claims' : 'Show its claims in the graph') : undefined}
      >
        <Status ok={n.ok} fail={n.fail} problem={problem} />
      </div>
      <div className="card-foot">
        <Freshness node={n} />
        <span title={n.last_checked ? `last checked ${when(n.last_checked)}` : undefined}>
          {n.last_checked ? `checked ${new Date(n.last_checked).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : ''}
        </span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function SectionNode({ data, id }: NodeProps) {
  const ctx = useContext(UiCtx)
  const n = (data as { node: GNode }).node
  return (
    <div className={nodeClass(id, ctx, 'section')} style={{ width: 210 }}>
      <Handle type="target" position={Position.Left} />
      <div className="card-head">
        <span className="icon">§</span>
        <span className="name">{n.label}</span>
      </div>
      <div
        className={`status-click ${ctx.openFiles.has(n.id) ? 'opened' : ''}`}
        onClick={(e) => { if (n.claims.length) { e.stopPropagation(); ctx.toggleFile(n.id) } }}
        title={ctx.openFiles.has(n.id) ? 'Hide its claims' : 'Show its claims in the graph'}
      >
        <Status ok={n.ok} fail={n.fail} />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function GroupCollapsed({ data, id }: NodeProps) {
  const ctx = useContext(UiCtx)
  const s = (data as { summary: GroupSummary }).summary
  const files = s.kind === 'files'
  return (
    <div className={nodeClass(id, ctx, 'group-collapsed')} style={{ width: 270 }}>
      <Handle type="target" position={Position.Left} />
      <div className="card-head">
        <span className="name upper">{s.id}</span>
        <button className="chev" onClick={(e) => { e.stopPropagation(); ctx.toggle(s.id) }} title="Expand">⌄</button>
      </div>
      <div className="card-sub">
        {s.members.length} {files ? 'file' : 'section'}
        {s.members.length === 1 ? '' : 's'}
        {s.matches > 0 && <span className="matchcount"> · {s.matches} match{s.matches === 1 ? '' : 'es'}</span>}
      </div>
      <div className="pills">
        <span className={`pill ${s.fail || s.problems - s.staleFiles > 0 ? 'bad' : 'good'}`}>
          ● {fmt(s.ok)}
          {s.fail ? ` · ${fmt(s.fail)} failing` : ''}
        </span>
        <span className="muted small">claims</span>
        {s.staleFiles > 0 && <span className="pill stale">◐ {s.staleFiles} stale</span>}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function GroupOpen({ data }: NodeProps) {
  const ctx = useContext(UiCtx)
  const s = (data as { summary: GroupSummary }).summary
  return (
    <div className="group-open">
      <Handle type="target" position={Position.Left} />
      <div className="group-head">
        <div>
          <div className="name upper">{s.id}</div>
          <div className="muted small">
            {s.members.length} {s.kind === 'files' ? 'files' : 'sections'} · {fmt(s.ok)} claims verified
            {s.fail ? ` · ${fmt(s.fail)} failing` : ''}
            {s.staleFiles ? ` · ${s.staleFiles} stale` : ''}
          </div>
        </div>
        <button className="chev" onClick={() => ctx.toggle(s.id)} title="Collapse">⌃</button>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function ClaimNode({ data, id }: NodeProps) {
  const ctx = useContext(UiCtx)
  const c = (data as { claim: ClaimRow }).claim
  return (
    <div className={nodeClass(id, ctx, `claim-card ${c.ok ? '' : 'bad'}`)} style={{ width: 240 }}>
      <Handle type="target" position={Position.Left} />
      <div className="claim-card-top">
        <span className={`dot ${c.ok ? 'good' : 'bad'}`} />
        <span className="mono name">{c.id}</span>
      </div>
      <div className="claim-card-sub">
        <span>{c.where}</span>
        <span>{c.assertions.filter((a) => a.kind !== 'quote').map((a) => a.extracted).filter(Boolean)[0] ?? ''}</span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function MoreNode({ data, id }: NodeProps) {
  const ctx = useContext(UiCtx)
  const d = data as { more: number }
  return (
    <div className={nodeClass(id, ctx, 'more-card')} style={{ width: 240 }}>
      <Handle type="target" position={Position.Left} />
      +{d.more} more claims · open the panel
    </div>
  )
}

export const nodeTypes = {
  claim: ClaimNode,
  more: MoreNode, artifact: ArtifactNode, section: SectionNode, groupCollapsed: GroupCollapsed, groupOpen: GroupOpen }
