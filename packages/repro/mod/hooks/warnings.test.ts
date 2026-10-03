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
