import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

test('the band above the prompt draws one field per row', async ($, on) => {
  on('session.cwd', () => ({ value: '/work/study' }))
  on('fs.exists', (_$, e) => ({ value: e.path.startsWith('/work/study') }))
  on('fs.read', () => ({ value: '' }))
  on('fs.list', () => ({ value: [] }))
  on('ui.status', () => ({ value: undefined as never }))
  on('process.run', (_$, e) => ({
    value: {
      exitCode: 0,
      stdout: e.argv[0] === 'results' ? 'chain intact: 5 events, anchored\n' : '',
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
  }))
  await $.command.run({ command: 'repro-status', args: '/work/study' })

  const ui = await $.ui.mount({
    plugin: 'repro',
    surface: 'terminal',
    component: 'AbovePrompt',
    props: { hasSurvey: false, isWorking: false, maxRows: 10, columns: 120 } as never,
  })
  expect(await ui.find({ type: 'Text', text: /^study · prereg: none drafted {2}→ {2}prereg new$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^results: 0 runs, 0 claims bound/ })).toBeDefined()
  await ui.unmount()
})

test('the hide command removes the band and the show command brings it back', async ($, on) => {
  on('ui.render', { component: 'AbovePrompt' } as never, ($, e) => h($.ui.resolve(e as never).Box, {}))
  on('session.cwd', () => ({ value: '/work/study' }))
  on('fs.exists', (_$, e) => ({ value: e.path.startsWith('/work/study') }))
  on('fs.read', () => ({ value: '' }))
  on('fs.list', () => ({ value: [] }))
  on('ui.status', () => ({ value: undefined as never }))
  on('process.run', () => ({
    value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  }))
  await $.command.run({ command: 'repro-status', args: '/work/study' })
  const props = { hasSurvey: false, isWorking: false, maxRows: 10, columns: 120 } as never
  const drawn = async () => {
    const ui = await $.ui.mount({ plugin: 'repro', surface: 'terminal', component: 'AbovePrompt', props })
    const row = await ui.find({ type: 'Text', text: /prereg:/ }).catch(() => undefined)
    await ui.unmount()

    return row !== undefined && row !== null
  }

  expect(await drawn()).toBe(true)
  expect((await $.command.run({ command: 'repro-hide', args: '' })).text).toContain('hidden')
  expect(await drawn()).toBe(false)
  await $.command.run({ command: 'repro-hide', args: '' })
  expect(await drawn()).toBe(false)
  expect((await $.command.run({ command: 'repro-show', args: '' })).text).toContain('shown')
  expect(await drawn()).toBe(true)
})

/** Every command the mod ran in the last `rows`, its words joined by spaces. */
const spawned: string[] = []

/**
 * The rows the band draws for a project at `root`, where only the paths in `existing` exist. The
 * manifest reads as `manifest`, and `repro stale` prints `stale` (null: it times out).
 */
async function rows(
  $: Parameters<TestBody>[0],
  on: Parameters<TestBody>[1],
  root: string,
  existing: string[],
  manifest = '',
  stale: string | null = '',
) {
  on('session.cwd', () => ({ value: root }))
  on('fs.exists', (_$, e) => ({ value: existing.includes(e.path) }))
  on('fs.read', (_$, e) => ({ value: e.path === `${root}/repro.yaml` ? manifest : '' }))
  on('fs.list', () => ({ value: [] }))
  on('ui.status', () => ({ value: undefined as never }))
  on('process.run', (_$, e) => {
    spawned.push(e.argv.join(' '))
    if (e.argv[1] === 'stale' && stale === null) {
      throw new Error('$.process.run(repro) aborted: still running after 60000ms')
    }

    return {
      value: {
        exitCode: 0,
        stdout:
          e.argv[1] === 'stale'
            ? (stale ?? '')
            : e.argv[0] === 'repro'
              ? `${root}/repro.yaml\n\n  ok    n  metric   /n = 3\n\n  3 verified\n  policy publication: passed  (0 errors, 0 warnings)\n`
              : '',
        stderr: '',
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    }
  })
  await $.command.run({ command: 'repro-status', args: root })
  const ui = await $.ui.mount({
    plugin: 'repro',
    surface: 'terminal',
    component: 'AbovePrompt',
    props: { hasSurvey: false, isWorking: false, maxRows: 10, columns: 120 } as never,
  })
  const drawn = (await ui.findAll({ type: 'Text' })).map(row => row.text)
  await ui.unmount()

  return drawn
}

test('a project with nothing set up is pointed at the one command that starts all four', async ($, on) => {
  expect(await rows($, on, '/work/plain', ['/work/plain', '/work/plain/PREREG.md'])).toEqual([
    'plain · prereg: none drafted  →  repro init',
    'results: no ledger',
    'citations: none pinned',
    'repro: no manifest',
  ])
})

test('the band draws the manifest’s assertions as a fourth row', async ($, on) => {
  expect(await rows($, on, '/work/bound', ['/work/bound', '/work/bound/PREREG.md', '/work/bound/repro.yaml'])).toEqual([
    'bound · prereg: none drafted  →  prereg new',
    'results: no ledger  →  results init',
    'citations: none pinned  →  citations pin',
    'repro: 3/3 checks verified',
  ])
})

test('a project with a ledger and no manifest is pointed at the command that writes one', async ($, on) => {
  expect(
    await rows($, on, '/work/half', ['/work/half', '/work/half/.results', '/work/half/.results/ledger.jsonl']),
  ).toContain('repro: no manifest  →  repro manifest init')
})

const BOUND = ['/work/bound', '/work/bound/PREREG.md', '/work/bound/repro.yaml']
const FIRST_ROWS = [
  'bound · prereg: none drafted  →  prereg new',
  'results: no ledger  →  results init',
  'citations: none pinned  →  citations pin',
  'repro: 3/3 checks verified',
]
const DECLARES = 'project: bound\nregenerations:\n  - id: fit\n    command: [python, fit.py]\n'

type Command = { state: string; rerun_at?: string | null; witness?: { kind: string } | null }

/** What `repro stale --format json` prints for a manifest declaring `commands`. */
const report = (commands: Command[]) =>
  JSON.stringify({
    staleness: {
      reruns: 2,
      regenerations: commands.map((command, at) => ({
        id: `r${at}`,
        artifact: `a${at}`,
        causes: [],
        rerun_at: null,
        witness: null,
        ...command,
      })),
    },
    assessment: { passed: true },
  })

/** `n` declared commands in one state, last compared with a re-run that started at `rerun_at`. */
const commands = (n: number, state: string, rerun_at: string | null = null): Command[] =>
  Array.from({ length: n }, () => ({ state, rerun_at }))

test('every declared command reproduced draws a fifth row with the day of the last re-run', async ($, on) => {
  const stale = report([...commands(6, 'current', '2026-09-30T12:00:00+00:00'), ...commands(1, 'current', '2026-10-13T12:00:00+00:00')])

  expect(await rows($, on, '/work/bound', BOUND, DECLARES, stale)).toEqual([
    ...FIRST_ROWS,
    'repro: 7/7 reproduced, last 13 Oct',
  ])
  expect(spawned).toContain('repro stale --format json')
})

test('stale commands are counted with the day of the last re-run and pointed at a re-run', async ($, on) => {
  const stale = report([...commands(5, 'current', '2026-10-02T12:00:00+00:00'), ...commands(2, 'stale', '2026-10-13T12:00:00+00:00')])

  expect(await rows($, on, '/work/bound', BOUND, DECLARES, stale)).toEqual([
    ...FIRST_ROWS,
    'repro: 5/7 reproduced, 2 stale since 13 Oct  →  repro reproduce',
  ])
})

test('commands declared and never re-run, as with no record of re-runs, read as none reproduced', async ($, on) => {
  expect(await rows($, on, '/work/bound', BOUND, DECLARES, report(commands(7, 'never_rerun')))).toEqual([
    ...FIRST_ROWS,
    'repro: 0/7 reproduced  →  repro reproduce',
  ])
})

test('a command whose files are missing is counted as undetermined, beside the last re-run', async ($, on) => {
  const stale = report([...commands(5, 'current', '2026-10-13T12:00:00+00:00'), ...commands(1, 'undetermined'), ...commands(1, 'never_rerun')])

  expect(await rows($, on, '/work/bound', BOUND, DECLARES, stale)).toEqual([
    ...FIRST_ROWS,
    'repro: 5/7 reproduced, 1 undetermined, last 13 Oct  →  repro reproduce',
  ])
})

test('a last re-run witnessed in a workflow is said to be in CI', async ($, on) => {
  const stale = report([
    { state: 'current', rerun_at: '2026-10-02T12:00:00+00:00' },
    { state: 'current', rerun_at: '2026-10-13T12:00:00+00:00', witness: { kind: 'github_actions' } },
  ])

  expect(await rows($, on, '/work/bound', BOUND, DECLARES, stale)).toEqual([
    ...FIRST_ROWS,
    'repro: 2/2 reproduced, last 13 Oct in CI',
  ])
})

test('a manifest that declares no commands draws no fifth row, and the re-runs are never read', async ($, on) => {
  spawned.length = 0

  expect(await rows($, on, '/work/bound', BOUND, 'project: bound\nclaims: []\n', report(commands(7, 'current')))).toEqual(
    FIRST_ROWS,
  )
  expect(spawned).not.toContain('repro stale --format json')
})

test('a record of re-runs that cannot be read draws no fifth row and leaves the others standing', async ($, on) => {
  expect(await rows($, on, '/work/bound', BOUND, DECLARES, '')).toEqual(FIRST_ROWS)
})

test('a read of the re-runs that times out draws no fifth row and leaves the others standing', async ($, on) => {
  expect(await rows($, on, '/work/bound', BOUND, DECLARES, null)).toEqual(FIRST_ROWS)
})
