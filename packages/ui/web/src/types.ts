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
  built_at?: string
  checked_at?: string
  project_dir?: string
  project_name?: string
  tabs?: {
    prereg: { lines: string[] }
    results: {
      runs: {
        run_id: string; timestamp: string; note: string; outputs: string[]; sealed_before: boolean
        /** The commit holding the run's output bytes (the latest, when outputs differ); null when none does. */
        commit?: string | null
        /** Every output's recorded bytes are in some commit. */
        committed?: boolean
        remote_url?: string | null
        /** A W&B run named in the ledger event; never looked up. */
        wandb_url?: string | null
        /** Each output with its recorded hash, and whether the file on disk still has those bytes. */
        files?: { path: string; sha256: string; on_disk: boolean }[]
        /** `results annotate` links naming one of the outputs: linked, not checked. */
        links?: { kind: string; ref: string; url: string | null; note: string; by: string; status: string; timestamp: string; same_bytes: boolean }[]
      }[]
      seals: number
      bound: { run_id: string; timestamp: string; claim: string; location: string }[]
    }
    citations: {
      sources: {
        file: string; citation: string; url: string; local: string; sha256: string; pinned: number
        cited_in: { text: string; section: string; file: string; order: [number, number] }[]
        bib: Record<string, string>
        link: string
        doi_link: string
        statements: { id: string; statement: string; notes: string; quotes: { exact: string; section: string }[] }[]
      }[]
    }
    reproduce: {
      steps: {
        id: string; artifact: string; state: string; rerun_at: string | null; command: string; causes: { cause: string; artifact: string }[]
        inputs?: { artifact: string; path: string }[]
        output_path?: string
        /** This step in each recorded re-run, newest first. */
        history?: { ended_at: string; tool_version: string; state: string; bytes_identical: boolean | null; exit_code: number | null; duration_seconds: number | null; detail: string }[]
      }[]
      reruns: { started_at: string; ended_at: string; tool_version: string; counts: Record<string, number>; steps: number }[]
    }
  }
  status?: Record<'prereg' | 'results' | 'citations' | 'repro', StatusField>
  reproduce?: { runs: number; declared: number; last_at: string | null; last: Record<string, number>; last_steps: number }
  manifest_digest: string
  totals: {
    claims: number
    assertions: number
    artifacts: number
    failing: number
    reruns: number
    stale_steps: number
    run_backed?: number
    checks: number
    last_check: string | null
  }
  groups: { id: string; kind: 'files' | 'sections' }[]
  nodes: GNode[]
  edges: GEdge[]
}

export interface StatusField {
  text: string
  ok: boolean | null
  next?: string
  counts?: Record<string, number>
}
