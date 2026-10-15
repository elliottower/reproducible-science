import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import Catalog from './Catalog'
import Overview, { type Tab } from './Overview'
import { CitationsTab, PreregTab, ReproduceTab, ResultsTab } from './Records'
import { ClaimsPill, FixCtx } from './fix'
import { IssuesPill } from './issues'
import { ReproducedPill, ReproduceButton, type Run, VerifyButton } from './reproduce'
import { post, postWhenFree } from './api'
import { layout, summarize } from './layout'
import { nodeTypes, UiCtx } from './nodes'
import { fmt, Panel, when } from './shared'
import type { Focus, Graph } from './types'

interface Recheck {
  available: boolean
  busy: 'refresh' | 'verify' | 'reproduce' | null
  message: string | null
  run: (kind: 'refresh' | 'verify') => void
  reproduce: (only: string[] | null) => void
  /** The re-run streaming in, or the last one to finish; null before any. */
  live: Run | null
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
  const [reproOpen, setReproOpen] = useState(false)
  // Where Open in UI last took the page: the tab it opened reads it and shows that item.
  const [focus, setFocus] = useState<Focus | null>(null)
  useEffect(() => {
    document.title = graph.project_name ? `${graph.project_name} · repro ui` : 'repro ui'
  }, [graph.project_name])
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

  return (
    <UiCtx.Provider value={{ selected: shown, matches, related, toggle, openFiles, toggleFile }}>
      <div className="app">
        <header className="top">
          <div className="tabs">
            {TABS.map(([k, label]) => (
              <button key={k} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>{label}</button>
            ))}
          </div>
          <div className="spacer" />
          <ClaimsPill graph={graph} openClaims={() => setMode('claims')} />
          <ReproducedPill graph={graph} live={recheck.live} openTab={() => setMode('reproduce')} />
          <IssuesPill graph={graph} onOpen={(o) => { setMode(o.tab); setFocus({ ...o, at: Date.now() }) }} />
          {recheck.available && (
            <>
              <VerifyButton graph={graph} busy={recheck.busy === 'verify'} disabled={recheck.busy !== null && recheck.busy !== 'refresh'} run={() => recheck.run('verify')} />
              <ReproduceButton graph={graph} open={reproOpen} setOpen={setReproOpen} live={recheck.live} run={recheck.reproduce} />
            </>
          )}
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
          <PreregTab graph={graph} focus={focus?.tab === 'prereg' ? focus : null} />
        ) : mode === 'results' ? (
          <ResultsTab graph={graph} query={query} focus={focus?.tab === 'results' ? focus : null} />
        ) : mode === 'citations' ? (
          <CitationsTab graph={graph} query={query} focus={focus?.tab === 'citations' ? focus : null} />
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
  const [live, setLive] = useState<Run | null>(null)

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

  // The page re-reads the records by itself, which writes nothing: when its tab comes back into
  // view, and every 30 s while it is in view. Never while a check or a re-run is going.
  const busyRef = useRef(busy)
  busyRef.current = busy
  useEffect(() => {
    if (!available) return
    const refresh = () => {
      if (document.visibilityState !== 'visible' || busyRef.current !== null) return
      setBusy('refresh')
      post('api/refresh', {})
        .then((r) => r.json())
        .then((res) => (res.ok ? load() : undefined))
        .catch(() => undefined)
        .finally(() => setBusy((b) => (b === 'refresh' ? null : b)))
    }
    const t = setInterval(refresh, 30_000)
    document.addEventListener('visibilitychange', refresh)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', refresh) }
  }, [available])

  const run = (kind: 'refresh' | 'verify') => {
    setBusy(kind)
    setMessage(null)
    postWhenFree(`api/${kind}`, {})
      .then((r) => r.json())
      .then((res) => {
        setMessage(res.ok ? null : `${kind === 'verify' ? 'repro verify' : 'Refresh'} failed: ${res.error}`)
        return res.ok ? load() : undefined
      })
      .catch((e) => setMessage(`${kind} failed: ${e}`))
      .finally(() => setBusy(null))
  }

  /** Runs the steps and reads the answer as it streams: one JSON object per line, each printed
   * line of `repro reproduce` and then what the re-run recorded. */
  const reproduce = async (only: string[] | null) => {
    setBusy('reproduce')
    setMessage(null)
    const started = Date.now()
    let run: Run = { only, lines: [], started }
    setLive(run)
    const finish = (done: Run['done']) => {
      run = { ...run, done }
      setLive(run)
      // The result shows in the Reproduce dialog; only a failure is also said in the top bar.
      if (done && !done.ok) setMessage(`Reproduce failed: ${done.error}`)
    }
    try {
      const r = await postWhenFree('api/reproduce', { only })
      if (!r.ok || !r.body) {
        const res = await r.json().catch(() => ({}))
        finish({ ok: false, error: res.error ?? `the server answered ${r.status}`, seconds: (Date.now() - started) / 1000 })
        return
      }
      const reader = r.body.pipeThrough(new TextDecoderStream()).getReader()
      let rest = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        rest += value
        const parts = rest.split('\n')
        rest = parts.pop() ?? ''
        for (const part of parts.filter(Boolean)) {
          const event = JSON.parse(part)
          if (event.done) finish(event)
          else { run = { ...run, lines: [...run.lines, event.line] }; setLive(run) }
        }
      }
      if (!run.done) finish({ ok: false, error: 'the connection closed before the re-run finished', seconds: (Date.now() - started) / 1000 })
      await load()
    } catch (e) {
      finish({ ok: false, error: String(e), seconds: (Date.now() - started) / 1000 })
    } finally {
      setBusy(null)
    }
  }

  if (error) return <div className="center">{error}</div>
  if (!graph) return <div className="center muted">Loading…</div>
  return (
    <FixCtx.Provider value={{ project: projectPath }}>
      <ReactFlowProvider>
        <Canvas graph={graph} recheck={{ available, busy, message, run, reproduce, live }} />
      </ReactFlowProvider>
    </FixCtx.Provider>
  )
}
