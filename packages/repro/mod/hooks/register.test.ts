import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

const CWD = '/work/study'
const FROZEN_PLAN = '# Plan\n\n**Plan sha256:** `' + 'a'.repeat(64) + '`\n\nH1. ...\n'
const DRAFT_PLAN = '# Plan\n\nH1. ...\n'

/** Every scroll the mod asked for, as JSON. */
const revealed: string[] = []

/** Every `$.process.run` the mod made, as JSON, so a test can read where a check ran. */
const spawned: string[] = []

/** Stands for the engine beneath the mod: a project whose files are `files`, and a tool that always runs. */
function project(on: On, files: Record<string, string>) {
  const ran: string[] = []
  on('session.cwd', () => ({ value: CWD }))
  on('fs.exists', (_$, e) => ({
    value: e.path in files || Object.keys(files).some(f => f.startsWith(`${e.path}/`)),
  }))
  on('fs.read', (_$, e) => ({ value: files[e.path] ?? '' }))
  on('ui.open', () => ({ value: { isOpen: true } as never }))
  on('ui.close', () => ({ value: undefined as never }))
  on('ui.focus', () => ({ value: undefined as never }))
  on('ui.status', () => ({ value: undefined as never }))
  on('ui.scroll', (_$, e) => {
    revealed.push(JSON.stringify(e))

    return { value: undefined as never }
  })
  on('fs.list', (_$, e) => {
    const under = `${e.path}/`
    const names = new Set(
      Object.keys(files).filter(f => f.startsWith(under)).map(f => f.slice(under.length).split('/')[0] as string),
    )

    return { value: [...names].map(name => ({ name, kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false })) }
  })
  on('process.run', (_$, e) => {
    spawned.push(JSON.stringify(e))

    return {
      value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
    }
  })
  on('tool.call', (_$, e) => {
    ran.push(String(e.tool))

    return { result: {} as never }
  })

  return ran
}

test('an edit to a frozen plan is refused and never reaches the tool', async ($, on) => {
  const ran = project(on, { [`${CWD}/PREREG.md`]: FROZEN_PLAN })

  const answer = await $.tool.call({
    tool: 'Edit',
    file_path: `${CWD}/PREREG.md`,
    old_string: 'H1. ...',
    new_string: 'H1. something the data suggested',
  })

  expect(answer.deny).toContain('frozen registration')
  expect(answer.deny).toContain('prereg log')
  expect(ran).toEqual([])
})

test('a plan that is not frozen can be edited', async ($, on) => {
  const ran = project(on, { [`${CWD}/PREREG.md`]: DRAFT_PLAN })

  const answer = await $.tool.call({
    tool: 'Edit',
    file_path: `${CWD}/PREREG.md`,
    old_string: 'H1. ...',
    new_string: 'H1. a sharper hypothesis',
  })

  expect(answer.deny).toBeUndefined()
  expect(ran).toEqual(['Edit'])
})

test('a manuscript edited with no ledger above it is noted once, and the edit still lands', async ($, on) => {
  const ran = project(on, { [`${CWD}/paper/main.tex`]: 'x' })
  const edit = { tool: 'Edit', file_path: `${CWD}/paper/main.tex`, old_string: 'x', new_string: '0.42' } as const

  const first = await $.tool.call(edit)
  const second = await $.tool.call(edit)

  expect(first.deny).toBeUndefined()
  expect((first.context ?? []).join(' ')).toContain('no .results/ ledger')
  expect(second.context ?? []).toEqual([])
  expect(ran).toEqual(['Edit', 'Edit'])
})

test('a manuscript with a ledger above it draws no note', async ($, on) => {
  project(on, {
    [`${CWD}/paper/other.tex`]: 'x',
    [`${CWD}/.results/ledger.jsonl`]: '{}',
  })

  const answer = await $.tool.call({
    tool: 'Edit',
    file_path: `${CWD}/paper/other.tex`,
    old_string: 'x',
    new_string: '0.42',
  })

  expect(answer.context ?? []).toEqual([])
})

test('a downloaded paper is followed by a note naming the address to record', async ($, on) => {
  project(on, {})

  const answer = await $.tool.call({
    tool: 'Bash',
    command: 'curl -sL https://arxiv.org/pdf/2211.00593 -o reference/wang_2023_ioi.pdf',
  })
  const note = (answer.context ?? []).join(' ')

  expect(note).toContain('https://arxiv.org/pdf/2211.00593')
  expect(note).toContain('reference/wang_2023_ioi.pdf')
  expect(note).toContain('url:')
})

test('a command that downloads nothing draws no note', async ($, on) => {
  project(on, {})

  const answer = await $.tool.call({ tool: 'Bash', command: 'git status' })

  expect(answer.context ?? []).toEqual([])
})

test('the project is read off the files a session touches, not the folder it started in', async ($, on) => {
  project(on, {
    '/elsewhere/study/.results/ledger.jsonl': '{}',
    '/elsewhere/study/paper/main.tex': 'x',
  })
  spawned.length = 0

  await $.tool.call({ tool: 'Read', file_path: '/elsewhere/study/paper/main.tex' })
  await $.command.run({ command: 'repro-status', args: '' })

  expect(spawned.length).toBeGreaterThan(0)
  expect(spawned.every(call => call.includes('/elsewhere/study'))).toBe(true)
})

test('a project named by the person stays the working project when other files are touched', async ($, on) => {
  project(on, {
    '/work/pinned/.results/ledger.jsonl': '{}',
    '/elsewhere/study/.results/ledger.jsonl': '{}',
    '/elsewhere/study/paper/main.tex': 'x',
  })

  const set = await $.command.run({ command: 'repro-status', args: 'pinned' })
  await $.tool.call({ tool: 'Read', file_path: '/elsewhere/study/paper/main.tex' })
  spawned.length = 0
  const after = await $.command.run({ command: 'repro-status', args: '' })

  expect(set.text).toContain('Working project set to /work/pinned')
  expect(after.text).toContain('pinned:')
  expect(spawned.every(call => call.includes('/work/pinned'))).toBe(true)
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a project is set by its number in the list or by part of its name', async ($, on) => {
  project(on, {
    '/work/alpha/.results/ledger.jsonl': '{}',
    '/work/beta-one/claims/a.yaml': 'x',
    '/work/beta-two/claims/a.yaml': 'x',
    '/work/notes/todo.md': 'x',
  })
  await $.command.run({ command: 'repro-status', args: 'auto' })

  const listed = await $.command.run({ command: 'repro-status', args: 'list' })
  expect(listed.text).toContain('3 research projects')
  expect(listed.text).toContain(' 1  alpha')
  expect(listed.text).not.toContain('notes')

  expect((await $.command.run({ command: 'repro-status', args: '1' })).text).toContain('set to /work/alpha')
  expect((await $.command.run({ command: 'repro-status', args: 'two' })).text).toContain('set to /work/beta-two')
  expect((await $.command.run({ command: 'repro-status', args: 'beta' })).text).toContain('matches 2 projects')
  expect((await $.command.run({ command: 'repro-status', args: 'zzz' })).text).toContain('No research project matches')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('the model can declare the project it is working on', async ($, on) => {
  project(on, { '/elsewhere/study/.results/ledger.jsonl': '{}' })
  on('tool.register', () => ({ value: { tool: 'mcp__repro-gates__set_project' } }))

  const answer = await $.tool.call({ tool: 'mcp__repro-gates__set_project', path: '/elsewhere/study' })

  expect(String(answer.result)).toContain('Working project set to /elsewhere/study')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('the picker draws one button per project, and picking one makes it the working project', async ($, on) => {
  project(on, {
    '/work/alpha/.results/ledger.jsonl': '{}',
    '/work/beta/claims/a.yaml': 'x',
    '/work/notes/todo.md': 'x',
  })
  await $.command.run({ command: 'repro-status', args: 'auto' })
  await $.command.run({ command: 'repro-status', args: 'pick' })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'repro-gates', surface, component: 'Pane', requestId: 'repro-projects', props: {} as never })
    expect(await ui.find({ key: 'project:alpha' })).toBeDefined()
    expect(await ui.find({ key: 'project:beta' })).toBeDefined()
    expect(await ui.find({ key: 'project:notes' })).toBeUndefined()

    await ui.press({ key: 'project:beta' })
    const after = await $.command.run({ command: 'repro-status', args: '' })
    expect(after.text).toContain('beta:')
    await $.command.run({ command: 'repro-status', args: 'auto' })
    await ui.unmount()
  }
})

test('the picker draws only a window of the list, so the tree always fits the pane', async ($, on) => {
  const files: Record<string, string> = {}
  for (let n = 1; n <= 20; n += 1) {
    files[`/work/study${String(n).padStart(2, '0')}/.results/ledger.jsonl`] = '{}'
  }
  project(on, files)
  await $.command.run({ command: 'repro-status', args: 'auto' })
  await $.command.run({ command: 'repro-status', args: 'pick' })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'repro-gates', surface, component: 'Pane', requestId: 'repro-projects', props: {} as never })
    expect(await ui.find({ key: 'project:study01' })).toBeDefined()
    expect(await ui.find({ key: 'project:study08' })).toBeDefined()
    expect(await ui.find({ key: 'project:study09' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /1–8 of 20/ })).toBeDefined()

    // The person walks the ring to the last line, then presses down: the engine asks the ring
    // to wrap to the first line, and the window slides by one instead.
    const walk = (n: number) =>
      $.ui.focus({ requestId: 'repro-projects', key: `project:study${String(n).padStart(2, '0')}`, origin: { kind: 'person' } } as never)
    for (let n = 1; n <= 8; n += 1) {
      await walk(n)
    }
    expect((await ui.find({ type: 'Text', text: /of 20/ }))?.text).toContain('1–8 of 20')
    await walk(1)
    expect((await ui.find({ type: 'Text', text: /of 20/ }))?.text).toContain('2–9 of 20')
    await walk(2)
    expect((await ui.find({ type: 'Text', text: /of 20/ }))?.text).toContain('3–10 of 20')
    await $.command.run({ command: 'repro-status', args: 'pick' })
    await ui.unmount()
  }
})
