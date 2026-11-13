import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, realpathSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ASK_FIRST, issuePrompt, lineText, reproduceCommand, shellQuote, statusLine, statusLines, terminalCommand } from './format'
import type { Issue, Status } from './types'

/** What a POSIX shell makes of `script`. */
const sh = (script: string) => execFileSync('/bin/sh', ['-c', script], { encoding: 'utf8' })
/** Each word the shell passes on from `quoted`, separated by NUL so a newline inside one survives. */
const words = (quoted: string) => sh(`printf '%s\\0' ${quoted}`).split('\0').slice(0, -1)

const NASTY = [
  'plain',
  'with space',
  "it's",
  'both "double" and \'single\'',
  'a;b',
  'x && echo injected',
  '$(echo injected)',
  '`echo injected`',
  '$HOME',
  'tab\there',
  'line\nbreak',
  '*',
  '',
  "''",
  '-n',
]

describe('shellQuote', () => {
  it.each(NASTY)('passes %j to the shell as one word, unexpanded', (s) => {
    expect(words(shellQuote(s))).toEqual([s])
  })

  it('leaves a word with nothing special in it bare', () => {
    expect(shellQuote('repro-ui_v1.2/path:x=y+z')).toBe('repro-ui_v1.2/path:x=y+z')
  })
})

describe('terminalCommand', () => {
  it.each(["it's a dir", 'a;b', '$(echo injected)', 'x && echo injected', '`echo injected`'])(
    'changes into a folder named %j and runs the command there',
    (name) => {
      const root = mkdtempSync(join(tmpdir(), 'repro ui '))
      try {
        const dir = join(root, name)
        mkdirSync(dir)
        expect(sh(terminalCommand(dir, 'pwd -P')).trim()).toBe(realpathSync(dir))
      } finally {
        rmSync(root, { recursive: true, force: true })
      }
    },
  )

  it('is the command alone when there is no folder', () => {
    expect(terminalCommand(undefined, 'repro verify')).toBe('repro verify')
  })
})

describe('reproduceCommand', () => {
  it('passes each step id to --only as one word', () => {
    const ids = ['plain', 'with space', "it's", '$(echo injected)', 'a;b']
    const cmd = reproduceCommand(undefined, ids)
    expect(cmd.startsWith('repro reproduce ')).toBe(true)
    expect(words(cmd.slice('repro reproduce '.length))).toEqual(ids.flatMap((id) => ['--only', id]))
  })

  it('names no step to run every step', () => {
    expect(reproduceCommand('/p', null)).toBe('cd /p && repro reproduce')
  })
})

const APPROVED: Status = {
  prereg: { state: 'none', ok: null },
  results: { state: 'read', runs: 72, sealed: 72, changed: 0, ok: true },
  citations: { state: 'read', quotes: 293, found: 293, not_found: 0, ok: true },
  claims: { state: 'read', total: 531, verified: 531, ok: true },
  repro: { state: 'read', steps: 20, current: 18, changed: 2, never: 0, last_at: '2026-10-15T12:00:00Z', ok: false },
}

describe('status lines', () => {
  it('reads as approved, in the order prereg, results, citations, claims, repro', () => {
    expect(statusLines(APPROVED).map(lineText)).toEqual([
      'prereg: none drafted  →  prereg new',
      'results: 72/72 runs sealed',
      'citations: 293/293 quotes verified',
      'claims: 531/531 verified',
      'repro: 18/20 reproduced, 2 changed since 15 Oct  →  repro reproduce',
    ])
  })

  it('says what failed in the same shape, and colours it', () => {
    const failing: Status = {
      prereg: { state: 'read', plans: 2, frozen: 1, changed: 1, drafts: 0, amendments: 0, ok: false },
      results: { state: 'read', runs: 72, sealed: 70, changed: 3, ok: false },
      citations: { state: 'read', quotes: 1293, found: 1292, not_found: 1, ok: false },
      claims: { state: 'read', total: 531, verified: 528, ok: false },
      repro: { state: 'read', steps: 20, current: 20, changed: 0, never: 0, last_at: null, ok: true },
    }
    expect(statusLines(failing).map(lineText)).toEqual([
      'prereg: 1/2 frozen, 1 changed since frozen',
      'results: 70/72 runs sealed, 3 files changed after sealing',
      'citations: 1,292/1,293 quotes verified, 1 not found',
      'claims: 528/531 verified',
      'repro: 20/20 reproduced',
    ])
    expect(statusLines(failing).map((l) => l.tone)).toEqual(['bad', 'bad', 'bad', 'bad', 'good'])
  })

  it('says "changed", never "stale", and counts never-re-run steps apart', () => {
    const l = statusLine('repro', { repro: { state: 'read', steps: 5, current: 2, changed: 1, never: 2, last_at: null, ok: false } })
    expect(lineText(l)).toBe('repro: 2/5 reproduced, 1 changed, 2 never re-run  →  repro reproduce')
    expect(lineText(l)).not.toMatch(/stale/)
  })

  it('names the command that starts each record a project does not keep', () => {
    expect(statusLines({}).map(lineText)).toEqual([
      'prereg: none drafted  →  prereg new',
      'results: no ledger  →  results init',
      'citations: none pinned  →  citations pin',
      'claims: no claims declared',
      'repro: no rebuild steps declared',
    ])
  })

  it('drops the bound-claims count from the results line', () => {
    const l = statusLine('results', { results: { state: 'read', runs: 3, sealed: 3, changed: 0, ok: true } })
    expect(lineText(l)).toBe('results: 3/3 runs sealed')
  })

  it('counts a registration naming no commit held here as a problem', () => {
    const l = statusLine('prereg', { prereg: { state: 'read', plans: 2, frozen: 1, changed: 0, drafts: 0, amendments: 0, unknown: 1, ok: false } })
    expect(lineText(l)).toBe('prereg: 1/2 frozen, 1 naming no commit held here')
    expect(l.tone).toBe('bad')
  })

  it('asks for a freeze, not a new preregistration, when one is drafted and not frozen', () => {
    const l = statusLine('prereg', { prereg: { state: 'read', plans: 1, frozen: 0, changed: 0, drafts: 1, amendments: 0, ok: false } })
    expect(lineText(l)).toBe('prereg: 0/1 frozen  →  prereg freeze')
    expect(l.tone).toBe('warn')
  })
})

/** Verbs a prompt may never open a sentence with: the prompt asks, it does not instruct. */
const ACTS = /^(please\s+)?(edit|run|re-?run|seal|reseal|freeze|amend|re-?pin|commit|log|restore|record|correct|drop|retire|pin|delete|change|fix|update|write)\b/i

const ROWS: Issue[] = [
  'prereg-changed', 'prereg-pinned-changed', 'results-changed', 'results-missing',
  'citations-not-found', 'citations-pin', 'something-else',
].map((id) => ({
  id, tool: id.split('-')[0] as Issue['tool'], title: `a title for ${id}`, note: 'A note.', fix: true,
  items: [{ label: 'paper/x.json', open: { tab: 'results' } }],
}))

describe('issue prompts', () => {
  it.each(ROWS)('asks the agent to look, lay out options and stop, never to act ($id)', (row) => {
    const prompt = issuePrompt(row, '/work/my paper')
    expect(prompt).toContain('In /work/my paper,')
    expect(prompt).toContain(row.title)
    expect(prompt).toContain('Items: paper/x.json.')
    for (const para of prompt.split('\n\n')) expect(para).not.toContain('\n')
    expect(prompt.endsWith(ASK_FIRST)).toBe(true)
    // Every sentence, except the closing one that forbids acting, opens on something other
    // than an instruction to change a record.
    const body = prompt.slice(0, -ASK_FIRST.length)
    const sentences = body.split(/\n|(?<=[.;:])\s+/).map((x) => x.replace(/^[-\s]+/, '')).filter(Boolean)
    for (const s of sentences) expect(s).not.toMatch(ACTS)
    // Nowhere outside the options sentence does a verb that changes a record appear, whether a
    // sentence opens on it or it sits mid-sentence ("Then restore the frozen text").
    for (const s of sentences.filter((x) => !x.startsWith('Options might include'))) {
      expect(s).not.toMatch(/\b(edit|re-?run|seal|reseal|freeze|amend|re-?pin|restore|retire|delete|fix|log)\b/i)
    }
    expect(prompt).toContain(row.note)
    // Options are named only as options, in the one sentence that says so.
    for (const s of sentences.filter((x) => /\b(amendment|restoring|re-?pinning|recording)\b/.test(x))) {
      expect(s).toMatch(/^Options might include/)
    }
  })

  it('ends by asking before anything is changed', () => {
    expect(ASK_FIRST).toMatch(/stop and ask me/)
    expect(ASK_FIRST.endsWith('Do not change any file or record — no edit, freeze, amend, log, seal, pin, re-run or commit — until I choose.')).toBe(true)
  })

  it('lists at most twenty items and says how many more', () => {
    const row = { ...ROWS[2], items: Array.from({ length: 25 }, (_, i) => ({ label: `f${i}`, open: { tab: 'results' as const } })) }
    const prompt = issuePrompt(row, null)
    expect(prompt).toContain('; f19; and 5 more.')
    expect(prompt).not.toContain('f20')
    expect(prompt.startsWith('In this project,')).toBe(true)
  })
})
