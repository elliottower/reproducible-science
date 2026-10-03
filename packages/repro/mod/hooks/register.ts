import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

/** What `prereg freeze` writes into a plan. Its presence is what makes a plan frozen. */
const FROZEN = /^\*\*Plan sha256:\*\*[ \t]*`[0-9a-f]{64}`/m

const PLAN = 'PREREG.md'
const LEDGER = '.results/ledger.jsonl'
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
3. Before a confirmatory analysis runs: \`prereg freeze\` the plan. A frozen plan is never edited in place; a change is recorded with \`prereg log\`.

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
 * quotations takes minutes, so the status line never runs it: `/repro-status` does, and the
 * result is kept here, in the session's state, until the next one.
 */
const quotations = atom({ plugin: 'repro', key: 'quotations' } as const, {} as Record<string, string>)

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
 *     study · prereg: 1/1 frozen · results: 3 runs, 2 sealed, 4 claims · citations: 120/120 found
 *
 * Fractions only where there is a real total. The project's name stays, because the project
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
  const counts = new Map<string, number>()
  for (const line of (plans ?? '').split('\n')) {
    const label = /^([A-Za-z][A-Za-z ]*?)\s{2,}\//.exec(line)?.[1]?.toLowerCase()
    if (label) {
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
        ? 'prereg: no plan'
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
      const count = (kind: string) => (ledger.match(new RegExp(`"event":"${kind}"`, 'g')) ?? []).length
      const changed = (verified.match(/^\s+(CHANGED|MISSING)\s/gm) ?? []).length
      runs = count('run')
      fields.push(
        `results: ${changed ? `${changed} changed, ` : ''}${plural(runs, 'run')}, ` +
          `${count('seal')} sealed, ${plural(count('claim'), 'claim')}`,
      )
      if (changed) {
        wrong.push(`${plural(changed, 'sealed file')} changed`)
      }
      if (/^TIMESTAMP CONTRADICTS/m.test(verified)) {
        wrong.push('ledger rewritten after timestamp')
      }
      if (runs > 0 && count('seal') === 0) {
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

  if (await $.fs.exists(`${root}/claims`)) {
    const last = (await read($, quotations))[root]
    if (last) {
      fields.push(`citations: ${last}`)
    } else {
      // Counting what is pinned is one grep; checking it is minutes, and `/repro-status` does that.
      const counted = await output($, ['grep', '-rhcE', '^[[:space:]]*-?[[:space:]]*exact:', 'claims'], root, 20_000)
      const pinned = (counted ?? '').split('\n').reduce((sum, n) => sum + (Number(n) || 0), 0)
      fields.push(`citations: ${pinned.toLocaleString('en-US')} pinned, not verified`)
    }
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
    if (!line || e.props.hasSurvey) {
      return next(e)
    }
    const { Box, Text } = $.ui.resolve(e)

    // The engine draws its collapse mark, `[-]`, over the last columns of the band's first row.
    // Unpadded, a line wrapping there lost the characters under it: `4 sealed, 0 claims` showed
    // as `4 sealed,` then `claims`.
    // One element per field, so the row breaks between fields and never inside one:
    // `0 claims` split across two rows read as a count belonging to the field before it.
    const fields = line.split(' · ')

    return h(
      Box,
      { paddingRight: 5, flexDirection: 'row', flexWrap: 'wrap' },
      ...fields.map((field, at) =>
        h(Text, { key: `field:${at}`, dimColor: true }, at < fields.length - 1 ? `${field} · ` : field),
      ),
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
    // The quotations first, so the status line computed after them carries this check's count.
    const checked: string[] = []
    if (await $.fs.exists(`${project}/claims`)) {
      const ran = await $.process.run(['citations', 'verify', '--claims', 'claims/'], {
        cwd: project,
        timeoutMs: 300_000,
      })
      checked.push(...ran.stdout.split('\n').filter(line => /^\s+(found|not found|unchecked|ambiguous)\s/.test(line)))
      const pinned = /^([\d,]+) quotes?$/m.exec(ran.stdout)?.[1]
      const found = /^\s+found\s+([\d,]+)/m.exec(ran.stdout)?.[1] ?? '0'
      if (pinned) {
        const root = project
        await update($, quotations, saved => ({ ...saved, [root]: `${found}/${pinned} found` }))
      }
    } else {
      checked.push('no claims/ directory, so no quotations are pinned')
    }
    const lines = [...said, await status($, project, true), ...checked]
    lastStatus = lines[said.length] ?? lastStatus
    await show($)

    return { text: lines.join('\n') }
  })
}
