import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import Catalog from './Catalog'
import Overview, { type Tab } from './Overview'
import { CitationsTab, PreregTab, ReproduceTab, ResultsTab } from './Records'
import { FixCtx, ProblemPill, projectPrompt } from './fix'
import { ReproduceButton, VerifyButton } from './reproduce'
import { post } from './api'
import { layout, summarize } from './layout'
import { nodeTypes, UiCtx } from './nodes'
import { fmt, Panel, when } from './shared'
import type { Graph } from './types'

interface Recheck {
  available: boolean
  busy: 'refresh' | 'verify' | 'reproduce' | null
  message: string | null
  run: (kind: 'refresh' | 'verify') => void
  reproduce: (only: string[] | null) => void
  /** false when nothing is re-running; otherwise the steps re-running, null meaning all. */
  reproducing: string[] | null | false
}

function Canvas({ graph, recheck }: { graph: Graph; recheck: Recheck }) {
  const initial = useMemo(() => new URLSearchParams(window.location.hash.slice(1)), [])
  const [open, setOpen] = useState<Set<string>>(
    new Set((initial.get('open') ?? '').split('|').filter((g) => graph.groups.some((x) => x.id === g))),
  )
  const [selected, setSelected] = useState<string | null>(initial.get('sel'))
  const [openFiles, setOpenFiles] = useState<Set<string>>(new Set((initial.get('files') ?? '').split('|').filter(Boolean)))
  const [query, setQuery] = useState('')
  const TABS: [Tab, string][] = [
    ['overview', 'Overview'], ['prereg', 'Prereg'], ['results', 'Results'], ['citations', 'Citations'],
    ['claims', 'Claims'], ['reproduce', 'Reproduce'], ['graph', 'Graph'],
  ]
  const [mode, setMode] = useState<Tab>(TABS.map(([k]) => k).find((v) => v === initial.get('view')) ?? 'overview')
  const [flow, setFlow] = useState<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] })
  const rf = useReactFlow()
  const fitted = useRef(false)
  // The group or file being opened or closed, and where it sat on screen. After the new layout,
  // the view is moved so that node stays put, instead of everything jumping.
  const anchor = useRef<{ id: string; x: number; y: number } | null>(null)
  const pin = (id: string) => {
    const n = rf.getInternalNode(id)
    if (!n) return
    const s = rf.flowToScreenPosition(n.internals.positionAbsolute)
    anchor.current = { id, x: s.x, y: s.y }
  }

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
    layout(graph, open, groups, openFiles).then((r) => {
      if (!live) return
      setFlow(r)
      const a = anchor.current
      anchor.current = null
      if (a) {
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const n = rf.getInternalNode(a.id)
          if (!n) return
          const s = rf.flowToScreenPosition(n.internals.positionAbsolute)
          const vp = rf.getViewport()
          rf.setViewport({ x: vp.x + a.x - s.x, y: vp.y + a.y - s.y, zoom: vp.zoom })
        }))
      }
      // Fit once, when the graph first appears; afterwards the zoom is the reader's.
      if (!fitted.current) {
        fitted.current = true
        requestAnimationFrame(() => rf.fitView({ padding: 0.08, duration: 300 }))
      }
    })
    return () => { live = false }
    // groups changes with every search keystroke; layout only depends on which groups are open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, open, openFiles])

  const toggle = (g: string) => {
    pin(`group:${g}`)
    if (selected === `group:${g}`) setSelected(null)
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(g)) next.delete(g)
      else next.add(g)
      return next
    })
  }

  const toggleFile = (f: string) => {
    pin(f)
    setOpenFiles((prev) => {
      const next = new Set(prev)
      if (next.has(f)) next.delete(f)
      else next.add(f)
      return next
    })
  }

  // Highlight the selected node's upstream and downstream lineage.
  // A selection that is not drawn (a group just opened, a claim folded away) highlights nothing,
  // rather than dimming everything.
  const shown = selected && flow.nodes.some((n) => n.id === selected) ? selected : null
  const related = useMemo(() => {
    const r = new Set<string>()
    if (!shown) return r
    r.add(shown)
    const walk = (dir: 'up' | 'down') => {
      const stack = [shown]
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
  }, [shown, flow.edges])

  const edges = useMemo(
    () =>
      flow.edges.map((e) => {
        const on = shown && related.has(e.source) && related.has(e.target)
        return {
          ...e,
          label: on ? e.label : undefined,
          className: `${e.className} ${on ? 'edge-on' : shown ? 'edge-dim' : ''}`,
        }
      }),
    [flow.edges, shown, related],
  )

  const expandMatches = () =>
    setOpen(new Set([...groups.values()].filter((s) => s.matches > 0).map((s) => s.id)))

  useEffect(() => {
    const h = new URLSearchParams()
    if (open.size) h.set('open', [...open].join('|'))
    if (selected) h.set('sel', selected)
    if (openFiles.size) h.set('files', [...openFiles].join('|'))
    if (mode !== 'graph') h.set('view', mode)
    window.history.replaceState(null, '', `#${h.toString()}`)
  }, [open, selected, mode, openFiles])

  const failing = graph.totals.failing
  const needRerun = graph.nodes.filter((n) => n.type === 'artifact' && (n.freshness === 'stale' || n.freshness === 'never_rerun')).length

  return (
    <UiCtx.Provider value={{ selected: shown, matches, related, toggle, openFiles, toggleFile }}>
      <div className="app">
        <header className="top">
          <div className="brand mono">{graph.project_name ?? 'Claim lineage'}</div>
          <div className="tabs">
            {TABS.map(([k, label]) => (
              <button key={k} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>{label}</button>
            ))}
          </div>
          <div className="spacer" />
          {failing > 0 ? (
            <ProblemPill className="bad" label={`● ${fmt(failing)} failing`} subject="project"
              what={`${fmt(failing)} claim${failing === 1 ? '' : 's'} no longer match the file they read.`}
              prompt={projectPrompt(graph, graph.project_dir ?? null)}
              title={graph.totals.last_check ? `last check ${when(graph.totals.last_check)}` : undefined} />
          ) : (
            <span className="pill big good"
              title={graph.totals.last_check ? `${fmt(graph.totals.assertions)} assertions over ${fmt(graph.totals.artifacts)} files · last check ${when(graph.totals.last_check)}` : undefined}>
              ● {fmt(graph.totals.claims)} verified
            </span>
          )}
          {needRerun > 0 && (
            <ProblemPill className="stale" label={`◐ ${needRerun} need re-run`} subject="project"
              what={<>{needRerun} {needRerun === 1 ? 'file whose rebuild step' : 'files whose rebuild steps'} changed since the last <code>repro reproduce</code>, or {needRerun === 1 ? 'was' : 'were'} never re-run.</>}
              prompt={projectPrompt(graph, graph.project_dir ?? null)} />
          )}
          {recheck.available && (
            <>
              <button className="recheck" onClick={() => recheck.run('refresh')} disabled={recheck.busy !== null}
                title="Re-read the records (repro stale, results verify, prereg check, the ledger and the check history). Writes nothing.">
                {recheck.busy === 'refresh' ? 'Refreshing…' : <><span className="refresh-icon">⟳</span> Refresh</>}
              </button>
              <VerifyButton graph={graph} busy={recheck.busy === 'verify'} disabled={recheck.busy !== null} run={() => recheck.run('verify')} />
            </>
          )}
          {recheck.available && <ReproduceButton graph={graph} busy={recheck.reproducing} run={recheck.reproduce} />}
          {recheck.message && <span className="error-note">{recheck.message}</span>}
        </header>
        <div className="toolbar" style={mode === 'overview' ? { display: 'none' } : undefined}>
          <input
            className="search"
            placeholder={({
              prereg: 'Search plans', results: 'Search runs, notes and files', citations: 'Search sources, quotations and interpretations',
              claims: 'Search claims, sections and files', reproduce: 'Search rebuild steps and commands', graph: 'Search files, sections, claim text… (e.g. 1,062 or timings)',
            } as Record<string, string>)[mode] ?? 'Search'}
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
        ) : mode === 'prereg' ? (
          <PreregTab graph={graph} />
        ) : mode === 'results' ? (
          <ResultsTab graph={graph} query={query} />
        ) : mode === 'citations' ? (
          <CitationsTab graph={graph} query={query} />
        ) : mode === 'reproduce' ? (
          <ReproduceTab graph={graph} query={query} />
        ) : mode === 'claims' ? (
          <Catalog graph={graph} query={query} />
        ) : (
          <div className="body">
            <div className="canvas">
              <div className="graph-key-box">
                <span className="mono"><span className="ov-cmd">graph:</span> the files and runs behind each claim</span>
                <span className="muted small">files left, paper sections right · solid: claims read this file · dashed: a rebuild step makes it</span>
              </div>
              <ReactFlow
                nodes={flow.nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodeClick={(_, n) => {
                if (n.type === 'groupOpen') return setSelected(null)
                setSelected(n.type === 'more' ? (n.data as { file: string }).file : n.id)
                // A group or a "more" card is opened in place; only a single node is panned to.
                if (n.type === 'more' || n.id.startsWith('group:')) return
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
            {selected && (
              <Panel
                graph={graph}
                id={selected}
                onClose={() => setSelected(null)}
                onExpand={toggle}
                onPick={(node, group) => {
                  setOpen((prev) => new Set([...prev, group]))
                  setSelected(node)
                  if (graph.nodes.find((n) => n.id === node)?.claims.length) setOpenFiles((prev) => new Set([...prev, node]))
                }}
              />
            )}
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
  const [busy, setBusy] = useState<'refresh' | 'verify' | 'reproduce' | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [reproducing, setReproducing] = useState<string[] | null | false>(false)

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
    post(`api/${kind}`, {})
      .then((r) => r.json())
      .then((res) => {
        setMessage(res.ok ? null : `${kind === 'verify' ? 'repro verify' : 'Refresh'} failed: ${res.error}`)
        return res.ok ? load() : undefined
      })
      .catch((e) => setMessage(`${kind} failed: ${e}`))
      .finally(() => setBusy(null))
  }

  const reproduce = (only: string[] | null) => {
    setBusy('reproduce')
    setReproducing(only)
    setMessage(null)
    post('api/reproduce', { only })
      .then((r) => r.json())
      .then((res) => {
        const counts = Object.entries(res.counts ?? {}).map(([k, v]) => `${v} ${k}`).join(', ')
        setMessage(res.ok ? `Reproduce: ${counts} in ${res.seconds} s` : `Reproduce failed: ${res.error}`)
        return load()
      })
      .catch((e) => setMessage(`Reproduce failed: ${e}`))
      .finally(() => { setBusy(null); setReproducing(false) })
  }

  if (error) return <div className="center">{error}</div>
  if (!graph) return <div className="center muted">Loading…</div>
  return (
    <FixCtx.Provider value={{ available, project: projectPath }}>
      <ReactFlowProvider>
        <Canvas graph={graph} recheck={{ available, busy, message, run, reproduce, reproducing }} />
      </ReactFlowProvider>
    </FixCtx.Provider>
  )
}
