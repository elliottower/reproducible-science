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
    return {
      key, text: parts.join(', '),
      tone: f.changed ? 'bad' : f.drafts || f.amendments ? 'warn' : 'good',
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
    if (f.changed) parts.push(`${plural(f.changed, 'file', 'files')} changed since sealed`)
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

/** How every prompt ends. A prompt asks the agent to look and to say what it found; it never
 * tells the agent to change anything, so the person reading the answer decides what happens. */
export const ASK_FIRST =
  'Investigate and tell me what you find: what changed, whether it looks intended, and what my options are. ' +
  'Then stop and ask me which to do. Do not edit, repin, reseal, re-run or commit anything until I choose.'

/** What to look at, and the options to lay out, for each kind of issue. */
const LOOK: Record<string, [string, string]> = {
  'prereg-changed': [
    'The freeze record in the .prereg/ folder beside each plan names the commit and the sha256 that were frozen. Compare that commit\'s copy of the plan with the file now, and say what changed and whether it reads as a deliberate change to the plan.',
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
  return [
    `In ${project ?? 'this project'}, ${row.tool} reports: ${row.title}.`,
    ...row.items.slice(0, 20).map((i) => `- ${i.label}`),
    ...(row.items.length > 20 ? [`- and ${row.items.length - 20} more`] : []),
    row.note,
    '',
    look,
    ...(options ? [`Options might include ${options}; say which fit what you found, and what else would.`] : []),
    '',
    ASK_FIRST,
  ].join('\n')
}
