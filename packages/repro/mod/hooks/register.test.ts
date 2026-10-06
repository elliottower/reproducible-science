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
function project(on: On, files: Record<string, string>, says: (argv: readonly string[]) => string | null = () => '') {
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
    if (says(e.argv) === null) {
      throw new Error(`$.process.run(${e.argv[0]}) aborted: still running after 60000ms`)
    }

    return {
      value: { exitCode: 0, stdout: says(e.argv) ?? '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
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

test('an edit to a frozen amendment is refused and never reaches the tool', async ($, on) => {
  const ran = project(on, {
    [`${CWD}/PREREG.md`]: DRAFT_PLAN,
    [`${CWD}/PREREG_AMENDMENT_1.md`]: '# Amendment 1\n\n## Reason\n\nA second cohort.\n',
    [`${CWD}/.prereg/PREREG.md.json`]: '{}',
    [`${CWD}/.prereg/PREREG_AMENDMENT_1.md.json`]: '{}',
  })

  for (const name of ['PREREG_AMENDMENT_1.md', 'PREREG.md']) {
    for (const tool of ['Edit', 'Write'] as const) {
      const answer = await $.tool.call(
        tool === 'Edit'
          ? { tool, file_path: `${CWD}/${name}`, old_string: 'A second cohort.', new_string: 'The data suggested it.' }
          : { tool, file_path: `${CWD}/${name}`, content: 'rewritten' },
      )

      expect(answer.deny).toContain('freeze record')
      expect(answer.deny).toContain(`.prereg/${name}.json`)
      expect(answer.deny).toContain('prereg amend')
    }
  }
  expect(ran).toEqual([])
})

test('an amendment still in draft can be edited beside a frozen plan', async ($, on) => {
  const ran = project(on, {
    [`${CWD}/PREREG.md`]: DRAFT_PLAN,
    [`${CWD}/PREREG_AMENDMENT_1.md`]: '# Amendment 1\n\n## Reason\n\n_Why the plan changes._\n',
    [`${CWD}/.prereg/PREREG.md.json`]: '{}',
  })

  const answer = await $.tool.call({
    tool: 'Edit',
    file_path: `${CWD}/PREREG_AMENDMENT_1.md`,
    old_string: '_Why the plan changes._',
    new_string: 'A second cohort.',
  })

  expect(answer.deny).toBeUndefined()
  expect(ran).toEqual(['Edit'])
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
  expect(after.text).toContain('pinned ·')
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
  on('tool.register', () => ({ value: { tool: 'mcp__repro__set_project' } }))

  const answer = await $.tool.call({ tool: 'mcp__repro__set_project', path: '/elsewhere/study' })

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
    const ui = await $.ui.mount({ plugin: 'repro', surface, component: 'Pane', requestId: 'repro-projects', props: {} as never })
    expect(await ui.find({ key: 'project:alpha' })).toBeDefined()
    expect(await ui.find({ key: 'project:beta' })).toBeDefined()
    expect(await ui.find({ key: 'project:notes' })).toBeUndefined()

    await ui.press({ key: 'project:beta' })
    const after = await $.command.run({ command: 'repro-status', args: '' })
    expect(after.text).toContain('beta ·')
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
    const ui = await $.ui.mount({ plugin: 'repro', surface, component: 'Pane', requestId: 'repro-projects', props: {} as never })
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

test('the readout gives the project, then plan, inputs and ledger, in that order', async ($, on) => {
  project(on, { '/work/study/.results/ledger.jsonl': '{}', '/work/study/PREREG.md': DRAFT_PLAN }, argv =>
    argv[0] === 'results' ? 'chain intact: 5 events, anchored\n' : 'not frozen   /work/study/PREREG.md\n',
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'study' })

  expect(shown.text).toContain('study · prereg: 0/1 frozen · results: 0 runs, 0 claims bound')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a check that times out marks its own field and the rest of the line still shows', async ($, on) => {
  project(on, { '/work/study/.results/ledger.jsonl': '{}', '/work/study/PREREG.md': DRAFT_PLAN }, argv =>
    argv[0] === 'prereg' ? null : 'chain intact: 5 events, anchored\n',
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'study' })

  expect(shown.text).toContain('study · prereg: not read (timed out) · results: 0 runs, 0 claims bound')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('quotations pinned in a claims folder below the top of the project are counted', async ($, on) => {
  project(on, { '/work/study/PREREG.md': DRAFT_PLAN }, argv =>
    argv[0] === 'find' ? './paper/prior_art/claims\n' : argv[0] === 'grep' ? '40\n23\n' : '',
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'study' })

  expect(shown.text).toContain('citations: 63 pinned, not verified')
  expect(spawned.some(call => call.includes('paper/prior_art/claims') && call.includes('grep'))).toBe(true)
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('the status command never runs the quotation check, and the verify command records its count', async ($, on) => {
  project(on, { '/work/study/PREREG.md': DRAFT_PLAN }, argv =>
    argv[0] === 'find'
      ? './claims\n'
      : argv[0] === 'grep'
        ? '63\n'
        : argv[0] === 'citations' && argv[1] === 'verify'
          ? '63 quotes\n\n  found              61\n  not found           2\n'
          : '',
  )
  const verifies = () => spawned.filter(call => call.includes('citations') && call.includes('verify')).length

  const shown = await $.command.run({ command: 'repro-status', args: 'study' })
  expect(shown.text).toContain('citations: 63 pinned, not verified')
  expect(verifies()).toBe(0)

  const verified = await $.command.run({ command: 'repro-verify', args: '' })
  expect(verifies()).toBe(1)
  expect(verified.text).toContain('citations: 61/63 quotes found')
  expect(verified.text).toContain('not found           2')

  const after = await $.command.run({ command: 'repro-status', args: '' })
  expect(after.text).toContain('citations: 61/63 quotes found')
  expect(verifies()).toBe(1)
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a plan in a subfolder is counted beside the one at the top', async ($, on) => {
  const top = 'unchanged    /work/study/PREREG.md\n  timestamp  none.\n'
  const below = top + 'unchanged    /work/study/artifact_survey/PREREG.md\n'
  let checks = 0
  project(on, { '/work/study/.results/ledger.jsonl': '' }, argv =>
    argv[0] === 'find' && argv.includes('PREREG.md')
      ? './artifact_survey/PREREG.md\n'
      : argv[0] === 'prereg'
        ? checks++ === 0
          ? top
          : below
        : '',
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'study' })
  expect(shown.text).toContain('prereg: 2/2 frozen')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a plan frozen whole, its amendment and its log read as two frozen files and no change', async ($, on) => {
  const chain =
    'unchanged    /work/study/PREREG.md  frozen 2026-10-06  nothing run\n' +
    '  timestamp  owed. `prereg timestamp` completes it.\n' +
    'unchanged    /work/study/PREREG_AMENDMENT_1.md  frozen 2026-10-07  results seen\n' +
    '  amends     PREREG.md\n' +
    '  written after results were seen\n' +
    'log          /work/study/PREREG.log  2 entries, chain intact\n'
  let listing = chain
  project(on, { '/work/study/.results/ledger.jsonl': '' }, argv => (argv[0] === 'prereg' ? listing : ''))

  const clean = await $.command.run({ command: 'repro-status', args: 'study' })
  expect(clean.text).toContain('prereg: 2/2 frozen')
  expect(clean.text).not.toContain('changed')

  listing = chain.replace('log          /work/study/PREREG.log  2 entries, chain intact', 'LOG ALTERED  /work/study/PREREG.log')
  const altered = await $.command.run({ command: 'repro-status', args: '' })
  expect(altered.text).toContain('prereg: 1 changed')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('registrations frozen by a commit line count as plans, and only an edited one is a change', async ($, on) => {
  const intact =
    '\nregistrations frozen by a commit line:\n' +
    'unchanged    PREREGISTRATION_AMENDMENT_2.md  at 12ea0ed\n' +
    'appended     PREREGISTRATION_AMENDMENT_5.md  at fbc7d33\n' +
    '  8 lines added after the frozen text\n' +
    'pending      PREREGISTRATION_AMENDMENT_3.md\n'
  let listing = intact
  project(on, { '/work/study/.results/ledger.jsonl': '' }, argv => (argv[0] === 'prereg' ? listing : ''))

  const clean = await $.command.run({ command: 'repro-status', args: 'study' })
  expect(clean.text).toContain('prereg: 2/3 frozen')
  expect(clean.text).not.toContain('changed')

  listing = intact + 'CHANGED      PREREGISTRATION.md  at b96d10a\n  23 lines added, 3 removed\n'
  const edited = await $.command.run({ command: 'repro-status', args: '' })
  expect(edited.text).toContain('prereg: 1 changed')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

/** What `repro verify` prints, cut to the lines the mod reads: the assertions, the counts, the policy. */
const assertions = (lines: string[], counts: string, policy = 'FAILED  (1 errors, 0 warnings)') =>
  `/work/trial/repro.yaml\n\n${lines.map(line => `  ${line}\n`).join('')}\n  ${counts}\n  policy publication: ${policy}\n`

/** A project at /work/trial with a manifest, where `repro verify` prints `printed` (null: it times out). */
function trial(on: On, printed: string | null, files: Record<string, string> = { '/work/trial/repro.yaml': 'x' }) {
  project(on, { '/work/trial/PREREG.md': DRAFT_PLAN, ...files }, argv => (argv[0] === 'repro' ? printed : ''))
  spawned.length = 0
}

test('a manifest whose assertions all verify adds a fourth field, as verified over all', async ($, on) => {
  trial(
    on,
    assertions(
      ['ok    corpus-size  quote      [short]', 'ok    corpus-size  metric   /corpus/quotations = 2364'],
      '34 verified',
      'passed  (0 errors, 0 warnings)',
    ),
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'trial' })

  expect(shown.text).toContain('citations: none pinned · repro: 34/34 checks verified')
  expect(spawned.some(call => call.includes('"repro","verify"') && call.includes('/work/trial'))).toBe(true)
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('checks are a fraction when every assertion is printed, even when one did not verify', async ($, on) => {
  trial(
    on,
    assertions(
      [
        'ok    sensors      quote    ',
        'ok    sensors      metric   /sensors = 12',
        'ok    mean-offset  quote    ',
        'MISS  mean-offset  metric   /mean_offset: reported 0.34, found 0.43',
        'ok    offset-sd    quote    ',
        'ok    offset-sd    metric   /offset_sd = 0.41',
      ],
      '1 mismatch, 5 verified',
    ),
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'trial' })

  expect(shown.text).toContain('· repro: 5/6 checks verified')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('assertions that did not verify are counted under the tool’s own words, the most serious first', async ($, on) => {
  trial(
    on,
    assertions(
      ['MISS  effect-size  correspondence effect-delta: manuscript 0.055, run 0.0453'],
      '1 mismatch, 2 not_found, 1 not_offered, 1 unchecked, 30 verified',
    ),
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'trial' })

  expect(shown.text).toContain('· repro: 1 mismatch, 2 not found, 1 unchecked, 1 not offered, 30 verified')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a pinned file that changed keeps the field from reading as all verified', async ($, on) => {
  trial(
    on,
    assertions(['BROKEN PIN  paper: pinned 978f5e1fd04a, found 2d9f4f51d553'], '3 verified'),
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'trial' })

  expect(shown.text).toContain('· repro: 1 broken pin, 3 verified')
  expect(shown.text).not.toContain('3/3')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a project with no manifest says so in a fourth field and the check is never run', async ($, on) => {
  trial(on, assertions([], '34 verified', 'passed  (0 errors, 0 warnings)'), {})

  const shown = await $.command.run({ command: 'repro-status', args: 'trial' })
  const line = (shown.text ?? '').split('\n').at(-1) ?? ''

  expect(line.split(' · ')).toEqual([
    'trial',
    'prereg: none drafted',
    'results: no ledger',
    'citations: none pinned',
    'repro: no manifest',
  ])
  expect(spawned.filter(call => call.includes('"repro"')).length).toBe(0)
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a manifest check that times out marks its own field and the others still show', async ($, on) => {
  trial(on, null)

  const shown = await $.command.run({ command: 'repro-status', args: 'trial' })

  expect(shown.text).toContain('results: no ledger · citations: none pinned · repro: not read (timed out)')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('a manifest that does not load is said to be unreadable, not verified', async ($, on) => {
  trial(on, '/work/trial/repro.yaml: claims.0.id: Field required\n')

  const shown = await $.command.run({ command: 'repro-status', args: 'trial' })

  expect(shown.text).toContain('· repro: manifest unreadable')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})

test('runs are a fraction sealed, and runs named as tests are left out of the row', async ($, on) => {
  const ledger =
    '{"event":"init","seq":0}\n' +
    '{"event":"run","seq":1,"run_id":"smoke_s1_search"}\n' +
    '{"event":"run","seq":2,"run_id":"prefreeze_ledger_proof"}\n' +
    '{"event":"run","seq":3,"run_id":"early"}\n' +
    '{"event":"seal","seq":4,"files":[{"path":"a.csv"},{"path":"run.py"}]}\n' +
    '{"event":"run","seq":5,"run_id":"s1_search"}\n' +
    '{"event":"run","seq":6,"run_id":"s2_eligibility"}\n' +
    '{"event":"claim","seq":7,"run_id":"s1_search"}\n'
  project(on, { '/work/study/.results/ledger.jsonl': ledger }, argv =>
    argv[0] === 'results' ? 'chain intact: 8 events, anchored\n' : '',
  )

  const shown = await $.command.run({ command: 'repro-status', args: 'study' })

  expect(shown.text).toContain('results: 2/3 runs sealed, 1 claim bound')
  expect(shown.text).not.toContain('test run')
  await $.command.run({ command: 'repro-status', args: 'auto' })
})
