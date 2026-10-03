import { expect, test } from 'claude-code/testing'

test('the band above the prompt draws the readout', async ($, on) => {
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
  expect(await ui.find({ type: 'Text', text: /study · prereg: no plan · results: 0 runs/ })).toBeDefined()
  await ui.unmount()
})
