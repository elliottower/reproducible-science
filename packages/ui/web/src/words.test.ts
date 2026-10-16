import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ASK_FIRST, issuePrompt, lineText, statusLines } from './format'
import type { Issue, Status } from './types'

/** Words the page never shows: a preregistration is called that, not a plan. */
const BANNED = /\bplans?\b/i

/** The text a source file can put on screen: its string literals and the text between JSX tags,
 * with comments removed first. Code identifiers (a `plans` field) are not text and stay. */
export function shownText(src: string): string[] {
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1')
  const strings = [...code.matchAll(/'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g)].map((m) => m[0])
  const jsx = [...code.matchAll(/>([^<>{}]*[A-Za-z][^<>{}]*)</g)].map((m) => m[1])
  return [...strings, ...jsx]
}

const SRC = join(__dirname)
const files = readdirSync(SRC).filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))

describe('words the page shows', () => {
  it.each(files)('%s says "preregistration", never "plan"', (f) => {
    const hits = shownText(readFileSync(join(SRC, f), 'utf8')).filter((t) => BANNED.test(t))
    expect(hits).toEqual([])
  })

  it('catches the word in a literal, a template and JSX text, and leaves identifiers alone', () => {
    expect(shownText("const a = 'Search plans'").some((t) => BANNED.test(t))).toBe(true)
    expect(shownText('const b = `${n} plans`').some((t) => BANNED.test(t))).toBe(true)
    expect(shownText('<th>Plan</th>').some((t) => BANNED.test(t))).toBe(true)
    expect(shownText('const plans = t.plans // the plans').some((t) => BANNED.test(t))).toBe(false)
  })

  it('holds for the status lines and every prompt the page builds', () => {
    const status: Status = {
      prereg: { state: 'read', plans: 2, frozen: 0, changed: 1, drafts: 1, amendments: 1, unknown: 1, ok: false },
      results: { state: 'read', runs: 3, sealed: 2, changed: 1, ok: false },
    }
    const ids = ['prereg-changed', 'prereg-pinned-changed', 'prereg-never-frozen', 'results-changed', 'citations-not-found', 'other']
    const said = [
      ...statusLines(status).map(lineText),
      ...statusLines(undefined).map(lineText),
      ASK_FIRST,
      ...ids.map((id) => issuePrompt({ id, tool: 'prereg', title: 't', note: 'n', fix: true, items: [] } as Issue, '/p')),
    ]
    expect(said.filter((t) => BANNED.test(t))).toEqual([])
    expect(lineText(statusLines(status)[1])).toBe('results: 2/3 runs sealed, 1 file changed after sealing')
  })
})
