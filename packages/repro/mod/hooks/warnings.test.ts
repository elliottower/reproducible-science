import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

/** Every text pinned under the prompt, as JSON; `undefined` (cleared) is recorded as null. */
const pinned: string[] = []

function project(on: On, ledger: string, plans: string) {
  pinned.length = 0
  on('session.cwd', () => ({ value: '/work/study' }))
  on('fs.exists', (_$, e) => ({ value: e.path.startsWith('/work/study/.results') || e.path === '/work/study' }))
  on('fs.read', () => ({ value: ledger }))
  on('fs.list', () => ({ value: [] }))
  on('ui.status', (_$, e) => {
    pinned.push(JSON.stringify(e))

    return { value: undefined as never }
  })
  on('process.run', (_$, e) => ({
    value: {
      exitCode: 0,
      stdout: e.argv[0] === 'results' ? 'chain intact: 3 events, anchored\n' : plans,
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
  }))
}

test('an edited frozen plan and runs with nothing sealed are pinned as warnings', async ($, on) => {
  project(on, '{"event":"init"}\n{"event":"run"}\n{"event":"run"}\n', 'CHANGED      /work/study/PREREG.md\n')

  await $.command.run({ command: 'repro-status', args: '/work/study' })

  const last = pinned.at(-1) ?? ''
  expect(last).toContain('1 plan edited after freeze · 2 runs, nothing sealed')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a project with nothing wrong pins nothing', async ($, on) => {
  project(on, '{"event":"init"}\n{"event":"seal"}\n{"event":"run"}\n', 'unchanged    /work/study/PREREG.md\n')

  await $.command.run({ command: 'repro-status', args: '/work/study' })

  expect(pinned.at(-1)).not.toContain('edited')
  expect(pinned.at(-1)).not.toContain('sealed')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

/** What `repro verify` prints for these assertion lines and this line of counts. */
const printed = (lines: string[], counts: string) =>
  `/work/audit/repro.yaml\n\n${lines.map(line => `  ${line}\n`).join('')}\n  ${counts}\n  policy publication: FAILED  (1 errors, 0 warnings)\n`

/**
 * A healthy project at `root` with a manifest and one claims folder, where `repro verify` and
 * `citations verify` print what is given.
 */
function audited(on: On, root: string, repro: string, citations: string) {
  pinned.length = 0
  on('session.cwd', () => ({ value: root }))
  on('fs.exists', (_$, e) => ({ value: [root, `${root}/repro.yaml`, `${root}/claims`].includes(e.path) }))
  on('fs.read', () => ({ value: '' }))
  on('fs.list', () => ({ value: [] }))
  on('ui.status', (_$, e) => {
    pinned.push(JSON.stringify(e))

    return { value: undefined as never }
  })
  on('process.run', (_$, e) => ({
    value: {
      exitCode: 0,
      stdout:
        e.argv[0] === 'repro'
          ? repro
          : e.argv[0] === 'citations'
            ? citations
            : e.argv[0] === 'find'
              ? './claims\n'
              : e.argv[0] === 'grep'
                ? '3\n'
                : '',
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
  }))
}

const ALL_VERIFIED = '/work/audit/repro.yaml\n\n  3 verified\n  policy publication: passed  (0 errors, 0 warnings)\n'

test('a number that does not match its results file is pinned as a warning', async ($, on) => {
  audited(
    on,
    '/work/numbers',
    printed(['ok    mean         quote    ', 'MISS  mean         correspondence mean: manuscript 4.9, run 4.2'], '1 mismatch, 3 verified'),
    '',
  )

  await $.command.run({ command: 'repro-status', args: '/work/numbers' })

  expect(pinned.at(-1)).toContain('"1 number mismatched"')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('mismatched quotations are worded apart from mismatched numbers', async ($, on) => {
  audited(
    on,
    '/work/mixed',
    printed(
      [
        'MISS  mean         metric   /mean = 4.2',
        'MISS  spread       table    spread: reported 0.9, found 0.7',
        'MISS  wording      quote      [short]',
      ],
      '3 mismatch, 1 verified',
    ),
    '',
  )

  await $.command.run({ command: 'repro-status', args: '/work/mixed' })

  expect(pinned.at(-1)).toContain('"2 numbers mismatched · 1 quotation mismatched"')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('mismatches whose kind cannot be read off the lines are called claims', async ($, on) => {
  audited(on, '/work/spaced', printed(['MISS  mean of all  metric   /mean = 4.2'], '2 mismatch, 1 verified'), '')

  await $.command.run({ command: 'repro-status', args: '/work/spaced' })

  expect(pinned.at(-1)).toContain('"2 claims mismatched"')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('quotations the full check did not find are pinned by the tool’s count, not by pinned less found', async ($, on) => {
  audited(on, '/work/quoted', ALL_VERIFIED, '6 quotes\n\n  found               3\n  not found           1\n  unchecked           2\n')

  await $.command.run({ command: 'repro-status', args: '/work/quoted' })
  expect(pinned.at(-1)).not.toContain('not found')

  const verified = await $.command.run({ command: 'repro-verify', args: '' })
  expect(verified.text).toContain('citations: 3/6 quotes found')
  expect(pinned.at(-1)).toContain('"1 quotation not found"')

  await $.command.run({ command: 'repro-status', args: '' })
  expect(pinned.at(-1)).toContain('"1 quotation not found"')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('verified assertions, found quotations and unchecked ones pin nothing', async ($, on) => {
  audited(
    on,
    '/work/clean',
    '/work/clean/repro.yaml\n\n  1 not_offered, 2 unchecked, 3 verified\n  policy publication: passed  (0 errors, 2 warnings)\n',
    '5 quotes\n\n  found               3\n  unchecked           2\n',
  )

  await $.command.run({ command: 'repro-status', args: '/work/clean' })
  const shown = await $.command.run({ command: 'repro-verify', args: '' })

  expect(shown.text).toContain('citations: 3/5 quotes found · repro: 2 unchecked, 1 not offered, 3 verified')
  expect(pinned.at(-1)).toBe(JSON.stringify({}))
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a claim bound to a test run is pinned as a warning', async ($, on) => {
  const ledger =
    '{"event":"init","seq":0}\n' +
    '{"event":"seal","seq":1,"files":[{"path":"a.csv"}]}\n' +
    '{"event":"run","seq":2,"run_id":"smoke_s1"}\n' +
    '{"event":"run","seq":3,"run_id":"s1"}\n' +
    '{"event":"claim","seq":4,"run_id":"smoke_s1"}\n' +
    '{"event":"claim","seq":5,"run_id":"s1"}\n'
  const pinned: string[] = []
  on('session.cwd', () => ({ value: '/work/study' }))
  on('fs.exists', (_$, e) => ({ value: e.path === '/work/study' || e.path.startsWith('/work/study/.results') }))
  on('fs.read', () => ({ value: ledger }))
  on('fs.list', () => ({ value: [] }))
  on('ui.status', (_$, e) => {
    pinned.push(JSON.stringify(e))

    return { value: undefined as never }
  })
  on('process.run', (_$, e) => ({
    value: {
      exitCode: 0,
      stdout: e.argv[0] === 'results' ? 'chain intact: 6 events, anchored\n' : '',
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
  }))

  const shown = await $.command.run({ command: 'repro-status', args: '/work/study' })

  expect(shown.text).toContain('results: 1/1 runs sealed, 2 numbers bound')
  expect(pinned.join(' ')).toContain('1 claim on test runs')
})
