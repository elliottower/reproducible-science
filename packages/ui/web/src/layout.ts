import ELK from 'elkjs/lib/elk.bundled.js'
import type { Edge, Node } from '@xyflow/react'
import type { ClaimRow, GNode, Graph } from './types'

const elk = new ELK()

export const SIZE = {
  artifact: { w: 270, h: 92 },
  section: { w: 210, h: 66 },
  collapsed: { w: 270, h: 96 },
  claim: { w: 240, h: 58 },
}

/** Claims drawn under an opened file; the rest are one "+N more" card that opens the panel. */
export const CLAIMS_SHOWN = 12

export interface GroupSummary {
  id: string
  kind: 'files' | 'sections'
  members: GNode[]
  ok: number
  fail: number
  problems: number
  staleFiles: number
  matches: number
}

/** Map each node to what is visible for it: itself when its group is open, its group otherwise. */
function visibleId(n: GNode, open: Set<string>): string {
  return open.has(n.group) ? n.id : `group:${n.group}`
}

export function summarize(graph: Graph, matches: Set<string>): Map<string, GroupSummary> {
  const out = new Map<string, GroupSummary>()
  for (const g of graph.groups) {
    out.set(g.id, { id: g.id, kind: g.kind, members: [], ok: 0, fail: 0, problems: 0, staleFiles: 0, matches: 0 })
  }
  for (const n of graph.nodes) {
    const s = out.get(n.group)!
    s.members.push(n)
    if (n.type === 'section') {
      s.ok += n.ok
      s.fail += n.fail
    }
    if (n.fail > 0 || (n.state && n.state !== 'pinned')) s.problems += 1
    if (n.freshness === 'stale') s.staleFiles += 1
    if (matches.has(n.id)) s.matches += 1
  }
  // A file group's claim count is the distinct claims that read any of its files.
  for (const s of out.values()) {
    if (s.kind !== 'files') continue
    const seen = new Map<string, boolean>()
    for (const m of s.members) for (const c of m.claims) seen.set(c.id, (seen.get(c.id) ?? true) && c.ok)
    s.ok = [...seen.values()].filter(Boolean).length
    s.fail = seen.size - s.ok
  }
  return out
}

export async function layout(
  graph: Graph,
  open: Set<string>,
  groups: Map<string, GroupSummary>,
  openFiles: Set<string> = new Set(),
): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const sectionId = (section: string) => `sec:${section}`

  // An opened file or paper section draws its claims as cards in its own group. A file's cards are
  // wired file -> claim -> section, a section's cards file -> claim -> section; either replaces the
  // opened node's direct edges.
  type Card = { owner: string; group: string; claim?: ClaimRow; more?: number }
  const claimCards = new Map<string, Card[]>()
  const replacedFrom = new Set<string>()
  const replacedTo = new Set<string>()
  for (const oid of openFiles) {
    const o = byId.get(oid)
    if (!o || !open.has(o.group) || o.claims.length === 0) continue
    if (o.type === 'artifact') replacedFrom.add(oid)
    else replacedTo.add(oid)
    const sorted = [...o.claims].sort((a, b) => Number(a.ok) - Number(b.ok))
    const cards: Card[] = sorted.slice(0, CLAIMS_SHOWN).map((c) => ({ owner: oid, group: o.group, claim: c }))
    if (sorted.length > CLAIMS_SHOWN) cards.push({ owner: oid, group: o.group, more: sorted.length - CLAIMS_SHOWN })
    claimCards.set(oid, cards)
  }
  const cardId = (owner: string, c: { claim?: ClaimRow; more?: number }) => (c.claim ? `claim:${owner}::${c.claim.id}` : `more:${owner}`)

  // Visible edges, with parallel edges between the same visible pair merged and counted.
  const merged = new Map<string, { source: string; target: string; kinds: Set<string>; count: number }>()
  for (const e of graph.edges) {
    if (e.kind === 'supports' && (replacedFrom.has(e.source) || replacedTo.has(e.target))) continue
    const s = byId.get(e.source)
    const t = byId.get(e.target)
    if (!s || !t) continue
    const vs = visibleId(s, open)
    const vt = visibleId(t, open)
    if (vs === vt) continue
    const key = `${vs}->${vt}`
    const m = merged.get(key) ?? { source: vs, target: vt, kinds: new Set(), count: 0 }
    m.kinds.add(e.kind)
    m.count += e.count ?? 0
    merged.set(key, m)
  }

  const addEdge = (source: string, target: string, kind: string, count = 0) => {
    const key = `${source}->${target}`
    const m = merged.get(key) ?? { source, target, kinds: new Set(), count: 0 }
    m.kinds.add(kind)
    m.count += count
    merged.set(key, m)
  }
  for (const [oid, cards] of claimCards) {
    const owner = byId.get(oid)!
    for (const c of cards) {
      const id = cardId(oid, c)
      if (owner.type === 'artifact') {
        addEdge(oid, id, 'reads')
        if (c.claim) {
          const sec = byId.get(sectionId(c.claim.section))
          if (sec) addEdge(id, visibleId(sec, open), 'supports')
        }
      } else {
        addEdge(id, oid, 'supports')
        const files = new Set((c.claim?.assertions ?? []).filter((a) => a.kind !== 'quote').map((a) => a.artifact))
        for (const f of files) {
          const fn = byId.get(f)
          if (fn) addEdge(visibleId(fn, open), id, 'reads')
        }
      }
    }
  }

  const children: any[] = []
  for (const g of graph.groups) {
    const s = groups.get(g.id)!
    if (open.has(g.id)) {
      children.push({
        id: `group:${g.id}`,
        layoutOptions: { 'elk.padding': '[top=48,left=16,bottom=16,right=16]' },
        children: [
          ...s.members.map((n) => ({ id: n.id, width: SIZE[n.type].w, height: SIZE[n.type].h })),
          ...[...claimCards.entries()]
            .filter(([oid]) => byId.get(oid)?.group === g.id)
            .flatMap(([oid, cards]) => cards.map((c) => ({ id: cardId(oid, c), width: SIZE.claim.w, height: c.more ? 40 : SIZE.claim.h }))),
        ],
      })
    } else {
      children.push({ id: `group:${g.id}`, width: SIZE.collapsed.w, height: SIZE.collapsed.h })
    }
  }

  const res = await elk.layout({
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      'elk.layered.spacing.nodeNodeBetweenLayers': '90',
      'elk.spacing.nodeNode': '28',
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.edgeRouting': 'SPLINES',
    },
    children,
    edges: [...merged.values()].map((m, i) => ({ id: `e${i}`, sources: [m.source], targets: [m.target] })),
  })

  const nodes: Node[] = []
  for (const c of res.children ?? []) {
    const gid = c.id.slice('group:'.length)
    const s = groups.get(gid)!
    if (open.has(gid)) {
      nodes.push({
        id: c.id,
        type: 'groupOpen',
        position: { x: c.x ?? 0, y: c.y ?? 0 },
        data: { summary: s },
        style: { width: c.width, height: c.height },
        selectable: false,
      })
      for (const k of c.children ?? []) {
        if (k.id.startsWith('claim:') || k.id.startsWith('more:')) {
          const fid = k.id.startsWith('more:') ? k.id.slice(5) : k.id.slice(6, k.id.indexOf('::'))
          const card = claimCards.get(fid)!.find((x) => cardId(fid, x) === k.id)!
          nodes.push({
            id: k.id,
            type: card.more ? 'more' : 'claim',
            parentId: c.id,
            extent: 'parent',
            position: { x: k.x ?? 0, y: k.y ?? 0 },
            data: { claim: card.claim, file: fid, more: card.more },
          })
          continue
        }
        const n = byId.get(k.id)!
        nodes.push({
          id: k.id,
          type: n.type,
          parentId: c.id,
          extent: 'parent',
          position: { x: k.x ?? 0, y: k.y ?? 0 },
          data: { node: n },
        })
      }
    } else {
      nodes.push({
        id: c.id,
        type: 'groupCollapsed',
        position: { x: c.x ?? 0, y: c.y ?? 0 },
        data: { summary: s },
      })
    }
  }

  const edges: Edge[] = [...merged.values()].map((m) => {
    const regen = m.kinds.has('regenerates') && !m.kinds.has('supports')
    const reads = m.kinds.has('reads')
    return {
      id: `${m.source}->${m.target}`,
      source: m.source,
      target: m.target,
      type: 'default',
      label: m.count ? `${m.count} claim${m.count === 1 ? '' : 's'}` : undefined,
      data: { regen },
      className: regen ? 'edge-regen' : reads ? 'edge-reads' : 'edge-supports',
    }
  })
  return { nodes, edges }
}
