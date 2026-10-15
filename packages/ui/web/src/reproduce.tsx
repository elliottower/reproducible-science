import { useState } from 'react'
import { fmt, when } from './shared'
import type { Graph } from './types'

const STATE: Record<string, [string, string]> = {
  current: ['Reproduced', 'good'],
  stale: ['Changed', 'stale'],
  never_rerun: ['Never re-run', 'stale'],
}

/** Reproduce in the top bar opens the list of rebuild steps. Each step has its own Run, and the
 * head of the list runs every step, or only the changed ones. Nothing runs from the first click. */
export function ReproduceButton({ graph, busy, run }: {
  graph: Graph
  busy: string[] | null | false
  run: (only: string[] | null) => void
}) {
  const steps = graph.tabs?.reproduce.steps ?? []
  const changed = steps.filter((s) => s.state !== 'current').map((s) => s.id)
  const [open, setOpen] = useState(false)
  if (steps.length === 0) return null
  const running = busy !== false
  const isRunning = (id: string) => running && (busy === null || busy.includes(id))
  return (
    <>
      <button className="repro-main" onClick={() => setOpen(true)}>
        {running ? 'Reproducing…' : <><span className="play-icon">▶</span> Reproduce</>} <span className="caret">▾</span>
      </button>
      {open && (
        <div className="viewer-back" onClick={() => setOpen(false)}>
          <div className="confirm" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-head">
              <h3>Rebuild steps</h3>
              <button className="close" onClick={() => setOpen(false)}>×</button>
            </div>
            <p className="small muted">Each step runs a command from repro.yaml, the project's own script, and checks its output comes out the same. A step may take a while. Every run is added to the project's record of re-runs.</p>
            <div className="confirm-actions">
              {changed.length > 0 && (
                <button className="repro-main" disabled={running} onClick={() => run(changed)}>Run the {changed.length} changed</button>
              )}
              <button className={changed.length ? 'plain' : 'repro-main'} disabled={running} onClick={() => run(null)}>Run all {steps.length}</button>
            </div>
            <div className="step-list">
              {steps.map((s) => {
                const [label, tone] = STATE[s.state] ?? [s.state, 'none']
                return (
                  <div key={s.id} className="step-row">
                    <div className="step-main">
                      <div><span className="mono strong">{s.id}</span> <span className={`pill ${tone}`}>{isRunning(s.id) ? 'Running…' : label}</span></div>
                      <div className="mono small muted step-cmd">{s.command}</div>
                      <div className="small muted">{s.rerun_at ? `last re-run ${when(s.rerun_at)}` : 'never re-run'}</div>
                    </div>
                    <CopyButton text={s.command} />
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
              <CopyButton text="repro verify" />
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
