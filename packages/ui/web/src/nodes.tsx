import { createContext, useContext } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { GroupSummary } from './layout'
import { fmt, Freshness, Status, when } from './shared'
import type { GNode } from './types'

export interface Ctx {
  selected: string | null
  matches: Set<string>
  related: Set<string>
  toggle: (group: string) => void
}
export const UiCtx = createContext<Ctx>({ selected: null, matches: new Set(), related: new Set(), toggle: () => {} })

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
      <Status ok={n.ok} fail={n.fail} problem={problem} />
      <div className="card-foot">
        <Freshness node={n} />
        <span>{n.last_checked ? `checked ${when(n.last_checked)}` : ''}</span>
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
      <Status ok={n.ok} fail={n.fail} />
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

export const nodeTypes = { artifact: ArtifactNode, section: SectionNode, groupCollapsed: GroupCollapsed, groupOpen: GroupOpen }
