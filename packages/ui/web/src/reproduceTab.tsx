import { useContext, useEffect, useMemo, useState } from 'react'
import { FixCtx } from './fix'
import {
  changedSaid, clock, duration, fmt, reproduceCommand, sortRows, staticMessage, stepLog, terminalCommand,
  type SortKey, type StepRow, type StepState,
} from './format'
import { DiffView } from './issues'
import { useCopy, useToast } from './toast'
import type { Graph } from './types'

/** A re-run started from the page, as GET /api/runs reports it. */
export interface PageRun {
  run_id: string
  pid: number
  only: string[] | null
  started_at: string
  log: string
  state: 'running' | 'done' | 'interrupted'
  ended_at?: string
  steps?: { id: string; state: string; seconds: number | null; detail: string; exit_code: number | null }[]
}

type Step = NonNullable<Graph['tabs']>['reproduce']['steps'][number]

const covers = (r: PageRun, id: string) => r.only === null || r.only.includes(id)

/** The newest page run that covers `id`, if any. */
export const runFor = (runs: PageRun[], id: string) => runs.find((r) => covers(r, id))

/** One row per step: the last re-run's result, or Running while a page run covers it. A step
 * whose inputs or output changed since its last re-run reads Changed, with how many files. */
export function stepRow(st: Step, runs: PageRun[]): StepRow {
  const live = runs.find((r) => r.state === 'running' && covers(r, st.id))
  const last = st.history?.find((h) => h.state !== 'not_rerun')
  const newest = runFor(runs, st.id)
  const base = { step: st.id, cmd: st.command, dur: last?.duration_seconds ?? null }
  if (live) return { ...base, when: 'now', state: 'run', detail: '', dur: null }
  const when = st.rerun_at ?? last?.ended_at ?? ''
  // A page run of this step that ended with no re-run recorded, and nothing recorded since.
  if (newest?.state === 'interrupted' && (!when || when < newest.started_at)) {
    return { ...base, when: newest.started_at, state: 'int', detail: '' }
  }
  if (st.state === 'stale') return { ...base, when, state: 'changed', detail: changedSaid(st.causes) }
  if (last?.state === 'failed') return { ...base, when, state: 'err', detail: last.exit_code != null ? `exit ${last.exit_code}` : '' }
  if (last?.state === 'changed') return { ...base, when, state: 'changed', detail: 'output differs' }
  if (st.state === 'current') return { ...base, when, state: 'ok', detail: last?.bytes_identical === false ? '' : 'bytes identical' }
  return { ...base, when: '', state: 'none', detail: '' }
}

const LABEL: Record<StepState, string> = {
  run: 'Running', changed: 'Changed', err: 'Failed', int: 'Interrupted', ok: 'Reproduced', none: 'Not re-run',
}
const TONE: Record<StepState, string> = { run: 'run', changed: 'changed', err: 'err', int: 'none', ok: 'ok', none: 'none' }

const whenText = (w: string) =>
  w === 'now' ? 'Now' : w ? new Date(w).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—'

/** Seconds since `started`, ticking once a second while `on`. */
function useElapsed(started: string | undefined, on: boolean) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!on) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [on])
  return started ? Math.max(0, (now - Date.parse(started)) / 1000) : 0
}

function Result({ row, started }: { row: StepRow; started?: string }) {
  const elapsed = useElapsed(started, row.state === 'run')
  return (
    <span className={`res ${TONE[row.state]}`}>
      {row.state === 'run' ? <span className="spin" /> : <span className="dot" />}
      {row.state === 'run' ? `Running · ${clock(elapsed)}` : LABEL[row.state]}
      {row.detail && <small> · {row.detail}</small>}
    </span>
  )
}

type Filter = 'all' | 'changed' | 'ok' | 'run'
const inFilter = (f: Filter, r: StepRow) =>
  f === 'all' || (f === 'changed' ? r.state === 'changed' || r.state === 'err' : f === 'ok' ? r.state === 'ok' : r.state === 'run')

const HEADS: [SortKey, string][] = [['step', 'Step'], ['when', 'Last re-run'], ['state', 'Result'], ['dur', 'Duration'], ['cmd', 'Command']]

/** The Reproduce tab: every rebuild step repro.yaml declares, sortable and filtered, and a panel
 * for the one picked. Runs go on in the background if the page is closed. */
export function ReproduceTab({ graph, query, runs, start, stop, focus, serverless }: {
  graph: Graph
  /** No server to run anything: a click says which command to run instead. */
  serverless: boolean
  query: string
  runs: PageRun[]
  start: (only: string[] | null) => void
  stop: (run: string) => void
  focus?: { step: string; at: number } | null
}) {
  const steps = graph.tabs?.reproduce.steps ?? []
  const copy = useCopy()
  const toast = useToast()
  const rows = useMemo(() => steps.map((st) => stepRow(st, runs)), [steps, runs])
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'when', dir: -1 })
  const [sel, setSel] = useState<string | null>(null)
  useEffect(() => { if (focus) setSel(focus.step) }, [focus?.at])
  const q = query.trim().toLowerCase()
  const shown = sortRows(rows.filter((r) => inFilter(filter, r) && (!q || `${r.step} ${r.cmd}`.toLowerCase().includes(q))), sort.key, sort.dir)
  const count = (f: Filter) => rows.filter((r) => inFilter(f, r)).length
  const n = { ok: count('ok'), changed: rows.filter((r) => r.state === 'changed').length, run: count('run'), err: rows.filter((r) => r.state === 'err').length }
  const summary = [`${fmt(n.ok)} of ${fmt(rows.length)} reproduced`, n.changed ? `${fmt(n.changed)} changed` : '', n.err ? `${fmt(n.err)} failed` : '', n.run ? `${fmt(n.run)} running` : ''].filter(Boolean).join(', ')
  const runAll = () => (serverless ? toast(staticMessage('all')) : start(null))
  const click = (k: SortKey) => setSort((s) => (s.key === k ? { key: k, dir: (s.dir === 1 ? -1 : 1) } : { key: k, dir: k === 'when' ? -1 : 1 }))
  const picked = steps.find((s) => s.id === sel)
  return (
    <div className="rec">
      <div className="rp-head">
        <h1>Reproduce</h1>
        <span className="spacer" />
        <button className="btn" onClick={() => copy(terminalCommand(graph.project_dir, 'repro reproduce'), 'Copied the command')}>Copy command</button>
        <button className="btn primary" onClick={runAll} disabled={n.run > 0 && runs.some((r) => r.state === 'running' && r.only === null)}>▶ Re-run all</button>
      </div>
      <p className="rp-sub">Each step runs a command from repro.yaml and checks its output comes out the same. {summary}. Runs continue in the background if this page is closed.</p>
      <div className="chips">
        {([['all', 'All', rows.length], ['changed', 'Changed', count('changed')], ['ok', 'Reproduced', n.ok], ['run', 'Running', n.run]] as [Filter, string, number][]).map(([f, label, k]) => (
          <button key={f} className={`chip ${filter === f ? 'on' : ''}`} onClick={() => setFilter(f)}>{label} {k}</button>
        ))}
      </div>
      <table className="rp-table">
        <thead>
          <tr>
            {HEADS.map(([k, label]) => (
              <th key={k} className={sort.key === k ? 'sorted' : ''} onClick={() => click(k)}>
                {label}<span className="arrow">{sort.key === k ? (sort.dir < 0 ? '↓' : '↑') : '↕'}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.step} className={sel === r.step ? 'sel' : ''} onClick={() => setSel(r.step)}>
              <td className="mono strong">{r.step}</td>
              <td className="when">{whenText(r.when)}</td>
              <td><Result row={r} started={runs.find((x) => x.state === 'running' && covers(x, r.step))?.started_at} /></td>
              <td className="dur">{r.state === 'run' ? '' : duration(r.dur)}</td>
              <td className="mono small muted rp-cmd" title={r.cmd}>{r.cmd}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {picked && (
        <StepPanel step={picked} row={rows.find((r) => r.step === picked.id)!} run={runFor(runs, picked.id)}
          dir={graph.project_dir} onClose={() => setSel(null)} start={start} stop={stop} serverless={serverless} />
      )}
    </div>
  )
}

const CAUSE_SAID: Record<string, string> = { input_changed: 'input', output_changed: 'output' }

/** What changed since the step's last re-run, from its causes: which files (input or output) and
 * whether the command did, then where the diff is. */
function changedNote(step: Step): string {
  const files = step.causes.filter((c) => c.cause !== 'command_changed')
  const said = [
    ...files.map((c) => `${step.inputs?.find((i) => i.artifact === c.artifact)?.path || (c.artifact === step.artifact ? step.output_path : '') || c.artifact} (${CAUSE_SAID[c.cause] ?? c.cause})`),
    ...(step.causes.some((c) => c.cause === 'command_changed') ? ['the command'] : []),
  ]
  if (step.state !== 'stale') return 'The output differs from the recorded one.'
  return `Changed since the last re-run: ${said.join(', ')}.${(step.diffs ?? []).length ? ' The diff is open below.' : ''}`
}

function StepPanel({ step, row, run, dir, onClose, start, stop, serverless }: {
  serverless: boolean
  step: Step
  row: StepRow
  run: PageRun | undefined
  dir: string | undefined
  onClose: () => void
  start: (only: string[] | null) => void
  stop: (run: string) => void
}) {
  const copy = useCopy()
  const toast = useToast()
  const { project } = useContext(FixCtx)
  const running = row.state === 'run' && run?.state === 'running'
  const elapsed = useElapsed(run?.started_at, running)
  const last = step.history?.find((h) => h.state !== 'not_rerun')
  const log = run ? stepLog(run.log, step.id, run.only) : ''
  const diffs = step.diffs ?? []
  const command = reproduceCommand(dir ?? project ?? undefined, [step.id])
  return (
    <aside className="panel">
      <button className="close" onClick={onClose}>×</button>
      <div className="kicker">REBUILD STEP</div>
      <h2 className="mono">{step.id}</h2>
      <p><Result row={row} started={run?.started_at} /></p>
      {row.state === 'changed' && <div className="rp-note">{changedNote(step)}</div>}
      {row.state === 'err' && <div className="rp-note">The command failed. The log is open below.</div>}
      {row.state === 'int' && <div className="rp-note">The run stopped before it recorded a result.</div>}
      <dl className="kv2">
        <dt>Last re-run</dt><dd>{step.rerun_at ? whenText(step.rerun_at) : 'never'}</dd>
        {running ? (<><dt>Elapsed</dt><dd>{clock(elapsed)}</dd></>) : (<><dt>Duration</dt><dd>{duration(last?.duration_seconds) || '—'}</dd></>)}
        <dt>Output</dt><dd className="mono small">{step.output_path || step.artifact}</dd>
      </dl>
      <pre className="cmdbox mono">{step.command}</pre>
      <div className="rp-actions">
        {running
          ? <button className="btn" onClick={() => run && stop(run.run_id)}>Stop</button>
          : <button className="btn primary" onClick={() => (serverless ? toast(staticMessage('step', step.id)) : start([step.id]))}>▶ Run again</button>}
        <button className="btn" onClick={() => copy(command, 'Copied the command')}>Copy command</button>
      </div>
      {row.state === 'changed' && diffs.length > 0 && (
        <details open>
          <summary>Diff against the bytes the last re-run saw</summary>
          {diffs.map((d) => <DiffView key={d.label} issue={d.open.diff!} path={d.open.path!} label={d.label} />)}
        </details>
      )}
      <details open={row.state === 'err'}>
        <summary>Log</summary>
        <pre className="rp-log">{log || [
          `$ ${step.command}`,
          last ? `${last.state === 'reproduced' ? 'reproduced' : last.state}  ${step.id}  ${last.bytes_identical ? 'bytes identical' : last.detail}` : 'never re-run',
        ].join('\n')}</pre>
      </details>
    </aside>
  )
}
