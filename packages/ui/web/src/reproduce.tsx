import { useEffect, useRef, useState } from 'react'
import { fmt, when } from './shared'
import type { Graph } from './types'

const STATE: Record<string, [string, string]> = {
  current: ['Reproduced', 'good'],
  stale: ['Changed', 'stale'],
  never_rerun: ['Never re-run', 'stale'],
}

/** A command to paste into any new terminal: into the project's folder first, then the command. */
export function terminalCommand(dir: string | undefined, command: string): string {
  const quoted = dir ? `'${dir.replace(/'/g, `'\\''`)}'` : ''
  return dir ? `cd ${quoted} && ${command}` : command
}

function reproduceCommand(dir: string | undefined, only: string[] | null): string {
  return terminalCommand(dir, ['repro reproduce', ...(only ?? []).map((id) => `--only ${id}`)].join(' '))
}

/** A re-run's states in words, leaving out the steps it did not run. */
const WORDS: Record<string, string> = { reproduced: 'reproduced', changed: 'changed', unchecked: 'could not be checked', failed: 'failed' }
export function outcome(counts: Record<string, number> | undefined): string {
  const said = Object.entries(counts ?? {}).filter(([k, v]) => k !== 'not_rerun' && v > 0).map(([k, v]) => `${v} ${WORDS[k] ?? k}`)
  return said.length ? said.join(', ') : 'nothing re-ran'
}

const secs = (n: number | null | undefined) => (n == null ? '' : n < 10 ? `${n.toFixed(2)} s` : `${n.toFixed(1)} s`)

/** What the page shows while a re-run streams in, and once it is done. */
export interface Run {
  only: string[] | null
  lines: string[]
  started: number
  done?: { ok: boolean; seconds?: number; counts?: Record<string, number>; error?: string }
}

/** Reproduce in the top bar opens the list of rebuild steps. Each step has its own Run, and the
 * head of the list runs the changed ones or every step. Nothing runs from the first click. While a
 * re-run goes, its output streams into the dialog. */
export function ReproduceButton({ graph, open, setOpen, live, run }: {
  graph: Graph
  open: boolean
  setOpen: (open: boolean) => void
  live: Run | null
  run: (only: string[] | null) => void
}) {
  const steps = graph.tabs?.reproduce.steps ?? []
  const changedSteps = steps.filter((s) => s.state !== 'current')
  const changed = changedSteps.map((s) => s.id)
  const ordered = [...changedSteps, ...steps.filter((s) => s.state === 'current')]
  const dir = graph.project_dir
  const running = live !== null && !live.done
  const isRunning = (id: string) => running && (live.only === null || live.only.includes(id))
  const [now, setNow] = useState(Date.now())
  const log = useRef<HTMLPreElement>(null)
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [running])
  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight })
  }, [live?.lines.length])
  if (steps.length === 0) return null
  const elapsed = live ? (live.done?.seconds ?? (now - live.started) / 1000) : 0
  return (
    <>
      <button className={`pill big pill-btn ${changed.length ? 'stale' : 'good'}`} onClick={() => setOpen(true)}
        title="The rebuild steps repro.yaml declares, and whether each re-ran since its inputs last changed">
        {running
          ? `◐ reproducing… ${Math.floor(elapsed)} s`
          : `◐ ${fmt(steps.length - changed.length)}/${fmt(steps.length)} reproduced`} <span className="caret">▾</span>
      </button>
      {open && (
        <div className="viewer-back" onClick={() => setOpen(false)}>
          <div className="confirm" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-head">
              <h3>Rebuild steps</h3>
              <button className="close" onClick={() => setOpen(false)}>×</button>
            </div>
            <p className="small muted">Each step runs a command from repro.yaml, the project's own script, and checks its output comes out the same. Every run is added to the project's record of re-runs.</p>
            <div className="confirm-actions">
              {changed.length > 0 && (
                <button className="repro-main" disabled={running} onClick={() => run(changed)}>Run {changed.length} changed</button>
              )}
              <button className={changed.length ? 'plain' : 'repro-main'} disabled={running} onClick={() => run(null)}>Run all {steps.length}</button>
              <CopyButton text={reproduceCommand(dir, changed.length ? changed : null)} />
            </div>
            {live && (
              <div className="run-log">
                <div className="run-log-head small">
                  {live.done
                    ? (live.done.ok
                        ? `${outcome(live.done.counts)} · ${secs(live.done.seconds)}`
                        : `Failed after ${secs(live.done.seconds ?? elapsed)}: ${live.done.error}`)
                    : `Running ${live.only ? live.only.join(', ') : 'every step'} · ${Math.floor(elapsed)} s`}
                </div>
                <pre ref={log} className="run-log-body">{live.lines.join('\n')}</pre>
              </div>
            )}
            <div className="step-list">
              {ordered.map((s) => {
                const [label, tone] = STATE[s.state] ?? [s.state, 'none']
                const last = s.history?.[0]
                return (
                  <div key={s.id} className="step-row">
                    <div className="step-main">
                      <div><span className="mono strong">{s.id}</span> <span className={`pill ${tone}`}>{isRunning(s.id) ? 'Running…' : label}</span></div>
                      <div className="mono small muted step-cmd">{s.command}</div>
                      <div className="small muted">
                        {s.rerun_at ? `last re-run ${when(s.rerun_at)}${last?.duration_seconds != null ? ` · ${secs(last.duration_seconds)}` : ''}` : 'never re-run'}
                      </div>
                    </div>
                    <CopyButton text={reproduceCommand(dir, [s.id])} />
                    <button className="plain" disabled={running} onClick={() => run([s.id])}>Run</button>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function CopyButton({ text, label = 'Copy command' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button className="plain" onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) })}>
      {done ? 'Copied' : label}
    </button>
  )
}

/** repro verify ▾ opens a dialog first: when the claims were last checked and with what result, and
 * what running it writes, so a stray click does not add a check to the history. */
export function VerifyButton({ graph, busy, disabled, run }: { graph: Graph; busy: boolean; disabled: boolean; run: () => void }) {
  const [open, setOpen] = useState(false)
  const t = graph.totals
  return (
    <>
      <button className="recheck" onClick={() => setOpen(true)} disabled={disabled}>
        {busy ? 'Verifying…' : '✓ repro verify'} <span className="caret">▾</span>
      </button>
      {open && (
        <div className="viewer-back" onClick={() => setOpen(false)}>
          <div className="confirm" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-head">
              <h3 className="mono">repro verify</h3>
              <button className="close" onClick={() => setOpen(false)}>×</button>
            </div>
            <p className="small">Checks all {fmt(t.claims)} claims ({fmt(t.assertions)} assertions over {fmt(t.artifacts)} files) against the files they read.</p>
            <table className="kv small">
              <tbody>
                <tr><td>Last verified</td><td>{t.last_check ? `${when(t.last_check)} · ${t.failing ? `${fmt(t.failing)} failing` : `${fmt(t.claims)} passed`}` : 'never'}</td></tr>
                <tr><td>Writes</td><td>one line to this project's local check history, kept inside .git and never committed. None of the project's files change.</td></tr>
              </tbody>
            </table>
            <div className="confirm-actions">
              <CopyButton text={terminalCommand(graph.project_dir, 'repro verify')} />
              <span className="spacer" />
              <button className="plain" onClick={() => setOpen(false)}>Cancel</button>
              <button className="repro-main" onClick={() => { run(); setOpen(false) }}>Run repro verify</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
