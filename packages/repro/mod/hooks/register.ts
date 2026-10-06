import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

/** What `prereg freeze` once wrote into a plan. Its presence makes a plan frozen in place. */
const FROZEN = /^\*\*Plan sha256:\*\*[ \t]*`[0-9a-f]{64}`/m

/**
 * Where `prereg freeze` records a file frozen whole: `.prereg/<name>.json` beside it. A plan and
 * each of its amendments has one, and a file with one is never written to again.
 */
const recordOf = (path: string) => `${parent(path)}/.prereg/${path.replace(/^.*\//, '')}.json`

const PLAN = 'PREREG.md'
const LEDGER = '.results/ledger.jsonl'
const MANIFEST = 'repro.yaml'

/**
 * What a row reads while its tool has a next step still to take, and the command that takes it.
 * A row matching none of these carries no hint.
 */
const HINTS: [state: RegExp, next: string][] = [
  [/prereg: none drafted$/, 'prereg new'],
  [/prereg: 0\/\d+ frozen$/, 'prereg freeze'],
  [/^results: no ledger$/, 'results init'],
  [/^results: 0 runs, 0 claims bound$/, 'results seal'],
  [/^citations: none pinned$/, 'citations pin'],
  [/^repro: no manifest$/, 'repro manifest init'],
  [/^repro: no claims declared$/, 'add claims to repro.yaml'],
]
/** The rows of a project with nothing set up, which `repro init` starts in one command. */
const NOTHING = [/prereg: none drafted$/, /^results: no ledger$/, /^citations: none pinned$/, /^repro: no manifest$/]
const MANUSCRIPT = /\.(tex|rmd|qmd|typ)$/i

/** Programs that run an analysis, matched on a command's first three words. */
const RUNNERS = new Set([
  'python', 'python3', 'uv', 'Rscript', 'julia', 'make', 'snakemake', 'nextflow', 'papermill',
  'jupyter', 'quarto', 'modal', 'sbatch', 'srun',
])

const GATES = `# Research records (reproducible-science)

This project keeps machine-checkable records, and three steps are not taken without one:

1. Before a run whose output a paper will report: \`results seal\` the inputs, then \`results run\`. With no ledger in the repository, \`results init\` comes first.
2. Before a number goes into a manuscript: \`results claim\` binds the sentence to the run that produced it.
3. Before a confirmatory analysis runs: \`prereg freeze\` the plan. A frozen plan or amendment is never edited; a note is recorded with \`prereg log\` and a change to the plan with \`prereg amend\`.

A quotation is pinned with \`citations pin\` before the sentence quoting it is written.
A gate is skipped only with the user's approval or a reason written into the notebook or the commit message, and the user is told in the same turn.`

const parent = (path: string) => path.replace(/\/[^/]*$/, '')
const dirOf = (path: string) => (path.includes('/') ? parent(path) : '.')

/** The nearest `name` at or above `dir`, or undefined. Stops at the filesystem root. */
async function above($: EngineInterface, dir: string, name: string) {
  for (let at = dir; ; at = parent(at)) {
    if (await $.fs.exists(`${at}/${name}`)) {
      return `${at}/${name}`
    }
    if (at === '' || at === '.' || !at.includes('/')) {
      return undefined
    }
  }
}

async function absolute($: EngineInterface, path: string) {
  const cwd = await $.session.cwd()
  if (path.startsWith('~/')) {
    return `${/^\/(?:Users|home)\/[^/]+/.exec(cwd)?.[0] ?? ''}${path.slice(1)}`
  }

  return path.startsWith('/') ? path : `${cwd}/${path}`
}

/** What marks a directory as a research project: a ledger, pinned quotations, a plan or a manuscript folder. */
const MARKERS = ['.results', 'claims', PLAN, 'paper']

/** The nearest research project at or above `dir`, or undefined. */
async function projectOf($: EngineInterface, dir: string) {
  for (let at = dir; at.includes('/') && at !== ''; at = parent(at)) {
    for (const name of MARKERS) {
      if (await $.fs.exists(`${at}/${name}`)) {
        return at
      }
    }
  }

  return undefined
}

/** The directory a shell command works in when it opens with `cd <dir>`, or undefined. */
const cdTarget = (command: string) => /(?:^|[;&]\s*)cd\s+["']?([^\s"';&]+)/.exec(command)?.[1]

/** A command that saves a PDF from a URL: `[url, path]`, or undefined. curl and wget only. */
function download(command: string): [string, string] | undefined {
  if (!/\b(curl|wget)\b/.test(command)) {
    return undefined
  }
  const url = /https?:\/\/[^\s"'<>|;&)]+/.exec(command)
  const saved = /(?:-o|-O|--output|--output-document|>)\s*["']?([^\s"'|;&]+\.pdf)\b/i.exec(command)

  return url && saved ? [url[0], saved[1] as string] : undefined
}

/** Whether a command runs an analysis. An inline script (`python3 - <<EOF`, `python -c`) is not one. */
const runsAnAnalysis = (command: string) =>
  !/\s-(c\s|\s*<<)/.test(command) &&
  command.trim().split(/\s+/).slice(0, 3).some(word => RUNNERS.has(word.replace(/^.*\//, '')))

/**
 * The last full quotation check of each project, as `found/pinned`. Checking thousands of
 * quotations takes minutes, so the status line never runs it: `/repro-verify` does, and the
 * result is kept here, in the session's state, until the next one.
 */
const quotations = atom({ plugin: 'repro', key: 'quotations' } as const, {} as Record<string, string>)

/**
 * How many quotations that check reported as `not found`, by project. Kept apart from the
 * fraction because pinned less found also counts the quotations the check could not read.
 */
const quotationsNotFound = atom(
  { plugin: 'repro', key: 'quotationsNotFound' } as const,
  {} as Record<string, number>,
)

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/**
 * A command's output, or undefined when it did not finish in time or could not start.
 *
 * `$.process.run` rejects on a timeout, and a rejection here used to end the whole turn's hook:
 * one slow `prereg check` on a busy machine left no status line at all. A check that did not
 * finish now marks its own field and leaves the others standing.
 */
async function output($: EngineInterface, argv: string[], cwd: string, timeoutMs: number) {
  try {
    return (await $.process.run(argv, { cwd, timeoutMs })).stdout
  } catch {
    return undefined
  }
}

/** The outcomes `repro verify` counts, the most serious first, which is the order the row gives them in. */
const OUTCOMES = ['mismatch', 'not_found', 'error', 'unchecked', 'not_offered', 'verified']

/** The kinds of evidence `repro verify` prints beside an assertion. Only `quote` is not a number. */
const KINDS = new Set(['quote', 'metric', 'table', 'value', 'correspondence'])

/**
 * The `repro` field and its warnings, from what `repro verify` printed:
 *
 *       MISS  effect-size  correspondence effect-delta: manuscript 0.055, run 0.0453
 *
 *       1 mismatch, 2 verified
 *       policy publication: FAILED  (1 errors, 0 warnings)
 *
 * The counts are the tool's own summary line, under its own words. A pinned file that changed
 * is counted too: the assertions read from it still say `verified`, of a file that is not the
 * declared one, and `3/3 verified` would be the row saying so.
 */
function assertions(printed: string | undefined) {
  if (printed === undefined) {
    return { field: 'repro: not read (timed out)', wrong: [] }
  }
  // Without the policy line nothing was verified: the manifest did not load.
  if (!/^\s+policy \S+: (passed|FAILED)/m.test(printed)) {
    return { field: 'repro: manifest unreadable', wrong: [] }
  }
  const summary = /^\s+(\d+ \w+(?:, \d+ \w+)*)$/m.exec(printed)?.[1] ?? ''
  const counts = new Map([...summary.matchAll(/(\d+) (\w+)/g)].map(([, n, word]) => [word as string, Number(n)]))
  const total = [...counts.values()].reduce((a, b) => a + b, 0)
  const said = (n: number) => n.toLocaleString('en-US')
  const brokenPins = (printed.match(/^\s+BROKEN PIN\s/gm) ?? []).length
  const parts = [
    ...(brokenPins ? [`${said(brokenPins)} broken ${brokenPins === 1 ? 'pin' : 'pins'}`] : []),
    ...OUTCOMES.filter(word => counts.has(word)).map(word => `${said(counts.get(word) ?? 0)} ${word.replace(/_/g, ' ')}`),
  ]
  const verified = counts.get('verified') ?? 0
  // The row counts checks, one per assertion. Claims are counted on the results row, where
  // `results claim` makes them. Where every assertion is printed the row is a fraction even
  // when some failed; otherwise it is a fraction only when all verified.
  const lines = [...printed.matchAll(/^\s+(ok|MISS|GONE|--|ERR|none)\s+(\S+)\s/gm)]
  const pins = brokenPins ? `, ${said(brokenPins)} broken ${brokenPins === 1 ? 'pin' : 'pins'}` : ''

  const wrong: string[] = []
  const mismatched = counts.get('mismatch') ?? 0
  if (mismatched) {
    // The kind is the word after the claim's id. An id with a space in it moves that word, and
    // a line cut short hides one, so the kinds are believed only when every one is a known kind.
    const kinds = [...printed.matchAll(/^\s+MISS\s+\S+\s+(\S+)/gm)].map(match => match[1] as string)
    const quotes = kinds.filter(kind => kind === 'quote').length
    if (kinds.length !== mismatched || !kinds.every(kind => KINDS.has(kind))) {
      wrong.push(`${plural(mismatched, 'claim')} mismatched`)
    } else {
      if (mismatched > quotes) {
        wrong.push(`${plural(mismatched - quotes, 'number')} mismatched`)
      }
      if (quotes) {
        wrong.push(`${plural(quotes, 'quotation')} mismatched`)
      }
    }
  }

  return {
    field:
      total === 0
        ? 'repro: no claims declared'
        : lines.length === total
          ? `repro: ${said(verified)}/${said(total)} checks verified${pins}`
          : verified === total && !brokenPins
            ? `repro: ${said(verified)}/${said(total)} checks verified`
            : `repro: ${parts.join(', ')}`,
    wrong,
  }
}

/**
 * Every `claims` folder in the project, relative to its root. A paper keeps its pinned quotations
 * beside the manuscript as often as at the top (`paper/prior_art/claims`), and looking only at
 * the top reported 63 pinned quotations as none.
 */
async function claimsFolders($: EngineInterface, root: string) {
  const found = await output(
    $,
    ['find', '.', '-maxdepth', '4', '-type', 'd', '-name', 'claims', '-not', '-path', '*/node_modules/*', '-not', '-path', '*/.git/*'],
    root,
    20_000,
  )

  return (found ?? '')
    .split('\n')
    .map(line => line.replace(/^\.\//, '').trim())
    .filter(line => line.length > 0)
    .sort()
}

/**
 * Folders below the project that hold a `PREREG.md` of their own. `prereg check` reads the plan
 * nearest the folder it runs in, so a study kept in a subfolder was never listed: a repository
 * with a second frozen plan under `artifact_survey/` read `1/1 frozen`.
 */
async function planFolders($: EngineInterface, root: string) {
  const found = await output(
    $,
    ['find', '.', '-mindepth', '2', '-maxdepth', '4', '-type', 'f', '-name', 'PREREG.md', '-not', '-path', '*/node_modules/*', '-not', '-path', '*/.git/*'],
    root,
    20_000,
  )

  return (found ?? '')
    .split('\n')
    .map(line => line.replace(/^\.\//, '').trim())
    .filter(line => line.endsWith('/PREREG.md'))
    .map(line => line.slice(0, -'/PREREG.md'.length))
    .sort()
}

/**
 * What the last `status` found wrong, each in a few words. Drawn on the engine's pinned line
 * under the prompt, which is one row and spends about 28 columns on this plugin's name, so a
 * warning names the problem and `/repro-status` says what to do. The line is kept for these
 * because of its warning mark: a line that is there every turn stops being read as a warning.
 */
let warnings: string[] = []

/**
 * One line, one field per tool, in a fixed order so each is found in the same place every turn:
 *
 *     study · prereg: 1/1 frozen · results: 2/3 runs sealed, 4 claims bound · citations: 120/120 quotes found · repro: 34/34 checks verified
 *
 * The `repro` field is there only in a project with a manifest. Fractions only where there is a real total. The project's name stays, because the project
 * followed is the one whose files the session touches, which need not be where it started.
 *
 * `withFiles` also hashes every sealed file, which is the check that finds a changed input and
 * the one that costs: it runs for `/repro-status`, never at the end of every turn.
 */
async function status($: EngineInterface, root: string, withFiles: boolean) {
  const fields = [root.replace(/^.*\//, '')]
  const wrong: string[] = []

  // `prereg check` reads every plan at, above and below the directory it runs in.
  const plans = await output($, ['prereg', 'check'], root, 60_000)
  // One line per plan, whichever folder reported it: a check run in a subfolder also lists the
  // plan above it.
  const listed = new Set((plans ?? '').split('\n'))
  if (plans !== undefined) {
    for (const folder of await planFolders($, root)) {
      const below = await output($, ['prereg', 'check'], `${root}/${folder}`, 60_000)
      for (const line of (below ?? '').split('\n')) {
        listed.add(line)
      }
    }
  }
  const counts = new Map<string, number>()
  for (const line of listed) {
    // A plan frozen with `prereg freeze` is listed by its absolute path. A registration frozen by a
    // commit line in the document is listed by its path in the repository, under its own words:
    // text added after the frozen text leaves the plan intact, and a commit that is pending or not
    // in the repository could not be checked, which is not a change.
    const pinned = /^(unchanged|appended|CHANGED|pending|unknown commit)\s{2,}[^/\s]/.exec(line)?.[1]
    const label =
      /^([A-Za-z][A-Za-z ]*?)\s{2,}\//.exec(line)?.[1]?.toLowerCase() ??
      (pinned && { unchanged: 'unchanged', appended: 'unchanged', CHANGED: 'changed' }[pinned]) ??
      (pinned ? 'not frozen' : undefined)
    // `log  <path>  4 entries, chain intact` reports the log kept beside a plan. It is not a
    // plan, and counted as one it read as a plan that was neither frozen nor a draft: changed.
    if (label && label !== 'log') {
      counts.set(label, (counts.get(label) ?? 0) + 1)
    }
  }
  const total = [...counts.values()].reduce((a, b) => a + b, 0)
  const frozen = counts.get('unchanged') ?? 0
  const broken = total - frozen - (counts.get('not frozen') ?? 0)
  fields.push(
    plans === undefined
      ? 'prereg: not read (timed out)'
      : total === 0
        ? 'prereg: none drafted'
        : broken
          ? `prereg: ${broken} changed`
          : `prereg: ${frozen}/${total} frozen`,
  )
  if (broken) {
    wrong.push(`${plural(broken, 'plan')} edited after freeze`)
  }

  let runs = 0
  if (await $.fs.exists(`${root}/${LEDGER}`)) {
    const verified = await output(
      $,
      ['results', 'verify', ...(withFiles ? ['--files'] : [])],
      root,
      withFiles ? 300_000 : 60_000,
    )
    const head = verified?.split('\n')[0] ?? ''
    if (verified === undefined) {
      fields.push('results: not read (timed out)')
    } else if (/chain intact: \d+ events/.test(head)) {
      const ledger = await $.fs.read(`${root}/${LEDGER}`)
      // A run counts as sealed when inputs were sealed before it was recorded. A run named as a
      // test (`smoke_…`, `prefreeze_…`, `test_…`, `dryrun_…`) is left out of the row: it is
      // recorded before a plan is frozen, and nothing may be claimed from it.
      const events = ledger.split('\n').flatMap(line => {
        try {
          return line.trim() ? [JSON.parse(line) as { event?: string; run_id?: string }] : []
        } catch {
          return []
        }
      })
      const isTest = (id: string | undefined) => /^(smoke|prefreeze|test|dryrun)[_-]/.test(id ?? '')
      const claims = events.filter(event => event.event === 'claim')
      let hasSeal = false
      let sealed = 0
      for (const event of events) {
        if (event.event === 'seal') {
          hasSeal = true
        } else if (event.event === 'run' && !isTest(event.run_id)) {
          runs += 1
          sealed += hasSeal ? 1 : 0
        }
      }
      const changed = (verified.match(/^\s+(CHANGED|MISSING)\s/gm) ?? []).length
      const onTests = claims.filter(event => isTest(event.run_id)).length
      fields.push(
        `results: ${changed ? `${changed} changed, ` : ''}` +
          `${runs ? `${sealed}/${runs} runs sealed` : '0 runs'}, ${plural(claims.length, 'claim')} bound`,
      )
      if (changed) {
        wrong.push(`${plural(changed, 'sealed file')} changed`)
      }
      if (onTests) {
        wrong.push(`${plural(onTests, 'claim')} on test runs`)
      }
      if (/^TIMESTAMP CONTRADICTS/m.test(verified)) {
        wrong.push('ledger rewritten after timestamp')
      }
      if (runs > 0 && !hasSeal) {
        wrong.push(`${plural(runs, 'run')}, nothing sealed`)
      }
    } else {
      // `CHAIN TRUNCATED — events are missing from the end`: the word after CHAIN.
      const fault = /^(?:CHAIN|NO)\s+(\w+)/.exec(head)?.[1]?.toLowerCase() ?? 'unreadable'
      fields.push(`results: ${fault}`)
      wrong.push(`ledger ${fault}`)
    }
  } else {
    fields.push('results: no ledger')
  }
  if (runs > 0 && total > 0 && frozen === 0 && !broken) {
    wrong.push(`${plural(runs, 'run')}, no plan frozen`)
  }

  const folders = await claimsFolders($, root)
  if (folders.length > 0) {
    const last = (await read($, quotations))[root]
    if (last) {
      fields.push(`citations: ${last}`)
      const notFound = (await read($, quotationsNotFound))[root] ?? 0
      if (notFound) {
        wrong.push(`${plural(notFound, 'quotation')} not found`)
      }
    } else {
      // Counting what is pinned is one grep; checking it is minutes, and `/repro-verify` does that.
      const counted = await output(
        $,
        ['grep', '-rhcE', '^[[:space:]]*-?[[:space:]]*exact:', ...folders],
        root,
        20_000,
      )
      const pinned = (counted ?? '').split('\n').reduce((sum, n) => sum + (Number(n) || 0), 0)
      fields.push(`citations: ${pinned.toLocaleString('en-US')} pinned, not verified`)
    }
  } else {
    // Said, so the row always holds the same three fields and a missing one is not read as fine.
    fields.push('citations: none pinned')
  }

  // `repro verify` reads the `repro.yaml` at or above the directory it runs in and no other, so
  // that is the only manifest looked for. It takes under a second on 34 assertions, and runs here.
  // With no manifest the field says so, as the others do for a missing ledger or plan: a row
  // left out reads the same as nothing to check.
  if (await above($, root, MANIFEST)) {
    const checked = assertions(await output($, ['repro', 'verify'], root, 60_000))
    fields.push(checked.field)
    wrong.push(...checked.wrong)
  } else {
    fields.push('repro: no manifest')
  }

  warnings = wrong

  return fields.join(' · ')
}

/** The pane that lists the research projects, one button each, to pick one from. */
const PICKER = 'repro-projects'

/** Each project's button is addressed by this prefix and its folder name. */
const ROW = 'project:'

// In a pane the arrows walk the buttons only while the whole tree fits: once there are rows to
// scroll, an arrow scrolls the pane and the focus ring stays where it was. So the picker never
// draws more rows than fit. It draws a window onto the list and slides the window as the ring
// reaches either edge of it.

// Both live in the session's state, which the pane reads while it draws: a write then redraws
// the pane by itself. Kept in module variables, a slide changed the number and drew nothing.

/** How many projects the window shows. Corrected from the pane's real height on a first scroll. */
const windowRows = atom({ plugin: 'repro', key: 'windowRows' } as const, 8)

/** The index in `found` of the window's first row. */
const top = atom({ plugin: 'repro', key: 'top' } as const, 0)

const lastTop = (rows: number) => Math.max(0, found.length - rows)

/** The line of the pane the focus ring is on, from 0, to tell a wrap from an ordinary move. */
let lastLine = 0

/** The research projects last found beside the session's folder, by folder name. */
let found: string[] = []

/**
 * The research projects in the folder that holds the session's own: each folder there with a
 * ledger, pinned quotations or a plan at its top level, the ones with a ledger first.
 */
async function discover($: EngineInterface) {
  const home = parent(await $.session.cwd())
  const withLedger: string[] = []
  const others: string[] = []
  const papersOnly: string[] = []
  for (const entry of await $.fs.list(home)) {
    if (entry.kind !== 'dir' || entry.name.startsWith('.')) {
      continue
    }
    if (await $.fs.exists(`${home}/${entry.name}/${LEDGER}`)) {
      withLedger.push(entry.name)
    } else if (
      (await $.fs.exists(`${home}/${entry.name}/claims`)) ||
      (await $.fs.exists(`${home}/${entry.name}/${PLAN}`))
    ) {
      others.push(entry.name)
    } else if (await $.fs.exists(`${home}/${entry.name}/paper`)) {
      papersOnly.push(entry.name)
    }
  }
  found = [...withLedger.sort(), ...others.sort(), ...papersOnly.sort()]

  return found
}

/** Paths and projects already told once this session, so a note is not repeated. */
const told = new Set<string>()

/**
 * The research project this session last worked in, wherever the session was started.
 *
 * A session opened in one folder edits files in another, so the project is read off the paths
 * the tools touch: the nearest directory above a touched file that holds a ledger, pinned
 * quotations, a plan or a manuscript folder.
 */
let project: string | undefined

/** Set when the person named the project themselves; the tools' paths then stop moving it. */
let isPinned = false

// The session keeps both, so a reload of this module does not forget which project is open.
const savedProject = atom({ plugin: 'repro', key: 'project' } as const, null)
const savedPin = atom({ plugin: 'repro', key: 'isPinned' } as const, false)
/** Whether the person hid the readout above the prompt with `/repro-hide`. Warnings still show. */
const hidden = atom({ plugin: 'repro', key: 'isHidden' } as const, false)

async function save($: EngineInterface) {
  await update($, savedProject, () => project ?? null)
  await update($, savedPin, () => isPinned)
}

/** What the checks last said, shown on the status line and given to the model with the gates. */
let lastStatus = ''

/**
 * The same line, drawn in the band above the prompt. Kept in the session's state
 * so a change redraws it: a `$.ui.status` line carried this plugin's name and a warning mark ahead
 * of the text, and in a narrow terminal that left room for the project name and little else.
 */
const shownStatus = atom({ plugin: 'repro', key: 'statusLine' } as const, '')

async function show($: EngineInterface) {
  // The pinned line under the prompt carries a warning mark and this plugin's name, so it holds
  // only what is wrong, and nothing at all when nothing is.
  $.ui.status(warnings.length > 0 ? warnings.join(' · ') : undefined)
  await update($, shownStatus, () => lastStatus)
}

/** Makes the project above `path` the active one, when there is one. */
async function track($: EngineInterface, path: string) {
  if (isPinned) {
    return
  }
  const before = project
  project = (await projectOf($, await absolute($, path))) ?? project
  if (project !== before) {
    await save($)
  }
}

/**
 * Names the working project: a path, part of the name of a folder beside the one the session
 * started in, or its number in the list. `auto` hands it back to the paths the tools touch.
 * Answers what it did, for the transcript.
 */
async function choose($: EngineInterface, wanted: string) {
  if (wanted === 'auto') {
    isPinned = false
    await save($)

    return 'Following the files this session touches.'
  }
  const cwd = await $.session.cwd()
  let name = wanted
  if (!/^[~/.]/.test(wanted)) {
    const names = found.length > 0 ? found : await discover($)
    const hits = /^\d+$/.test(wanted)
      ? names.slice(Number(wanted) - 1, Number(wanted))
      : names.includes(wanted)
        ? [wanted]
        : names.filter(one => one.toLowerCase().includes(wanted.toLowerCase()))
    if (hits.length !== 1) {
      return hits.length === 0
        ? `No research project matches "${wanted}". /repro-status list shows them all.`
        : `"${wanted}" matches ${hits.length} projects. Specify the name further:\n  ${hits.join('\n  ')}`
    }
    name = hits[0] as string
  }
  const path = /^[~/.]/.test(name) ? await absolute($, name) : `${parent(cwd)}/${name}`
  if (!(await $.fs.exists(path))) {
    return `No such folder: ${path}`
  }
  project = (await projectOf($, path)) ?? path
  isPinned = true
  await save($)

  return `Working project set to ${project}`
}

async function refresh($: EngineInterface) {
  lastStatus = project ? await status($, project, false) : ''
  await show($)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'repro-status',
      description: "(reproducible-science) Instant status of a project's ledger, plans and quotations",
      argumentHint: '[part of a project name | pick | list | auto]',
    })
    await $.command.register({
      name: 'repro-hide',
      description: '(reproducible-science) Hide the readout above the prompt',
    })
    await $.command.register({
      name: 'repro-show',
      description: '(reproducible-science) Show the readout above the prompt again',
    })
    await $.command.register({
      name: 'repro-verify',
      description: "(reproducible-science) Check every pinned quotation of the working project against its source",
    })
    project = (await read($, savedProject)) ?? undefined
    isPinned = await read($, savedPin)
    await $.tool.register({
      name: 'set_project',
      description:
        'Declare which research project this session is working on, when it differs from the ' +
        'folder the session started in. Give the project folder as an absolute path. The ' +
        'record checks, the status line and the gates then follow that project.',
      inputSchema: {
        type: 'object',
        properties: { path: { type: 'string', description: 'Absolute path of the project folder' } },
        required: ['path'],
      },
    })
    await track($, await $.session.cwd())
    await refresh($)

    return next(e)
  })

  on('tool.call', { tool: 'Read' }, async ($, e, next) => {
    await track($, e.file_path)

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    await refresh($)

    return next(e)
  })

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)

    return project
      ? {
          sections: [
            ...composed.sections,
            {
              id: 'repro:gates',
              text: `${GATES}\n\nState of this project's records as of the last turn: ${lastStatus}.`,
              scope: 'session',
            },
          ],
        }
      : composed
  })

  for (const tool of ['Edit', 'Write'] as const) {
    on('tool.call', { tool }, async ($, e, next) => {
      const path = await absolute($, e.file_path)
      await track($, path)

      if (path.includes('/') && (await $.fs.exists(recordOf(path)))) {
        return {
          deny:
            `${path} has a freeze record (${recordOf(path)}), and a frozen file never changes by ` +
            `one byte. Record a note with \`prereg log\`, or a change to the plan as an ` +
            `amendment with \`prereg amend\`, which is a file of its own. Ask the user before ` +
            `doing either.`,
        }
      }

      if (path.endsWith(`/${PLAN}`) && (await $.fs.exists(path)) && FROZEN.test(await $.fs.read(path))) {
        return {
          deny:
            `${path} is a frozen registration, and a frozen plan is not edited in place. ` +
            `Record the change as an amendment or a deviation with \`prereg log\`, which keeps ` +
            `the frozen text and its digest. If the plan must be replaced, ask the user first.`,
        }
      }

      const ran = await next(e)
      if (ran.deny !== undefined || !MANUSCRIPT.test(path) || told.has(path)) {
        return ran
      }
      if (await above($, dirOf(path), LEDGER)) {
        return ran
      }
      told.add(path)

      return {
        ...ran,
        context: [
          ...(ran.context ?? []),
          `reproducible-science: ${path} is a manuscript and no .results/ ledger exists at or above it, ` +
            `so no number in it is bound to a run. Before reporting a result here, run ` +
            `\`results init\`, seal the inputs, and bind each sentence with \`results claim\`. ` +
            `If this file reports no results of this project, say so to the user and continue.`,
        ],
      }
    })
  }

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const target = cdTarget(e.command)
    if (target) {
      await track($, target)
    }
    const ran = await next(e)
    const cwd = target ? await absolute($, target) : await $.session.cwd()
    const fetched = download(e.command)
    if (ran.deny === undefined && !ran.isError && fetched && !told.has(fetched[1])) {
      told.add(fetched[1])

      return {
        ...ran,
        context: [
          ...(ran.context ?? []),
          `reproducible-science: ${fetched[1]} was downloaded from ${fetched[0]}. When this source is ` +
            `pinned, write that address as \`url:\` under \`source:\` in its claims file, beside ` +
            `its sha256 and its \`doi:\`, so \`citations fetch\` can retrieve the same bytes ` +
            `for a reader. Record the address the file came from, not a landing page.`,
        ],
      }
    }
    if (ran.deny !== undefined || !project || told.has(cwd) || !runsAnAnalysis(e.command)) {
      return ran
    }
    if (await above($, cwd, LEDGER)) {
      return ran
    }
    told.add(cwd)

    return {
      ...ran,
      context: [
        ...(ran.context ?? []),
        `reproducible-science: that command ran an analysis in a project with no .results/ ledger. If a ` +
          `paper will report its output, \`results init\` and \`results seal\` the inputs before ` +
          `the run that counts. If it was exploratory, no record is owed.`,
      ],
    }
  })

  on('tool.call', { tool: 'mcp__repro__set_project' }, async ($, e) => {
    const said = await choose($, String(e.path ?? ''))
    await refresh($)

    return { result: `${said}\n${lastStatus}` }
  })

  // One dim row directly above the prompt, drawn by this mod. The hint line under the prompt
  // takes a `tail`, and the terminal leaves the tail out where the row has no room beside its
  // own mode labels, which on a session with several of them is always.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const line = await read($, shownStatus)
    if (!line || e.props.hasSurvey || (await read($, hidden))) {
      return next(e)
    }
    const { Box, Text } = $.ui.resolve(e)

    // The engine draws its collapse mark, `[-]`, over the last columns of the band's first row.
    // Unpadded, a line wrapping there lost the characters under it: `4 sealed, 0 claims` showed
    // as `4 sealed,` then `claims`.
    // One field per row, always: the project's name with the plans, then the runs, then the
    // quotations, then the manifest's assertions where there is a manifest. Laid side by side they read differently at every window width.
    const [name, first, ...rest] = line.split(' · ')
    const fields = first === undefined ? [name ?? ''] : [`${name} · ${first}`, ...rest]

    // A row with a next step still to take names the command that takes it.
    const isNew = fields.length === NOTHING.length && NOTHING.every((state, at) => state.test(fields[at] ?? ''))
    const hints = fields.map((field, at) =>
      isNew ? (at === 0 ? 'repro init' : undefined) : HINTS.find(([state]) => state.test(field))?.[1],
    )
    // The hint follows its row directly. Set in a column, it sat as far right as the longest row,
    // and a long project name pushed it off the edge of the window.
    const rows = fields.map((field, at) => (hints[at] ? `${field}  →  ${hints[at]}` : field))

    return h(
      Box,
      { paddingRight: 5, flexDirection: 'column' },
      ...rows.map((row, at) => h(Text, { key: `field:${at}`, dimColor: true }, row)),
    )
  })

  on('ui.render', { component: 'Pane', requestId: PICKER }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const rows = await read($, windowRows)
    const first = Math.min(await read($, top), lastTop(rows))
    const shown = found.slice(first, first + rows)
    const current = project?.replace(/^.*\//, '')
    const start = shown.includes(current ?? '') ? current : shown[0]

    return h(
      Box,
      { flexDirection: 'column' },
      ...shown.map(name =>
        h(Button, {
          key: `${ROW}${name}`,
          label: name,
          plain: true,
          dimColor: true,
          ...(name === start ? { autoFocus: true } : {}),
          // Closed first: the checks behind the status take seconds, and a pane that waits
          // for them looks like a pick that did nothing.
          onPress: async () => {
            await $.ui.close({ id: PICKER })
            await choose($, name)
            await refresh($)
          },
        }),
      ),
      h(
        Text,
        { dimColor: true },
        `${first + 1}–${Math.min(first + rows, found.length)} of ${found.length} · Enter to pick · Esc to close`,
      ),
    )
  })

  // The ring keeps its position in the pane, not its row: after the window slides, the ring is
  // on the same line and that line shows the next project. So the window slides exactly when an
  // arrow on the last line asks the ring to wrap to the first (or the reverse): the wrap is
  // refused, the window moves by one, and the ring stays on its line, now showing the next
  // project. The ring wraps for real only at the two ends of the whole list.
  on('ui.focus', async ($, e, next) => {
    const landed = e.element ?? (e as { key?: string }).key
    if (e.requestId !== PICKER || !landed?.startsWith(ROW)) {
      return next(e)
    }
    const rows = Math.min(await read($, windowRows), found.length)
    const first = Math.min(await read($, top), lastTop(rows))
    const line = found.indexOf(landed.slice(ROW.length)) - first

    const isWrapDown = lastLine === rows - 1 && line === 0
    const isWrapUp = lastLine === 0 && line === rows - 1
    if (e.origin?.kind !== 'person' || rows < 2 || !(isWrapDown || isWrapUp)) {
      lastLine = line

      return next(e)
    }
    if (isWrapDown && first < lastTop(rows)) {
      await update($, top, () => first + 1)
    } else if (isWrapUp && first > 0) {
      await update($, top, () => first - 1)
    } else {
      // An end of the whole list: go round to the other end.
      await update($, top, () => (isWrapDown ? 0 : lastTop(rows)))
      lastLine = isWrapDown ? 0 : rows - 1
      void $.ui.focus({ requestId: PICKER, key: `${ROW}${found[isWrapDown ? 0 : found.length - 1]}` })
    }

    return { deny: 'the list moved to the next project' }
  })

  // A scroll in the picker means the tree did not fit the pane the layout granted. The window
  // shrinks to the pane's real height, and the pane is held at its top.
  on('ui.scroll', async ($, e, next) => {
    if (e.requestId !== PICKER || e.origin.kind !== 'person') {
      return next(e)
    }
    if (e.contentRows > e.bodyRows) {
      await update($, windowRows, () => Math.max(2, e.bodyRows - 1))
    }

    return next({ ...e, offset: 0 })
  })

  on('command.run', { command: 'repro-status' }, async ($, e) => {
    const wanted = (e.args ?? '').trim()
    if (wanted === 'list') {
      const names = await discover($)

      return {
        text:
          `${names.length} research projects. Set one with /repro-status <number or ` +
          `part of its name>:\n${names.map((name, at) => `  ${String(at + 1).padStart(2)}  ${name}`).join('\n')}`,
      }
    }
    if (wanted === 'pick' || (!wanted && !project)) {
      const names = await discover($)
      const here = names.indexOf(project?.replace(/^.*\//, '') ?? '')
      const rows = await read($, windowRows)
      await update($, top, () => Math.min(Math.max(0, here - 1), lastTop(rows)))
      lastLine = 0
      await $.ui.open({
        id: PICKER,
        title: 'Research projects',
        focus: true,
        closeOnEscape: true,
        holdToasts: true,
        rows: rows + 1,
      })

      return {
        text:
          `${names.length} research projects. ↑ and ↓ to move, Enter to pick, Esc to close. ` +
          `Or run /repro-status <part of a name>.`,
      }
    }
    const said = wanted ? [await choose($, wanted)] : []
    if (!project || said.some(line => !line.startsWith('Working project') && !line.startsWith('Following'))) {
      return { text: said.join('\n') }
    }
    const lines = [...said, await status($, project, true)]
    lastStatus = lines[said.length] ?? lastStatus
    await show($)

    return { text: lines.join('\n') }
  })

  // The readout is drawn every turn, and in a short window it takes rows the person may want back.
  // A warning is not part of it: that line stays, because it only appears when something is wrong.
  on('command.run', { command: 'repro-hide' }, async $ => {
    await update($, hidden, () => true)

    return { text: 'Readout hidden. /repro-show brings it back.' }
  })

  on('command.run', { command: 'repro-show' }, async $ => {
    await update($, hidden, () => false)

    return { text: 'Readout shown.' }
  })

  // The full quotation check. It reads every pinned source, which takes minutes on a large
  // project, so it has its own command and `/repro-status` stays instant.
  on('command.run', { command: 'repro-verify' }, async $ => {
    if (!project) {
      return { text: 'No working project. Run /repro-status <part of a name> first.' }
    }
    const checked: string[] = []
    const folders = await claimsFolders($, project)
    const count = (text: string | undefined) => Number((text ?? '0').replace(/,/g, ''))
    let pinned = 0
    let found = 0
    let notFound = 0
    for (const folder of folders) {
      const ran = await $.process.run(['citations', 'verify', '--claims', folder], {
        cwd: project,
        timeoutMs: 300_000,
      })
      checked.push(
        folder,
        ...ran.stdout.split('\n').filter(line => /^\s+(found|not found|unchecked|ambiguous)\s/.test(line)),
      )
      pinned += count(/^([\d,]+) quotes?$/m.exec(ran.stdout)?.[1])
      found += count(/^\s+found\s+([\d,]+)/m.exec(ran.stdout)?.[1])
      notFound += count(/^\s+not found\s+([\d,]+)/m.exec(ran.stdout)?.[1])
    }
    if (pinned > 0) {
      const root = project
      const line = `${found.toLocaleString('en-US')}/${pinned.toLocaleString('en-US')} quotes found`
      await update($, quotations, saved => ({ ...saved, [root]: line }))
      await update($, quotationsNotFound, saved => ({ ...saved, [root]: notFound }))
    }
    if (folders.length === 0) {
      checked.push('no claims folder, so no quotations are pinned')
    }
    const lines = [await status($, project, true), ...checked]
    lastStatus = lines[0] ?? lastStatus
    await show($)

    return { text: lines.join('\n') }
  })
}
