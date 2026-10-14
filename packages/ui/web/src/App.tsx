import { useEffect, useMemo, useState } from 'react'
import { Background, Controls, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import Catalog from './Catalog'
import { layout, summarize } from './layout'
import { nodeTypes, UiCtx } from './nodes'
import { fmt, Panel, when } from './shared'
import type { Graph } from './types'

function Canvas({ graph }: { graph: Graph }) {
  const initial = useMemo(() => new URLSearchParams(window.location.hash.slice(1)), [])
  const [open, setOpen] = useState<Set<string>>(
    new Set((initial.get('open') ?? '').split('|').filter((g) => graph.groups.some((x) => x.id === g))),
  )
  const [selected, setSelected] = useState<string | null>(initial.get('sel'))
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<'graph' | 'catalog'>(initial.get('view') === 'catalog' ? 'catalog' : 'graph')
  const [flow, setFlow] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] })
  const rf = useReactFlow()

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return new Set<string>()
    return new Set(
      graph.nodes
        .filter((n) =>
          [n.id, n.path ?? '', n.label ?? '', ...n.claims.map((c) => `${c.id} ${c.text}`)].some((s) => s.toLowerCase().includes(q)),
        )
        .map((n) => n.id),
    )
  }, [graph, query])

  const groups = useMemo(() => summarize(graph, matches), [graph, matches])

  useEffect(() => {
    let live = true
    layout(graph, open, groups).then((r) => {
      if (!live) return
      setFlow(r)
      requestAnimationFrame(() => rf.fitView({ padding: 0.08, duration: 300 }))
    })
    return () => { live = false }
    // groups changes with every search keystroke; layout only depends on which groups are open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, open])

  const toggle = (g: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(g)) next.delete(g)
      else next.add(g)
      return next
    })

  // Highlight the selected node's upstream and downstream lineage.
  const related = useMemo(() => {
    const r = new Set<string>()
    if (!selected) return r
    r.add(selected)
    const walk = (dir: 'up' | 'down') => {
      const stack = [selected]
      while (stack.length) {
        const cur = stack.pop()!
        for (const e of flow.edges) {
          const nxt = dir === 'down' ? (e.source === cur ? e.target : null) : (e.target === cur ? e.source : null)
          if (nxt && !r.has(nxt)) { r.add(nxt); stack.push(nxt) }
        }
      }
    }
    walk('up'); walk('down')
    return r
  }, [selected, flow.edges])

  const edges = useMemo(
    () =>
      flow.edges.map((e) => {
        const on = selected && related.has(e.source) && related.has(e.target)
        return {
          ...e,
          label: on ? e.label : undefined,
          className: `${e.className} ${on ? 'edge-on' : selected ? 'edge-dim' : ''}`,
        }
      }),
    [flow.edges, selected, related],
  )

  const expandMatches = () =>
    setOpen(new Set([...groups.values()].filter((s) => s.matches > 0).map((s) => s.id)))

  useEffect(() => {
    const h = new URLSearchParams()
    if (open.size) h.set('open', [...open].join('|'))
    if (selected) h.set('sel', selected)
    if (mode === 'catalog') h.set('view', 'catalog')
    window.history.replaceState(null, '', `#${h.toString()}`)
  }, [open, selected, mode])

  const failing = graph.totals.failing

  return (
    <UiCtx.Provider value={{ selected, matches, related, toggle }}>
      <div className="app">
        <header className="top">
          <div className="brand">Claim lineage</div>
          <div className="tabs">
            <button className={mode === 'graph' ? 'on' : ''} onClick={() => setMode('graph')}>Graph</button>
            <button className={mode === 'catalog' ? 'on' : ''} onClick={() => setMode('catalog')}>Catalog</button>
          </div>
          <div className="proj muted">{graph.project}</div>
          <div className="spacer" />
          <span className={`pill ${failing ? 'bad' : 'good'}`}>
            {failing ? `${fmt(failing)} claims failing` : 'All claims verified'}
          </span>
          {graph.totals.stale_steps > 0 && (
            <span className="pill stale" title="rebuild steps whose command, inputs or output changed since their last recorded re-run (repro stale)">
              ◐ {graph.totals.stale_steps} rebuild step{graph.totals.stale_steps === 1 ? '' : 's'} stale
            </span>
          )}
          <span className="muted small">
            {fmt(graph.totals.claims)} claims · {fmt(graph.totals.assertions)} assertions · {fmt(graph.totals.artifacts)} files
            {graph.totals.last_check ? ` · last check ${when(graph.totals.last_check)}` : ''}
          </span>
        </header>
        <div className="toolbar">
          <input
            className="search"
            placeholder="Search files, sections, claim text… (e.g. 1,062 or timings)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {mode === 'graph' && matches.size > 0 && (
            <button onClick={expandMatches}>Open {matches.size} match{matches.size === 1 ? '' : 'es'}</button>
          )}
          {mode === 'graph' && <button onClick={() => setOpen(new Set(graph.groups.map((g) => g.id)))}>Expand all</button>}
          {mode === 'graph' && <button onClick={() => setOpen(new Set())}>Collapse all</button>}
        </div>
        {mode === 'catalog' ? (
          <Catalog graph={graph} query={query} />
        ) : (
          <div className="body">
            <div className="canvas">
              <ReactFlow
                nodes={flow.nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodeClick={(_, n) => setSelected(n.type === 'groupOpen' ? null : n.id)}
                onPaneClick={() => setSelected(null)}
                onNodeDoubleClick={(_, n) => n.id.startsWith('group:') && toggle(n.id.slice(6))}
                nodesDraggable={false}
                minZoom={0.1}
                proOptions={{ hideAttribution: true }}
              >
                <Background gap={18} size={1} color="#d4d7de" />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
            {selected && <Panel graph={graph} id={selected} onClose={() => setSelected(null)} onExpand={toggle} />}
          </div>
        )}
      </div>
    </UiCtx.Provider>
  )
}

export default function App() {
  const [graph, setGraph] = useState<Graph | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    fetch('graph.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`graph.json: ${r.status}`))))
      .then(setGraph)
      .catch((e) => setError(String(e)))
  }, [])
  if (error) return <div className="center">{error}</div>
  if (!graph) return <div className="center muted">Loading…</div>
  return (
    <ReactFlowProvider>
      <Canvas graph={graph} />
    </ReactFlowProvider>
  )
}
