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
  expect(await ui.find({ type: 'Text', text: /^study · prereg: none drafted$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^results: 0 runs, 0 numbers bound/ })).toBeDefined()
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

/** The rows the band draws for a project at `root`, where only the paths in `existing` exist. */
async function rows($: Parameters<TestBody>[0], on: Parameters<TestBody>[1], root: string, existing: string[]) {
  on('session.cwd', () => ({ value: root }))
  on('fs.exists', (_$, e) => ({ value: existing.includes(e.path) }))
  on('fs.read', () => ({ value: '' }))
  on('fs.list', () => ({ value: [] }))
  on('ui.status', () => ({ value: undefined as never }))
  on('process.run', (_$, e) => ({
    value: {
      exitCode: 0,
      stdout:
        e.argv[0] === 'repro'
          ? `${root}/repro.yaml\n\n  ok    n  metric   /n = 3\n\n  3 verified\n  policy publication: passed  (0 errors, 0 warnings)\n`
          : '',
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
  }))
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

test('the band draws exactly three rows for a project with no manifest', async ($, on) => {
  expect(await rows($, on, '/work/plain', ['/work/plain', '/work/plain/PREREG.md'])).toEqual([
    'plain · prereg: none drafted',
    'results: no ledger',
    'citations: none pinned',
  ])
})

test('the band draws the manifest’s assertions as a fourth row', async ($, on) => {
  expect(await rows($, on, '/work/bound', ['/work/bound', '/work/bound/PREREG.md', '/work/bound/repro.yaml'])).toEqual([
    'bound · prereg: none drafted',
    'results: no ledger',
    'citations: none pinned',
    'repro: 3/3 checks verified',
  ])
})
