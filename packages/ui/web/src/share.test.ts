import { execFileSync } from 'node:child_process'
import { describe, expect, it } from 'vitest'
import {
  auditPrompt, cloneInstructions, fixPrompt, NEVER_ACT, pagesPrompt, pagesSteps, sortRows, staticMessage, stepLog,
  type StepRow,
} from './format'
import { runFor, stepRow, type PageRun } from './reproduceTab'
import { search, searchIndex } from './search'
import type { Graph, Issue } from './types'

const row = (step: string, when: string, state: StepRow['state'], dur: number | null, cmd = `run ${step}`): StepRow =>
  ({ step, when, state, dur, cmd, detail: '' })

const ROWS = [
  row('b', '2026-10-15T13:20:00Z', 'ok', 1.2),
  row('a', '2026-10-15T13:19:00Z', 'changed', 0.09),
  row('c', 'now', 'run', null),
  row('d', '', 'none', null),
  row('e', '2026-10-15T13:21:00Z', 'err', 4.8),
]

describe('sorting the steps', () => {
  it('puts the running step first by last re-run, newest first, and never-run last', () => {
    expect(sortRows(ROWS, 'when', -1).map((r) => r.step)).toEqual(['c', 'e', 'b', 'a', 'd'])
    expect(sortRows(ROWS, 'when', 1).map((r) => r.step)).toEqual(['d', 'a', 'b', 'e', 'c'])
  })
  it('orders results running, changed, failed, reproduced, not re-run', () => {
    expect(sortRows(ROWS, 'state', 1).map((r) => r.state)).toEqual(['run', 'changed', 'err', 'ok', 'none'])
  })
  it('sorts durations as numbers, with untimed steps after every timed one', () => {
    expect(sortRows(ROWS, 'dur', 1).map((r) => r.step)).toEqual(['a', 'b', 'e', 'c', 'd'])
  })
  it('sorts by name and by command, both ways, and leaves its input alone', () => {
    const before = ROWS.map((r) => r.step)
    expect(sortRows(ROWS, 'step', 1).map((r) => r.step)).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(sortRows(ROWS, 'cmd', -1).map((r) => r.step)).toEqual(['e', 'd', 'c', 'b', 'a'])
    expect(ROWS.map((r) => r.step)).toEqual(before)
  })
})

type Step = NonNullable<Graph['tabs']>['reproduce']['steps'][number]
const step = (over: Partial<Step>): Step => ({
  id: 's', artifact: 'out', state: 'current', rerun_at: '2026-10-15T13:00:00Z', command: 'python3 make.py', causes: [],
  history: [{ ended_at: '2026-10-15T13:00:00Z', tool_version: '0.7', state: 'reproduced', bytes_identical: true, exit_code: 0, duration_seconds: 0.5, detail: '' }],
  ...over,
})
const pageRun = (over: Partial<PageRun>): PageRun => ({ run_id: 'r', pid: 1, only: ['s'], started_at: '2026-10-15T14:00:00Z', log: '', state: 'running', ...over })

describe('a step row', () => {
  it('reads Running while a page run covers the step, and Reproduced from its last re-run otherwise', () => {
    expect(stepRow(step({}), [pageRun({})]).state).toBe('run')
    expect(stepRow(step({}), [pageRun({ only: null })]).state).toBe('run')
    expect(stepRow(step({}), [pageRun({ only: ['other'] })])).toMatchObject({ state: 'ok', detail: 'bytes identical', dur: 0.5 })
  })
  it('folds what changed into the result', () => {
    const r = stepRow(step({ state: 'stale', causes: [{ cause: 'input_changed', artifact: 'x' }, { cause: 'output_changed', artifact: 'y' }, { cause: 'command_changed', artifact: 'y' }] }), [])
    expect([r.state, r.detail]).toEqual(['changed', '2 files'])
  })
  it('says interrupted when the page run ended with nothing recorded, until a re-run is recorded', () => {
    expect(stepRow(step({}), [pageRun({ state: 'interrupted' })]).state).toBe('int')
    expect(stepRow(step({ rerun_at: '2026-10-15T15:00:00Z' }), [pageRun({ state: 'interrupted' })]).state).toBe('ok')
  })
  it('reads a failed re-run as failed, with its exit code', () => {
    const failed = step({ state: 'stale', causes: [], history: [{ ended_at: '', tool_version: '', state: 'failed', bytes_identical: null, exit_code: 2, duration_seconds: 1, detail: '' }] })
    expect(stepRow({ ...failed, state: 'current' }, [])).toMatchObject({ state: 'err', detail: 'exit 2' })
  })
  it('finds the newest page run of a step', () => {
    expect(runFor([pageRun({ run_id: 'new', only: null }), pageRun({ run_id: 'old' })], 's')?.run_id).toBe('new')
  })
})

describe('a step log', () => {
  const log = [
    '/p/repro.yaml', '', '  re-ran 2 of 2', '',
    '  reproduced  alpha  bytes identical',
    '  changed     beta   output differs',
    '              on the recorded output of alpha',
    '                 total  6 then, 7 now, paper prints 6',
    '', '  1 reproduced, 1 changed',
  ].join('\n')
  it('keeps only the lines of that step', () => {
    expect(stepLog(log, 'beta', null).split('\n')).toEqual([
      '  changed     beta   output differs',
      '              on the recorded output of alpha',
      '                 total  6 then, 7 now, paper prints 6',
    ])
    expect(stepLog(log, 'alpha', null)).toBe('  reproduced  alpha  bytes identical')
  })
  it('is the whole log for a run of that step alone', () => {
    expect(stepLog(log, 'beta', ['beta'])).toBe(log)
  })
})

describe('the static export', () => {
  it('says what each server-only button would run, in one pattern', () => {
    expect(staticMessage('verify')).toBe("This static export can't run repro verify. Run it on the command line: repro verify")
    expect(staticMessage('step', 'body-claims')).toBe("This static export can't re-run steps. Run it on the command line: repro reproduce --only body-claims")
    expect(staticMessage('step', "it's a step")).toBe("This static export can't re-run steps. Run it on the command line: repro reproduce --only 'it'\\''s a step'")
    expect(staticMessage('all')).toBe("This static export can't re-run steps. Run it on the command line: repro reproduce")
    expect(staticMessage('file')).toBe("This static export doesn't include file contents. Open the live page on the command line: repro ui")
  })
})

const ISSUES: Issue[] = [
  { id: 'prereg-changed', tool: 'prereg', title: 'PREREG.md changed after it was frozen', note: 'The plan on disk is not the text that was frozen.', fix: true, items: [{ label: 'PREREG.md', open: { tab: 'prereg' } }] },
  { id: 'citations-not-found', tool: 'citations', title: '1 quotation not found in its source (fox2020)', note: 'The quote, the pinned file or the reading may be wrong.', fix: true, items: [{ label: 'fox:sleeps', open: { tab: 'citations' } }] },
]
const REMOTE = { clone: 'https://github.com/o/my paper.git', host: 'github.com', owner: 'o', name: 'my paper', subdir: "it's here" }

describe('prompts', () => {
  const prompts = {
    audit: auditPrompt('/work/my paper', 'paper/main.tex'),
    auditUnknown: auditPrompt(null, null),
    fix: fixPrompt(ISSUES, '/work/my paper'),
    pages: pagesPrompt(REMOTE, '/work/my paper'),
  }
  it.each(Object.entries(prompts))('%s: every paragraph is one line, and the last is the rule', (_, p) => {
    const paragraphs = p.split('\n\n')
    expect(paragraphs[paragraphs.length - 1]).toBe(NEVER_ACT)
    // The Pages prompt carries the workflow file, which is code, not prose.
    for (const para of paragraphs.filter((x) => !x.startsWith('name: repro pages'))) expect(para).not.toContain('\n')
  })
  it('fills the audit prompt from the project, and says "the manuscript" when it is not known', () => {
    expect(prompts.audit).toContain('Project: /work/my paper. Manuscript: paper/main.tex. Manifest: repro.yaml.')
    expect(prompts.auditUnknown).toContain('Project: this project. Manifest: repro.yaml.')
    expect(prompts.auditUnknown).toContain('read the manuscript and list')
  })
  it('lists every open issue in the fix prompt, with its items and note', () => {
    expect(prompts.fix).toContain('1. prereg: PREREG.md changed after it was frozen. Items: PREREG.md.')
    expect(prompts.fix).toContain('2. citations: 1 quotation not found')
    expect(prompts.fix).toContain('The quote, the pinned file or the reading may be wrong.')
    expect(prompts.fix).toMatch(/stop and ask me/)
  })
  it('never tells the agent to change a record outside an options sentence or the closing rule', () => {
    for (const p of [prompts.fix, prompts.pages]) {
      const body = p.slice(0, -NEVER_ACT.length).replace(/Options might include [^.]*\./g, '')
      const prose = body.split('\n').filter((l) => !/^(\s|name:|on:|permissions:|jobs:|- )/.test(l) && !/^\d\. Add this workflow/.test(l))
      for (const line of prose) {
        expect(line).not.toMatch(/\b(edit|re-?run|reseal|freeze|amend|re-?pin|restore|retire|delete|fix)\b/i)
      }
    }
  })
})

describe('share', () => {
  const sh = (script: string) => execFileSync('/bin/sh', ['-c', script], { encoding: 'utf8' })
  it('quotes the clone address and folder for the shell', () => {
    const lines = cloneInstructions(REMOTE, '/x').split('\n')
    expect(lines.slice(2)).toEqual(['pip install "reproducible-science[ui]"', 'repro ui'])
    const words = (line: string) => sh(`printf '%s\\0' ${line}`).split('\0').slice(0, -1)
    expect(words(lines[0])).toEqual(['git', 'clone', 'https://github.com/o/my paper.git'])
    expect(words(lines[1])).toEqual(['cd', "my paper/it's here"])
  })
  it('without a remote, starts from the project folder', () => {
    expect(cloneInstructions(null, '/a b')).toBe("cd '/a b'\npip install \"reproducible-science[ui]\"\nrepro ui")
  })
  it('names the real repository in the Pages steps, and placeholders off GitHub', () => {
    expect(pagesSteps(REMOTE)).toContain('gh api -X POST repos/o/my paper/pages -f build_type=workflow')
    expect(pagesSteps(REMOTE)).toContain('The page appears at o.github.io/my paper.')
    expect(pagesSteps({ ...REMOTE, host: 'gitlab.com' })).toContain('repos/<owner>/<repo>/pages')
    expect(pagesSteps(null)).toContain('A Pages site is public even when the repository is private.')
  })
})

describe('search', () => {
  const graph = {
    nodes: [{ id: 'results', type: 'artifact', path: 'out/results.json', group: 'g', ok: 1, fail: 0, stale: 0,
      claims: [{ id: 'total', where: 'Section 1', section: 'Section 1', text: 'The total is 6.', ok: true, stale: null, history: [], assertions: [] }] }],
    tabs: {
      citations: { sources: [{ file: 'claims/fox.yaml', citation: 'fox2020', url: '', local: '', sha256: '', pinned: 1, cited_in: [], bib: { title: 'Foxes' }, link: '', doi_link: '',
        statements: [{ id: 'jumps', statement: '', notes: '', quotes: [{ exact: 'The quick brown fox', section: '' }] }] }] },
      reproduce: { steps: [{ id: 'make-total', artifact: 'results', state: 'current', rerun_at: null, command: 'python3 make.py', causes: [] }], reruns: [] },
    },
  } as unknown as Graph
  const index = searchIndex(graph)
  it('jumps to claims, quotes, sources, files and steps', () => {
    expect(new Set(search(index, 'total').map((h) => h.jump.kind))).toEqual(new Set(['claim', 'step']))
    expect(search(index, 'quick fox')[0].jump).toEqual({ kind: 'quote', file: 'claims/fox.yaml', statement: 'jumps', index: 0 })
    expect(search(index, 'foxes')[0].jump).toEqual({ kind: 'source', file: 'claims/fox.yaml' })
    expect(search(index, 'results.json')[0].jump).toEqual({ kind: 'file', id: 'results' })
    expect(search(index, 'make-total')[0].jump).toEqual({ kind: 'step', id: 'make-total' })
    expect(search(index, 'total')[0].jump).toEqual({ kind: 'claim', id: 'total' })
    expect(search(index, '   ')).toEqual([])
  })
})
