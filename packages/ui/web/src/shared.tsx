import { useMemo, useState } from 'react'
import type { ClaimRow, GNode, Graph, HistoryPoint } from './types'

export const fmt = (n: number) => n.toLocaleString('en-US')
export const when = (ts: string) =>
  new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

const CAUSE: Record<string, string> = {
  input_changed: 'input changed',
  output_changed: 'output changed',
  command_changed: 'command changed',
}

/** Dagster-style freshness tag for a file: whether its rebuild step still matches its last re-run. */
export function Freshness({ node, long }: { node: GNode; long?: boolean }) {
  const f = node.freshness
  if (f === 'stale') {
    const causes = [...new Set((node.causes ?? []).map((c) => CAUSE[c.cause] ?? c.cause))]
    return (
      <span className="fresh stale" title={(node.causes ?? []).map((c) => `${CAUSE[c.cause] ?? c.cause}: ${c.artifact}`).join('\n')}>
        Stale{causes.length ? ` · ${long ? causes.join(', ') : causes[0]}` : ''}
      </span>
    )
  }
  if (f === 'current') return <span className="fresh current">Reproduced</span>
  if (f === 'never_rerun') return <span className="fresh never">Never re-run</span>
  return <span className="fresh pinned">Pinned</span>
}

export function Status({ ok, fail, problem }: { ok: number; fail: number; problem?: string }) {
  if (problem) return <div className="status bad">{problem}</div>
  if (fail > 0)
    return (
      <div className="status bad">
        <span>{fmt(fail)} failing</span>
        <span>{fmt(ok)} verified</span>
      </div>
    )
  if (ok === 0) return <div className="status none">no claims read this</div>
  return (
    <div className="status good">
      <span>Verified</span>
      <span>
        {fmt(ok)} claim{ok === 1 ? '' : 's'}
      </span>
    </div>
  )
}

/** One mark per recorded check of a claim, oldest to newest, as Dagster draws asset-check history. */
export function HistoryStrip({ points }: { points: HistoryPoint[] }) {
  if (!points.length) return <span className="muted small">no recorded checks</span>
  const shown = points.slice(-24)
  return (
    <span className="history" title={`${points.length} recorded check${points.length === 1 ? '' : 's'}`}>
      {shown.map((p, i) => (
        <span key={i} className={`tick ${p.outcome === 'verified' ? 'good' : p.outcome === 'unchecked' ? 'none' : 'bad'}`} title={`${when(p.t)} · ${p.outcome}`} />
      ))}
      <span className="muted small"> last {when(points[points.length - 1].t)}</span>
    </span>
  )
}

export function ClaimList({ claims, limit = 40 }: { claims: ClaimRow[]; limit?: number }) {
  const [all, setAll] = useState(false)
  const sorted = useMemo(() => [...claims].sort((a, b) => Number(a.ok) - Number(b.ok)), [claims])
  const shown = all ? sorted : sorted.slice(0, limit)
  return (
    <div>
      {shown.map((c) => (
        <div key={c.id} className={`claim ${c.ok ? '' : 'bad'}`}>
          <div className="claim-top">
            <span className={`dot ${c.ok ? 'good' : 'bad'}`} />
            <span className="mono small">{c.id}</span>
            <span className="where">{c.where}</span>
          </div>
          <div className="claim-text">{c.text}</div>
          {c.assertions.map((a, i) => (
            <div key={i} className="assertion mono">
              <span className={a.ok ? 'ok' : 'no'}>{a.ok ? '✓' : '✗'}</span> {a.kind} · {a.artifact}
              {a.detail ? <span className="muted"> · {a.detail}</span> : null}
              {a.stale === 'stale' ? <span className="stale-inline"> · stale</span> : null}
            </div>
          ))}
          <div className="claim-hist">
            <HistoryStrip points={c.history} />
          </div>
        </div>
      ))}
      {sorted.length > limit && !all && (
        <button className="more" onClick={() => setAll(true)}>
          Show all {sorted.length}
        </button>
      )}
    </div>
  )
}

export function Panel({ graph, id, onClose, onExpand }: { graph: Graph; id: string; onClose: () => void; onExpand?: (g: string) => void }) {
  const node = graph.nodes.find((n) => n.id === id)
  if (id.startsWith('group:')) {
    const gid = id.slice(6)
    const members = graph.nodes.filter((n) => n.group === gid)
    return (
      <aside className="panel">
        <button className="close" onClick={onClose}>×</button>
        <div className="kicker">GROUP</div>
        <h2>{gid}</h2>
        {onExpand && <button className="primary" onClick={() => onExpand(gid)}>Expand group</button>}
        {members.map((m) => (
          <div key={m.id} className="member">
            <span className={`dot ${m.fail ? 'bad' : 'good'}`} />
            <span className="mono small">{m.type === 'section' ? m.label : m.id}</span>
            {m.type === 'artifact' && <Freshness node={m} />}
            <span className="muted small right">{fmt(m.ok + m.fail)} claims</span>
          </div>
        ))}
      </aside>
    )
  }
  if (!node) return null
  return (
    <aside className="panel">
      <button className="close" onClick={onClose}>×</button>
      <div className="kicker">{node.type === 'section' ? 'PAPER SECTION' : 'FILE'}</div>
      <h2 className={node.type === 'artifact' ? 'mono' : ''}>{node.type === 'section' ? node.label : node.id}</h2>
      {node.type === 'artifact' && (
        <dl>
          <dt>Path</dt>
          <dd className="mono">{node.path}</dd>
          <dt>Pinned</dt>
          <dd className="mono">
            {node.pinned?.slice(0, 16)}… {node.state === 'pinned' ? '(matches disk)' : `(${node.state})`}
          </dd>
          <dt>Freshness</dt>
          <dd>
            <Freshness node={node} long />
            {node.rerun_at && <div className="muted small">last re-run {when(node.rerun_at)}</div>}
            {(node.causes ?? []).map((c, i) => (
              <div key={i} className="small mono">{CAUSE[c.cause] ?? c.cause}: {c.artifact}</div>
            ))}
            {node.freshness === 'no_producer' && <div className="muted small">no rebuild step declared; checked against its pin</div>}
          </dd>
          {node.last_checked && (
            <>
              <dt>Last check</dt>
              <dd>{when(node.last_checked)}</dd>
            </>
          )}
          {node.run && (
            <>
              <dt>Run</dt>
              <dd>
                <span className="mono">{node.run.run_id}</span> · {when(node.run.timestamp)}
                {node.run.fresh ? '' : ' · file changed since'}
                <div className="muted small">{node.run.note}</div>
              </dd>
            </>
          )}
          {node.regenerated_by && (
            <>
              <dt>Rebuilt by</dt>
              <dd className="mono small">{node.regenerated_by}</dd>
            </>
          )}
        </dl>
      )}
      <h3>
        {fmt(node.ok + node.fail)} claims {node.fail ? `· ${node.fail} failing` : '· all verified'}
      </h3>
      <ClaimList claims={node.claims} />
    </aside>
  )
}
