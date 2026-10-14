import { useEffect, useMemo, useState } from 'react'
import { Background, Controls, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import Catalog from './Catalog'
import Overview from './Overview'
import { ClaudeButton, FixCtx, projectPrompt } from './fix'
import { layout, summarize } from './layout'
import { nodeTypes, UiCtx } from './nodes'
import { fmt, Panel, when } from './shared'
import type { Graph } from './types'

interface Recheck {
  available: boolean
  busy: 'refresh' | 'verify' | null
  message: string | null
  run: (kind: 'refresh' | 'verify') => void
}

function Canvas({ graph, recheck }: { graph: Graph; recheck: Recheck }) {
  const initial = useMemo(() => new URLSearchParams(window.location.hash.slice(1)), [])
  const [open, setOpen] = useState<Set<string>>(
    new Set((initial.get('open') ?? '').split('|').filter((g) => graph.groups.some((x) => x.id === g))),
  )
  const [selected, setSelected] = useState<string | null>(initial.get('sel'))
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<'overview' | 'graph' | 'catalog'>(
    (['overview', 'catalog'] as const).find((v) => v === initial.get('view')) ?? 'graph',
  )
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
    if (mode !== 'graph') h.set('view', mode)
    window.history.replaceState(null, '', `#${h.toString()}`)
  }, [open, selected, mode])

  const failing = graph.totals.failing

  return (
    <UiCtx.Provider value={{ selected, matches, related, toggle }}>
      <div className="app">
        <header className="top">
          <div className="brand">Claim lineage</div>
          <div className="tabs">
            <button className={mode === 'overview' ? 'on' : ''} onClick={() => setMode('overview')}>Overview</button>
            <button className={mode === 'graph' ? 'on' : ''} onClick={() => setMode('graph')}>Graph</button>
            <button className={mode === 'catalog' ? 'on' : ''} onClick={() => setMode('catalog')}>Catalog</button>
          </div>
          <div className="spacer" />
          <span
            className={`pill big ${failing ? 'bad' : 'good'}`}
            title={graph.totals.last_check ? `${fmt(graph.totals.assertions)} assertions over ${fmt(graph.totals.artifacts)} files · last check ${when(graph.totals.last_check)}` : undefined}
          >
            ● {failing ? `${fmt(failing)} claims failing` : `${fmt(graph.totals.claims)} claims verified`}
          </span>
          {graph.totals.stale_steps > 0 && (
            <span className="pill big stale" title="rebuild steps whose command, inputs or output changed since their last recorded re-run (repro stale)">
              ◐ {graph.totals.stale_steps} rebuild step{graph.totals.stale_steps === 1 ? '' : 's'} stale
            </span>
          )}
          {recheck.available && (
            <>
              <button className="recheck" onClick={() => recheck.run('refresh')} disabled={recheck.busy !== null}
                title="Re-read the records (repro stale, results verify, prereg check, the ledger and the check history). Writes nothing.">
                {recheck.busy === 'refresh' ? 'Refreshing…' : '⟳ Refresh'}
              </button>
              <button className="recheck" onClick={() => recheck.run('verify')} disabled={recheck.busy !== null}
                title="claims verify (the same check as repro verify): check every claim again. Records the check in the project's history.">
                {recheck.busy === 'verify' ? 'Verifying…' : '✓ Verify claims'}
              </button>
            </>
          )}
          <ClaudeButton prompt={projectPrompt(graph, graph.project_dir ?? null)} subject="whole project" />
          {recheck.message && <span className="error-note">{recheck.message}</span>}
        </header>
        <div className="toolbar" style={mode === 'overview' ? { display: 'none' } : undefined}>
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
        {mode === 'overview' ? (
          <Overview graph={graph} onOpen={setMode} />
        ) : mode === 'catalog' ? (
          <Catalog graph={graph} query={query} />
        ) : (
          <div className="body">
            <div className="canvas">
              <ReactFlow
                nodes={flow.nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodeClick={(_, n) => {
                if (n.type === 'groupOpen') return setSelected(null)
                setSelected(n.id)
                // Pan so the clicked node sits at the centre; the zoom stays where the reader left it.
                const inner = rf.getInternalNode(n.id)
                if (!inner) return
                const pos = inner.internals.positionAbsolute
                const w = inner.measured.width ?? 0
                const h = inner.measured.height ?? 0
                rf.setCenter(pos.x + w / 2, pos.y + h / 2, { zoom: rf.getZoom(), duration: 250 })
              }}
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
  const [available, setAvailable] = useState(false)
  const [projectPath, setProjectPath] = useState<string | null>(null)
  const [busy, setBusy] = useState<'refresh' | 'verify' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = () =>
    fetch(`graph.json?t=${Date.now()}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`graph.json: ${r.status}`))))
      .then(setGraph)
      .catch((e) => setError(String(e)))

  useEffect(() => {
    load()
    fetch('api/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => {
        setAvailable(Boolean(h?.recheck))
        setProjectPath(h?.project ?? null)
      })
      .catch(() => setAvailable(false))
  }, [])

  const run = (kind: 'refresh' | 'verify') => {
    setBusy(kind)
    setMessage(null)
    fetch(`api/${kind}`, { method: 'POST' })
      .then((r) => r.json())
      .then((res) => {
        setMessage(res.ok ? null : `${kind === 'verify' ? 'repro verify' : 'Refresh'} failed: ${res.error}`)
        return res.ok ? load() : undefined
      })
      .catch((e) => setMessage(`${kind} failed: ${e}`))
      .finally(() => setBusy(null))
  }

  if (error) return <div className="center">{error}</div>
  if (!graph) return <div className="center muted">Loading…</div>
  return (
    <FixCtx.Provider value={{ available, project: projectPath }}>
      <ReactFlowProvider>
        <Canvas graph={graph} recheck={{ available, busy, message, run }} />
      </ReactFlowProvider>
    </FixCtx.Provider>
  )
}
