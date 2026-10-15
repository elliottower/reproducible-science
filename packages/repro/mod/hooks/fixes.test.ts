import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'
import { isMine, parseQueue } from './register'

const req = (project: string, id = 'a') => ({
  id,
  created_at: '2026-10-14T18:00:00Z',
  project,
  subject: `claim-${id}`,
  kind: 'claim' as const,
  prompt: `fix ${id}`,
})
const QUEUE = '/home/u/.claude/repro-fixes/queue.jsonl'
const HANDLED = '/home/u/.claude/repro-fixes/handled.json'
const PROPS = { hasSurvey: false, isWorking: false, maxRows: 10, columns: 120 } as never

/** Stands for the engine: a session in `cwd` whose files are `files`. Returns what was put in the prompt box. */
function engine(on: On, cwd: string, files: Record<string, string>) {
  const filled: string[] = []
  on('ui.render', { component: 'AbovePrompt' } as never, ($, e) => h($.ui.resolve(e as never).Box, {}))
  on('env.get', () => ({ value: '/home/u' }))
  on('session.cwd', () => ({ value: cwd }))
  on('fs.exists', (_$, e) => ({
    value: e.path in files || Object.keys(files).some(f => f.startsWith(`${e.path}/`)),
  }))
  on('fs.read', (_$, e) => ({ value: files[e.path] ?? '' }))
  on('fs.write', (_$, e) => {
    files[e.path] = e.text

    return { value: undefined as never }
  })
  on('fs.list', () => ({ value: [] }))
  on('ui.toast', () => ({ value: undefined as never }))
  on('ui.status', () => ({ value: undefined as never }))
  on('process.run', () => ({
    value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  }))
  on('prompt.fill', (_$, e) => {
    filled.push(e.text)

    return { isFilled: true } as never
  })
  on('tool.call', () => ({ result: {} as never }))

  return filled
}

/** Every Text the band above the prompt draws. */
async function band($: Parameters<TestBody>[0]) {
  const ui = await $.ui.mount({ plugin: 'repro', surface: 'terminal', component: 'AbovePrompt', props: PROPS })
  const drawn = (await ui.findAll({ type: 'Text' })).map(row => row.text)
  await ui.unmount()

  return drawn
}

test('parseQueue keeps whole requests and skips a partly written line', async () => {
  const text = `${JSON.stringify(req('/p', 'one'))}\n{"id": "two", "proj\n\n${JSON.stringify(req('/p', 'three'))}\n`
  expect(parseQueue(text).map(r => r.id)).toEqual(['one', 'three'])
})

test('isMine: the project, a folder inside it, or a followed project; never a sibling sharing a prefix', async () => {
  expect(isMine(req('/u/paper'), '/u/paper', [])).toBe(true)
  expect(isMine(req('/u/paper'), '/u/paper/scripts', [])).toBe(true)
  expect(isMine(req('/u/paper'), '/u/paper-graph', [])).toBe(false)
  expect(isMine(req('/u/paper'), '/u/other', ['/u/paper'])).toBe(true)
  expect(isMine(req('/u/paper'), '/u/other', ['/u/paper-graph'])).toBe(false)
  expect(isMine(req('/u/paper'), '/u/other', ['/u/elsewhere'])).toBe(false)
})

test('a queued request for this project shows in the band, and load fills the box and marks it handled', async ($, on) => {
  const files: Record<string, string> = {
    [QUEUE]: [req('/work/paper', 'one'), req('/work/other', 'two')].map(r => JSON.stringify(r)).join('\n') + '\n',
  }
  const filled = engine(on, '/work/paper', files)

  const listed = await $.command.run({ command: 'repro-fixes' })
  expect(listed.text).toContain('claim-one')
  expect(listed.text).not.toContain('claim-two')

  const ui = await $.ui.mount({ plugin: 'repro', surface: 'terminal', component: 'AbovePrompt', props: PROPS })
  expect(await ui.find({ type: 'Text', text: /Failing claim: claim-one/ })).toBeDefined()
  expect(await ui.find({ key: 'fix:load' })).toBeDefined()
  expect(await ui.find({ key: 'fix:dismiss' })).toBeDefined()
  await ui.unmount()

  const loaded = await $.command.run({ command: 'repro-fixes', args: 'load' })
  expect(loaded.text).toContain('claim-one')
  expect(filled).toEqual(['fix one'])
  expect(JSON.parse(files[HANDLED] ?? '[]')).toEqual(['one'])

  const after = await $.command.run({ command: 'repro-fixes' })
  expect(after.text).toBe('No fix requests for this project.')
  expect((await band($)).some(text => /claim-/.test(text ?? ''))).toBe(false)
})

test('a request for another project never shows, while one for a project the session touched does', async ($, on) => {
  const files: Record<string, string> = {
    [QUEUE]: [req('/work/other', 'two'), req('/work/third', 'three')].map(r => JSON.stringify(r)).join('\n') + '\n',
    '/work/third/.results/ledger.jsonl': '{}',
    '/work/third/notes.md': 'x',
  }
  const filled = engine(on, '/work/paper', files)

  expect((await $.command.run({ command: 'repro-fixes' })).text).toBe('No fix requests for this project.')

  await $.tool.call({ tool: 'Read', file_path: '/work/third/notes.md' })
  const listed = await $.command.run({ command: 'repro-fixes' })
  expect(listed.text).toContain('claim-three')
  expect(listed.text).not.toContain('claim-two')
  expect((await band($)).some(text => /claim-two/.test(text ?? ''))).toBe(false)

  await $.command.run({ command: 'repro-fixes', args: 'load' })
  expect(filled).toEqual(['fix three'])
  expect((await $.command.run({ command: 'repro-fixes', args: 'load' })).text).toBe('No fix requests for this project.')
  expect(filled).toEqual(['fix three'])
  await $.command.run({ command: 'repro-status', args: 'auto' })
})
