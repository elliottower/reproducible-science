import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import Catalog from './Catalog'
import Overview, { type Tab } from './Overview'
import { CitationsTab, PreregTab, ResultsTab } from './Records'
import { ClaimsPill, FixCtx } from './fix'
import { IssuesBarPill, ISSUES_BAR } from './barVariant'
import { IssuesPill } from './issues'
import { Drawer } from './drawer'
import { AskAIMenu, ShareMenu, VerifyMenu } from './menus'
import { ReproduceTab, type PageRun } from './reproduceTab'
import { SearchBox, type Jump } from './search'
import { ToastHost, useToast } from './toast'
import { loadGraph, post, postWhenFree, showing, STATIC } from './api'
import { layout, summarize } from './layout'
import { nodeTypes, UiCtx } from './nodes'
import { fmt, Panel, when } from './shared'
import type { Focus, Graph } from './types'

interface Recheck {
  available: boolean
  busy: 'refresh' | 'verify' | 'reproduce' | null
  run: (kind: 'refresh' | 'verify', presubmit?: boolean) => Promise<void> | void
  /** The re-runs started from the page, newest first, as GET /api/runs reports them. */
  runs: PageRun[]
  start: (only: string[] | null) => void
  stop: (run: string) => void
  /** Switch the page to another project `repro ui` has been run in, or there and run verify. */
  openProject: (path: string) => Promise<boolean>
  verifyProject: (path: string) => Promise<void>
}

function Canvas({ graph, recheck }: { graph: Graph; recheck: Recheck }) {
  const initial = useMemo(() => new URLSearchParams(window.location.hash.slice(1)), [])
  const [open, setOpen] = useState<Set<string>>(
    new Set((initial.get('open') ?? '').split('|').filter((g) => graph.groups.some((x) => x.id === g))),
  )
  const [selected, setSelected] = useState<string | null>(initial.get('sel'))
  const [openFiles, setOpenFiles] = useState<Set<string>>(new Set((initial.get('files') ?? '').split('|').filter(Boolean)))
  const [query, setQuery] = useState('')
  const hasSteps = (graph.tabs?.reproduce.steps ?? []).length > 0
  // The Reproduce tab is there only when repro.yaml declares rebuild steps.
  const TABS: [Tab, string][] = ([
    ['overview', 'Overview'], ['prereg', 'Prereg'], ['results', 'Results'], ['citations', 'Citations'],
    ['claims', 'Claims'], ['reproduce', 'Reproduce'], ['graph', 'Graph'],
  ] as [Tab, string][]).filter(([k]) => k !== 'reproduce' || hasSteps)
  // A step the search box picked: the Reproduce tab opens its panel.
  const [stepFocus, setStepFocus] = useState<{ step: string; at: number } | null>(null)
  const [drawer, setDrawer] = useState(false)
  // Where Open in UI last took the page: the tab it opened reads it and shows that item.
  const [focus, setFocus] = useState<Focus | null>(null)
  /** Any other way to a tab drops the Open in UI target, so it is not applied again. */
  const go = (m: Tab) => { setMode(TABS.some(([k]) => k === m) ? m : 'overview'); setFocus(null); setStepFocus(null) }
  const jump = (j: Jump) => {
    const at = Date.now()
    if (j.kind === 'claim') { go('claims'); setQuery(j.id) }
    else if (j.kind === 'quote') { setQuery(''); setMode('citations'); setFocus({ tab: 'citations', quote: { file: j.file, statement: j.statement, index: j.index }, at }) }
    else if (j.kind === 'source') { setQuery(''); setMode('citations'); setFocus({ tab: 'citations', source: j.file, at }) }
    else if (j.kind === 'step') { go('reproduce'); setQuery(''); setStepFocus({ step: j.id, at }) }
    else {
      go('graph')
      setQuery('')
      const group = graph.nodes.find((n) => n.id === j.id)?.group
      if (group) setOpen((prev) => new Set([...prev, group]))
      setSelected(j.id)
    }
  }
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
          {!STATIC && recheck.available && (
            <button className="burger" onClick={() => setDrawer(true)} title="Projects">☰</button>
          )}
          <div className="tabs">
            {TABS.map(([k, label]) => (
              <button key={k} className={mode === k ? 'on' : ''} onClick={() => go(k)}>{label}</button>
            ))}
          </div>
          <span className="spacer" />
          <SearchBox graph={graph} onJump={jump} />
          <span className="spacer" />
          <ClaimsPill graph={graph} openClaims={() => go('claims')} />
          {ISSUES_BAR ? (
            <>
              <IssuesBarPill graph={graph} onOpen={(o) => { setMode(o.tab); setFocus({ ...o, at: Date.now() }) }}
                busy={recheck.busy === 'verify'} serverless={STATIC || !recheck.available} verify={() => recheck.run('verify')} />
            </>
          ) : (
            <>
              <IssuesPill graph={graph} onOpen={(o) => { setMode(o.tab); setFocus({ ...o, at: Date.now() }) }} />
              <VerifyMenu graph={graph} busy={recheck.busy === 'verify'} serverless={STATIC || !recheck.available} run={(presubmit) => recheck.run('verify', presubmit)} />
              <AskAIMenu graph={graph} />
            </>
          )}
          <ShareMenu graph={graph} />
        </header>
        <div className="toolbar" style={mode === 'overview' ? { display: 'none' } : undefined}>
          <input
            className="search"
            placeholder={({
              prereg: 'Search preregistrations', results: 'Search runs, notes and files', citations: 'Search sources, quotations and interpretations',
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
          <Overview graph={graph} onOpen={go} />
        ) : mode === 'prereg' ? (
          <PreregTab graph={graph} focus={focus?.tab === 'prereg' ? focus : null} />
        ) : mode === 'results' ? (
          <ResultsTab graph={graph} query={query} focus={focus?.tab === 'results' ? focus : null} />
        ) : mode === 'citations' ? (
          <CitationsTab graph={graph} query={query} focus={focus?.tab === 'citations' ? focus : null} />
        ) : mode === 'reproduce' ? (
          <ReproduceTab graph={graph} query={query} runs={recheck.runs} start={recheck.start} stop={recheck.stop} focus={stepFocus} serverless={STATIC || !recheck.available} />
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
        {!STATIC && <Drawer open={drawer} onClose={() => setDrawer(false)} onOpen={recheck.openProject} onVerify={recheck.verifyProject} />}
      </div>
    </UiCtx.Provider>
  )
}

export default function App() {
  return (
    <ToastHost>
      <Page />
    </ToastHost>
  )
}

function Page() {
  const [graph, setGraph] = useState<Graph | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [available, setAvailable] = useState(false)
  const [projectPath, setProjectPath] = useState<string | null>(null)
  const [busy, setBusy] = useState<'refresh' | 'verify' | null>(null)
  const [runs, setRuns] = useState<PageRun[]>([])
  const graphRef = useRef<Graph | null>(null)
  graphRef.current = graph
  const toast = useToast()

  const load = () =>
    loadGraph()
      .then((g) => { showing((g as Graph).project_dir); setGraph(g as Graph) })
      .catch((e) => setError(String(e)))

  useEffect(() => {
    load()
    if (STATIC) return
    fetch('api/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => {
        setAvailable(Boolean(h?.recheck))
        setProjectPath(h?.project ?? null)
      })
      .catch(() => setAvailable(false))
  }, [])

  // The page re-reads the records by itself, which writes nothing: when its tab comes back into
  // view, and every 30 s while it is in view. Never while a check is going.
  const busyRef = useRef(busy)
  busyRef.current = busy
  // A refresh asked for while another refresh or a check is going runs once that one ends,
  // rather than being dropped: a run that ended meanwhile would otherwise show its old result.
  const again = useRef(false)
  const refresh = (): Promise<void> => {
    if (busyRef.current !== null) { again.current = true; return Promise.resolve() }
    again.current = false
    busyRef.current = 'refresh'
    setBusy('refresh')
    return post('api/refresh', {})
      .then((r) => r.json())
      // Another tab switched the server to another project: said once, at the foot of the page.
      .then((res) => (res.ok ? load() : /another project/.test(res.error ?? '') ? toast(res.error) : undefined))
      .catch(() => undefined)
      .finally(() => {
        busyRef.current = null
        setBusy((b) => (b === 'refresh' ? null : b))
        if (again.current) refresh()
      })
  }
  useEffect(() => {
    if (!available) return
    const tick = () => { if (document.visibilityState === 'visible') refresh() }
    const t = setInterval(tick, 30_000)
    document.addEventListener('visibilitychange', tick)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', tick) }
  }, [available])

  // The re-runs started from the page: read every 2 s while one is going, every 15 s otherwise.
  // When one ends, the records are re-read so its result shows.
  const runningRef = useRef<Set<string>>(new Set())
  const readRuns = () =>
    fetch('api/runs')
      .then((r) => (r.ok ? r.json() : { runs: [] }))
      .then((body: { runs: PageRun[] }) => {
        setRuns(body.runs)
        const now = new Set(body.runs.filter((r) => r.state === 'running').map((r) => r.run_id))
        const ended = [...runningRef.current].some((id) => !now.has(id))
        runningRef.current = now
        // Also a run that ended after the data was built, while no page was watching.
        const built = graphRef.current?.built_at ?? ''
        const newer = body.runs.some((r) => r.state === 'done' && (r.ended_at ?? '') > built)
        if (ended || newer) refresh()
      })
      .catch(() => undefined)
  const anyRunning = runs.some((r) => r.state === 'running')
  useEffect(() => {
    if (!available) return
    readRuns()
    const t = setInterval(readRuns, anyRunning ? 2000 : 15_000)
    return () => clearInterval(t)
  }, [available, anyRunning])

  const run = (kind: 'refresh' | 'verify', presubmit = false) => {
    if (STATIC) return
    busyRef.current = kind
    setBusy(kind)
    return postWhenFree(`api/${kind}`, { presubmit })
      .then((r) => r.json())
      .then((res) => {
        // Said once, at the foot of the page; the bar only ever shows the button's own state.
        if (!res.ok) toast(`${kind === 'verify' ? 'repro verify' : 'Refresh'} failed: ${res.error}`)
        return res.ok ? load() : undefined
      })
      .catch((e) => toast(`${kind === 'verify' ? 'repro verify' : 'Refresh'} failed: ${e}`))
      .finally(() => {
        busyRef.current = null
        setBusy(null)
        if (again.current) refresh()
      })
  }

  const start = (only: string[] | null) =>
    post('api/reproduce', { only })
      .then((r) => r.json())
      .then((res) => {
        if (!res.ok) return toast(`Could not start: ${res.error}`)
        toast(only ? `Running ${only.join(', ')}` : 'Running every step')
        return readRuns()
      })
      .catch((e) => toast(`Could not start: ${e}`))

  const stop = (runId: string) =>
    post('api/stop', { run: runId })
      .then((r) => r.json())
      .then((res) => { toast(res.ok ? 'Stopping the run' : `Could not stop: ${res.error}`); return readRuns() })
      .catch((e) => toast(`Could not stop: ${e}`))

  /** Switch to another project: the server builds its data, and the page starts over on it. */
  /** Switch to another project; true once the page shows it. */
  const openProject = async (path: string): Promise<boolean> => {
    toast('Opening the project…')
    try {
      const res = await post('api/projects/open', { path }).then((r) => r.json())
      if (!res.ok) { toast(`Could not open it: ${res.error}`); return false }
      setProjectPath(res.project)
      runningRef.current = new Set()
      window.history.replaceState(null, '', '#')
      await load()
      setRuns([])
      return true
    } catch (e) {
      toast(`Could not open it: ${e}`)
      return false
    }
  }
  /** Open the project and verify it there; nothing runs where the switch did not happen. */
  const verifyProject = async (path: string) => {
    if (await openProject(path)) await run('verify')
  }

  if (error) return <div className="center">{error}</div>
  if (!graph) return <div className="center muted">Loading…</div>
  return (
    <FixCtx.Provider value={{ project: graph.project_dir ?? projectPath ?? null }}>
      <ReactFlowProvider>
        <Canvas key={graph.project_dir ?? ''} graph={graph} recheck={{ available, busy, run, runs, start, stop, openProject, verifyProject }} />
      </ReactFlowProvider>
    </FixCtx.Provider>
  )
}
