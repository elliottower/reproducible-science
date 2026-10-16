import { describe, expect, it } from 'vitest'
import { arrange, CARDS_SHOWN, claimsLine, type Project } from './drawer'

const p = (name: string, over: Partial<Project> = {}): Project => ({
  path: `/w/${name}`, name, title: null, opened_at: '2026-10-01T00:00:00+00:00', current: false, available: true, claims: null, ...over,
})

const LIST = [
  p('old', { opened_at: '2026-09-01T00:00:00+00:00' }),
  p('here', { opened_at: '2026-10-10T00:00:00+00:00', current: true, title: 'Reproducible Science' }),
  p('new', { opened_at: '2026-10-14T00:00:00+00:00' }),
  p('newest', { opened_at: '2026-10-15T00:00:00+00:00' }),
]

describe('the drawer', () => {
  it('lists every project newest opened first, the viewed one in its place', () => {
    expect(arrange(LIST, '').map((x) => x.name)).toEqual(['newest', 'new', 'here', 'old'])
  })
  it('searches titles, names and folders, every word, across all projects', () => {
    expect(arrange(LIST, 'reproducible').map((x) => x.name)).toEqual(['here'])
    expect(arrange(LIST, 'w new').map((x) => x.name)).toEqual(['newest', 'new'])
    expect(arrange(LIST, 'nothing')).toEqual([])
  })
  it('shows six cards before View all', () => {
    expect(CARDS_SHOWN).toBe(6)
  })
  it('says the claims as of the last check, or nothing when never checked', () => {
    expect(claimsLine(p('a', { claims: { verified: 531, total: 531 } }))).toBe('claims: 531/531 verified')
    expect(claimsLine(p('a', { claims: { verified: 1062, total: 1100 } }))).toBe('claims: 1,062/1,100 verified')
    expect(claimsLine(p('a'))).toBeNull()
  })
})
