import { describe, expect, it } from 'vitest'
import { arrange, claimsLine, type Project } from './drawer'

const p = (name: string, over: Partial<Project> = {}): Project => ({
  path: `/w/${name}`, name, title: null, opened_at: '2026-10-01T00:00:00+00:00', starred: false, current: false, available: true, claims: null, ...over,
})

const LIST = [
  p('old', { opened_at: '2026-09-01T00:00:00+00:00', starred: true }),
  p('here', { opened_at: '2026-10-10T00:00:00+00:00', starred: true, current: true, title: 'Reproducible Science' }),
  p('new', { opened_at: '2026-10-14T00:00:00+00:00' }),
  p('starred-new', { opened_at: '2026-10-15T00:00:00+00:00', starred: true }),
]

describe('the drawer', () => {
  it('shows starred projects as cards, the viewed one first, then newest opened', () => {
    expect(arrange(LIST, '').starred.map((x) => x.name)).toEqual(['here', 'starred-new', 'old'])
  })
  it('lists every project, newest opened first', () => {
    expect(arrange(LIST, '').all.map((x) => x.name)).toEqual(['starred-new', 'new', 'here', 'old'])
  })
  it('searches names, titles and folders, every word', () => {
    expect(arrange(LIST, 'reproducible').all.map((x) => x.name)).toEqual(['here'])
    expect(arrange(LIST, 'w new').all.map((x) => x.name)).toEqual(['starred-new', 'new'])
    expect(arrange(LIST, 'nothing').all).toEqual([])
  })
  it('says the claims as of the last check, or nothing when never checked', () => {
    expect(claimsLine(p('a', { claims: { verified: 531, total: 531, checked_at: null } }))).toBe('claims: 531/531 verified')
    expect(claimsLine(p('a', { claims: { verified: 1062, total: 1100, checked_at: null } }))).toBe('claims: 1,062/1,100 verified')
    expect(claimsLine(p('a'))).toBeNull()
  })
})
