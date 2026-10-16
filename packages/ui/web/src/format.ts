/** What the page says in words, kept apart from React so it can be tested on its own: the shell
 * commands it copies, the five status lines, and the prompts it copies for each issue. */
import type { Issue, Status } from './types'

/** One word for a POSIX shell: single-quoted, with any single quote closed, escaped and reopened. */
export function shellQuote(s: string): string {
  return /^[A-Za-z0-9_./:=+-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`
}

/** A command to paste into any new terminal: into the project's folder first, then the command. */
export function terminalCommand(dir: string | undefined, command: string): string {
  return dir ? `cd ${shellQuote(dir)} && ${command}` : command
}

/** `repro reproduce`, for the given steps or for every one, run from the project's folder. */
export function reproduceCommand(dir: string | undefined, only: string[] | null): string {
  return terminalCommand(dir, ['repro reproduce', ...(only ?? []).map((id) => `--only ${shellQuote(id)}`)].join(' '))
}

export const fmt = (n: number) => n.toLocaleString('en-US')
const plural = (n: number, one: string, many: string) => `${fmt(n)} ${n === 1 ? one : many}`
/** "15 Oct", for the date of the last re-run. */
export const day = (ts: string) => new Date(ts).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

export type Tone = 'good' | 'warn' | 'bad' | 'none'
export type StatusKey = 'prereg' | 'results' | 'citations' | 'claims' | 'repro'
export interface Line { key: StatusKey; text: string; tone: Tone; next?: string }

/** Order of the lines on the Overview. */
export const STATUS_ORDER: StatusKey[] = ['prereg', 'results', 'citations', 'claims', 'repro']

/** One status line: what the record holds, its tone, and the command that would move it on. */
export function statusLine(key: StatusKey, s: Status | undefined): Line {
  const none = (text: string, next?: string): Line => ({ key, text, tone: 'none', next })
  if (key === 'prereg') {
    const f = s?.prereg
    if (!f || f.state === 'none') return none('none drafted', 'prereg new')
    if (f.state === 'unread') return { key, text: 'could not be read', tone: 'bad' }
    const parts = [`${fmt(f.frozen ?? 0)}/${fmt(f.plans ?? 0)} frozen`]
    if (f.changed) parts.push(`${fmt(f.changed)} changed since frozen`)
    if (f.amendments) parts.push(plural(f.amendments, 'amendment not frozen', 'amendments not frozen'))
    if (f.unknown) parts.push(`${fmt(f.unknown)} naming no commit held here`)
    return {
      key, text: parts.join(', '),
      tone: f.changed || f.unknown ? 'bad' : f.drafts || f.amendments ? 'warn' : 'good',
      next: !f.changed && (f.drafts || f.amendments) ? 'prereg freeze' : undefined,
    }
  }
  if (key === 'results') {
    const f = s?.results
    if (!f || f.state === 'none') return none('no ledger', 'results init')
    if (f.state === 'broken') return { key, text: `chain ${f.chain ?? 'unreadable'}`, tone: 'bad' }
    const runs = f.runs ?? 0
    const sealed = f.sealed ?? 0
    const parts = [runs ? `${fmt(sealed)}/${fmt(runs)} runs sealed` : 'no runs recorded']
    if (f.changed) parts.push(`${plural(f.changed, 'file', 'files')} changed after sealing`)
    return { key, text: parts.join(', '), tone: f.changed ? 'bad' : sealed < runs ? 'warn' : 'good' }
  }
  if (key === 'citations') {
    const f = s?.citations
    if (!f || f.state === 'none') return none('none pinned', 'citations pin')
    if (f.state === 'unverified') return none(`${plural(f.pinned ?? 0, 'quote', 'quotes')} pinned, not verified`)
    if (f.state === 'unread') return { key, text: 'could not be checked', tone: 'bad' }
    const parts = [`${fmt(f.found ?? 0)}/${fmt(f.quotes ?? 0)} quotes verified`]
    if (f.not_found) parts.push(`${fmt(f.not_found)} not found`)
    return { key, text: parts.join(', '), tone: f.ok ? 'good' : 'bad' }
  }
  if (key === 'claims') {
    const f = s?.claims
    if (!f || f.state === 'none') return none('no claims declared')
    return { key, text: `${fmt(f.verified ?? 0)}/${fmt(f.total ?? 0)} verified`, tone: f.ok ? 'good' : 'bad' }
  }
  const f = s?.repro
  if (!f || f.state === 'none') return none('no rebuild steps declared')
  const parts = [`${fmt(f.current ?? 0)}/${fmt(f.steps ?? 0)} reproduced`]
  if (f.changed) parts.push(`${fmt(f.changed)} changed${f.last_at ? ` since ${day(f.last_at)}` : ''}`)
  if (f.never) parts.push(`${fmt(f.never)} never re-run`)
  const behind = Boolean(f.changed || f.never)
  return { key, text: parts.join(', '), tone: behind ? 'warn' : 'good', next: behind ? 'repro reproduce' : undefined }
}

export const statusLines = (s: Status | undefined): Line[] => STATUS_ORDER.map((k) => statusLine(k, s))

/** A line as one string, as the Overview reads: `results: 72/72 runs sealed`. */
export const lineText = (l: Line) => `${l.key}: ${l.text}${l.next ? `  →  ${l.next}` : ''}`

/** The rule every prompt the page copies ends on. */
export const NEVER_ACT = 'Do not change any file or record — no edit, freeze, amend, log, seal, pin, re-run or commit — until I choose.'

/** How every prompt ends. A prompt asks the agent to look and to say what it found; it never
 * tells the agent to change anything, so the person reading the answer decides what happens. */
export const ASK_FIRST =
  'Investigate and tell me what you find: what changed, whether it looks intended, and what my options are. ' +
  `Then stop and ask me which to do. ${NEVER_ACT}`

/** What to look at, and the options to lay out, for each kind of issue. */
const LOOK: Record<string, [string, string]> = {
  'prereg-changed': [
    'The record in the .prereg/ folder beside each preregistration names the commit and the sha256 of the frozen text. Compare that commit\'s copy of the preregistration with the file now, and say what changed and whether it reads as a deliberate change to the preregistration.',
    'logging an amendment that covers the change, or restoring the frozen text',
  ],
  'prereg-pinned-changed': [
    'The Commit SHA line in each registration names the commit it was pinned at. Compare that commit\'s copy with the file now, and say what changed.',
    'recording the change as a deviation, or restoring the pinned text',
  ],
  'results-changed': [
    'The ledger in .results/ledger.jsonl records the sha256 each file had when it was sealed or written by a run. Find out what changed in each file since then, and whether a later commit, a script or another run explains it.',
    'recording a new run for the new bytes, or restoring the recorded bytes',
  ],
  'results-missing': [
    'The ledger in .results/ledger.jsonl records these paths with a sha256. Find out where each file went: renamed, moved or deleted, and in which commit.',
    'restoring the file, or retiring the path in the ledger',
  ],
  'citations-not-found': [
    'Each claims file pins a source by sha256 and quotes it. Compare each quotation with the text of the pinned source, and say whether the quotation, the pinned file or the way it is read is wrong.',
    'correcting the quotation, pinning another copy of the source, or dropping the quotation',
  ],
  'citations-pin': [
    'Each claims file pins its source file by sha256. Find out how the file on disk differs from the pinned one: a new version, a re-download, or another document.',
    'restoring the pinned file, or pinning the new one after checking the quotations against it',
  ],
}

/** The prompt Copy prompt puts on the clipboard for one row of the issues menu. */
export function issuePrompt(row: Issue, project: string | null): string {
  const [look, options] = LOOK[row.id] ?? [
    `\`${row.tool}\`'s own check reports this. Find out what it reports and why.`,
    '',
  ]
  const items = row.items.slice(0, 20).map((i) => i.label).join('; ')
  return [
    `In ${project ?? 'this project'}, ${row.tool} reports: ${row.title}.`,
    ...(items ? [`Items: ${items}${row.items.length > 20 ? `; and ${row.items.length - 20} more` : ''}.`] : []),
    row.note,
    look,
    ...(options ? [`Options might include ${options}; say which fit what you found, and what else would.`] : []),
    ASK_FIRST,
  ].join('\n\n')
}

// ---------------------------------------------------------------------------------- prompts

/** The Ask AI audit prompt: one line per paragraph, never hard-wrapped, so it pastes as written. */
export function auditPrompt(project: string | null, manuscript: string | null | undefined): string {
  const where = [
    `Project: ${project ?? 'this project'}.`,
    ...(manuscript ? [`Manuscript: ${manuscript}.`] : []),
    'Manifest: repro.yaml.',
  ].join(' ')
  return [
    'Audit this paper with Reproducible Science, an open-source toolkit that checks a paper against the records behind it: prereg (the analysis plan was frozen before the run), results (each reported number came from a recorded run over sealed inputs), citations (each quoted passage occurs in its pinned source) and repro (every claim the paper declares resolves against the file it names). Docs: https://reproducible.science/',
    where,
    'Setup: first check whether the toolkit is installed (repro --version). If it is not, stop and ask me to install it; do not install anything yourself. The command-line tools install with pip install reproducible-science. The Claude Code plugin, which adds the skills repro, results, citations and prereg and the /repro-check command, can only be installed by me, by typing /plugin marketplace add elliottower/reproducible-science and then /plugin install reproducible-science@reproducible-science; if it is missing, tell me those two commands and carry on with the command-line tools.',
    'Step 1, the toolkit\'s checks: run /repro-check if the plugin is installed, otherwise repro verify --format json, which checks every declared claim and runs the prereg, results and citations checks. Report what it found, including anything it could not check.',
    `Step 2, what the checks cannot see: read the manuscript and list every number, quotation and claim with no record behind it, meaning no declared claim, no pinned quote or no sealed input. A number counts as recorded only when a claim fetches it from a stated address in a file, not when the same digits appear somewhere in one.`,
    'Step 3, for each finding give the file and line, the record it needs and the command that would make it (results claim, citations pin, results seal or prereg new).',
    'Only read files and run checks. Do not install, bind, pin, seal, freeze, commit or edit anything. Group the findings by kind, then wait for me to choose what to do.',
    NEVER_ACT,
  ].join('\n\n')
}

/** The Ask AI prompt for every open issue at once, under the same rules as each row's prompt. */
export function fixPrompt(rows: Issue[], project: string | null): string {
  const kinds = rows.length === 1 ? '1 kind of problem' : `${rows.length} kinds of problem`
  return [
    `In ${project ?? 'this project'}, prereg, results and citations report ${kinds}. For each, look into it, explain what you found and lay out my options.`,
    ...rows.map((row, k) => {
      const [look, options] = LOOK[row.id] ?? [`\`${row.tool}\`'s own check reports this. Find out what it reports and why.`, '']
      const items = row.items.slice(0, 10).map((i) => i.label).join('; ')
      return [
        `${k + 1}. ${row.tool}: ${row.title}.`,
        items ? `Items: ${items}${row.items.length > 10 ? `; and ${row.items.length - 10} more` : ''}.` : '',
        row.note,
        look,
        options ? `Options might include ${options}.` : '',
      ].filter(Boolean).join(' ')
    }),
    'Investigate and tell me what you find for each: what changed, whether it looks intended, and what my options are. Then stop and ask me which to do.',
    NEVER_ACT,
  ].join('\n\n')
}

// ---------------------------------------------------------------------------------- share

export interface Remote { clone: string; host: string; owner: string; name: string; subdir: string }

/** What someone runs to open this page on their own machine. */
export function cloneInstructions(remote: Remote | null | undefined, projectDir: string | undefined): string {
  if (!remote) {
    return [
      ...(projectDir ? [`cd ${shellQuote(projectDir)}`] : []),
      'pip install "reproducible-science[ui]"',
      'repro ui',
    ].join('\n')
  }
  const folder = remote.subdir ? `${remote.name}/${remote.subdir}` : remote.name
  return [
    `git clone ${shellQuote(remote.clone)}`,
    `cd ${shellQuote(folder)}`,
    'pip install "reproducible-science[ui]"',
    'repro ui',
  ].join('\n')
}

/** The workflow that exports the page on every push to main. */
export const PAGES_WORKFLOW = `name: repro pages
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: github-pages
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "reproducible-science[ui]"
      - run: repro ui --export _site
      - uses: actions/upload-pages-artifact@v3
        with:
          path: _site
      - uses: actions/deploy-pages@v4`

/** owner/repo on GitHub, or placeholders where the remote is not on GitHub. */
export function githubRepo(remote: Remote | null | undefined): { owner: string; name: string; known: boolean } {
  return remote && remote.host === 'github.com'
    ? { owner: remote.owner, name: remote.name, known: true }
    : { owner: '<owner>', name: '<repo>', known: false }
}

export const pagesCommand = (remote: Remote | null | undefined) => {
  const r = githubRepo(remote)
  return `gh api -X POST repos/${r.owner}/${r.name}/pages -f build_type=workflow`
}

export const pagesAddress = (remote: Remote | null | undefined) => {
  const r = githubRepo(remote)
  return `${r.owner}.github.io/${r.name}`
}

/** The three steps, as Copy steps puts them on the clipboard. */
export function pagesSteps(remote: Remote | null | undefined): string {
  return [
    'A Pages site is public even when the repository is private.',
    '1. Add this workflow as .github/workflows/repro-pages.yml. It exports the page on every push to main.',
    PAGES_WORKFLOW,
    `2. Turn on Pages with GitHub Actions as the source, in Settings → Pages, or with: ${pagesCommand(remote)}`,
    `3. Commit the workflow and push. The page appears at ${pagesAddress(remote)}.`,
  ].join('\n\n')
}

/** The Copy prompt of the Pages card: the agent checks and explains; it publishes nothing. */
export function pagesPrompt(remote: Remote | null | undefined, project: string | null): string {
  const r = githubRepo(remote)
  return [
    `I am thinking of publishing the Reproducible Science page of ${project ?? 'this project'} on GitHub Pages${r.known ? `, from ${r.owner}/${r.name}` : ''}. A Pages site is public even when the repository is private.`,
    'Check whether .github/workflows/repro-pages.yml exists, whether Pages is already turned on for the repository, and whether the repository is public or private. Then tell me what each of the steps below would change.',
    pagesSteps(remote),
    NEVER_ACT,
  ].join('\n\n')
}

// ---------------------------------------------------------------------------------- export

/** What a button that needs the local server says in the one-file export. */
export function staticMessage(what: 'verify' | 'step' | 'all' | 'file', step?: string): string {
  if (what === 'verify') return "This static export can't run repro verify. Run it on the command line: repro verify"
  if (what === 'step') return `This static export can't re-run steps. Run it on the command line: repro reproduce --only ${shellQuote(step ?? '')}`
  if (what === 'all') return "This static export can't re-run steps. Run it on the command line: repro reproduce"
  return "This static export doesn't include file contents. Open the live page on the command line: repro ui"
}

// ---------------------------------------------------------------------------------- reproduce

export type StepState = 'run' | 'changed' | 'err' | 'int' | 'ok' | 'none'
export interface StepRow {
  step: string
  /** ISO time of the last re-run, or 'now' while running, or '' when never. */
  when: string
  state: StepState
  /** Words after the result: "bytes identical", "1 file", "exit 1". */
  detail: string
  dur: number | null
  cmd: string
}

/** Order of results when sorting by Result. */
export const STATE_ORDER: Record<StepState, number> = { run: 0, changed: 1, err: 2, int: 3, ok: 4, none: 5 }
export type SortKey = 'step' | 'when' | 'state' | 'dur' | 'cmd'

/** Rows sorted by `key`; `dir` is 1 ascending, -1 descending. A running step is the newest; a step
 * with no duration sorts after every timed one. Ties keep the step's name order. */
export function sortRows(rows: StepRow[], key: SortKey, dir: 1 | -1): StepRow[] {
  const val = (r: StepRow): string | number =>
    key === 'state' ? STATE_ORDER[r.state]
      : key === 'when' ? (r.when === 'now' ? '9999' : r.when || '')
      : key === 'dur' ? (r.dur ?? 1e12)
      : r[key]
  return [...rows].sort((a, b) => {
    const x = val(a)
    const y = val(b)
    return ((x < y ? -1 : x > y ? 1 : 0) * dir) || a.step.localeCompare(b.step)
  })
}

/** "4m 05s", for a running step's clock. */
export const clock = (seconds: number) => `${Math.floor(seconds / 60)}m ${String(Math.floor(seconds % 60)).padStart(2, '0')}s`
/** A duration as the table shows it. */
export const duration = (s: number | null | undefined) => {
  if (s == null) return ''
  if (s < 1) return `${Math.round(s * 1000)} ms`
  if (s < 60) return `${s.toFixed(2)} s`
  const whole = Math.round(s)
  return `${Math.floor(whole / 60)}m ${whole % 60}s`
}

/** The lines of a `repro reproduce` log that belong to one step: its result line and the lines
 * indented under it. The whole log where the run was of that step alone. */
export function stepLog(log: string, step: string, only: string[] | null): string {
  if (only && only.length === 1 && only[0] === step) return log
  const out: string[] = []
  let mine = false
  for (const line of log.split('\n')) {
    const m = /^ {2}(reproduced|changed|unchecked|failed|not re-run)\s+(\S+)/.exec(line)
    if (m) mine = m[2] === step
    else if (!/^ {13}/.test(line)) mine = false
    if (mine) out.push(line)
  }
  return out.join('\n')
}

/** What Copy clone instructions says it copied. */
export const cloneToast = (remote: Remote | null | undefined) =>
  remote ? 'Copied: git clone, pip install, repro ui' : 'Copied: pip install, repro ui'

/** The words for what changed since a step's last re-run, from the causes `repro stale` gives:
 * the files whose bytes changed, and whether the command did. */
export function changedSaid(causes: { cause: string; artifact: string }[]): string {
  const files = new Set(causes.filter((c) => c.cause !== 'command_changed').map((c) => c.artifact)).size
  const command = causes.some((c) => c.cause === 'command_changed')
  return [files ? `${files} file${files === 1 ? '' : 's'}` : '', command ? 'command' : ''].filter(Boolean).join(' and ')
}

/** The Pre-submit check's findings, as a prompt for an agent to lay out what each one needs. */
export interface Presubmit {
  checked_at: string
  numbers_read: boolean
  unbound_count: number
  unbound: { path: string; line: number | null; text: string; context: string }[]
  unpinned: string[]
  unsealed: string[]
}
export function presubmitPrompt(p: Presubmit, project: string | null): string {
  const numbers = p.unbound.slice(0, 40).map((n) => `${n.path}:${n.line ?? '?'} "${n.text}" in "${n.context.replace(/\s+/g, ' ').trim()}"`).join('; ')
  return [
    `In ${project ?? 'this project'}, a Pre-submit check found ${p.unbound_count} number${p.unbound_count === 1 ? '' : 's'} the manuscript prints that no claim accounts for, ${p.unpinned.length} source${p.unpinned.length === 1 ? '' : 's'} whose quotations are not pinned to a file, and ${p.unsealed.length} run${p.unsealed.length === 1 ? '' : 's'} with nothing sealed before ${p.unsealed.length === 1 ? 'it' : 'them'}.`,
    ...(numbers ? [`Numbers: ${numbers}${p.unbound_count > 40 ? `; and ${p.unbound_count - 40} more` : ''}.`] : []),
    ...(p.unpinned.length ? [`Sources not pinned: ${p.unpinned.join(', ')}.`] : []),
    ...(p.unsealed.length ? [`Runs with nothing sealed before them: ${p.unsealed.join(', ')}.`] : []),
    'For each finding, say what record it needs: a declared claim for a number, a pinned source for a quotation, or for a run, whether its inputs can still be sealed for a new run. Note any number that needs no record, such as a section number, and why. Then stop and ask me which to do.',
    NEVER_ACT,
  ].join('\n\n')
}
