export interface Assertion {
  kind: string
  artifact: string
  ok: boolean
  comparison: string
  reason: string
  detail: string
  extracted: string | null
  warnings: string[]
  stale: string | null
}

export interface HistoryPoint {
  t: string
  outcome: string
}

export interface ClaimRow {
  id: string
  where: string
  section: string
  text: string
  ok: boolean
  stale: string | null
  history: HistoryPoint[]
  assertions: Assertion[]
}

export interface RunInfo {
  run_id: string
  timestamp: string
  sha256: string
  note: string
  fresh: boolean
}

export interface GNode {
  id: string
  type: 'artifact' | 'section'
  group: string
  label?: string
  path?: string
  media_type?: string
  pinned?: string
  current?: string | null
  state?: 'pinned' | 'changed' | 'missing'
  run?: RunInfo | null
  regenerated_by?: string | null
  code?: string[]
  freshness?: 'stale' | 'current' | 'never_rerun' | 'no_producer' | null
  rerun_at?: string | null
  causes?: { cause: string; artifact: string }[]
  last_checked?: string | null
  ok: number
  fail: number
  stale: number
  claims: ClaimRow[]
}

export interface GEdge {
  source: string
  target: string
  kind: 'regenerates' | 'supports'
  count?: number
}

export interface Graph {
  project: string
  manifest_digest: string
  totals: {
    claims: number
    assertions: number
    artifacts: number
    failing: number
    reruns: number
    stale_steps: number
    checks: number
    last_check: string | null
  }
  groups: { id: string; kind: 'files' | 'sections' }[]
  nodes: GNode[]
  edges: GEdge[]
}
