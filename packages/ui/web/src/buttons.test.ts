// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'

/** The page's own stylesheet, applied to markup shaped as the page renders it. jsdom applies the
 * cascade (not layout), so what this reads is the height, padding and size each rule sets. */
beforeAll(() => {
  const style = document.createElement('style')
  style.textContent = readFileSync(join(__dirname, 'styles.css'), 'utf8')
  document.head.appendChild(style)
  document.body.innerHTML = `
    <header class="top">
      <div class="dd"><button id="verify" class="btn ghost-dark">✓ repro verify ▾</button></div>
      <div class="dd"><button id="ask" class="btn ghost-dark">Ask AI ▾</button></div>
      <div class="dd"><button id="share" class="btn primary">Share ▾</button></div>
    </header>
    <div class="rec">
      <div class="rp-head"><h1>Reproduce</h1><span class="spacer"></span>
        <button id="head-copy" class="btn">Copy command</button><button id="head-run" class="btn primary">▶ Re-run all</button></div>
      <aside class="panel"><div class="rp-actions">
        <button id="panel-run" class="btn primary">▶ Run again</button><button id="panel-copy" class="btn">Copy command</button></div></aside>
    </div>`
})

const box = (id: string) => {
  const s = getComputedStyle(document.getElementById(id)!)
  return {
    height: s.height, paddingTop: s.paddingTop, paddingBottom: s.paddingBottom, paddingLeft: s.paddingLeft,
    fontSize: s.fontSize, marginTop: s.marginTop, marginBottom: s.marginBottom, borderTopWidth: s.borderTopWidth,
  }
}

describe('buttons that sit side by side', () => {
  it.each([
    ['the step panel', 'panel-run', 'panel-copy'],
    ['the Reproduce header', 'head-run', 'head-copy'],
    ['the top bar', 'share', 'ask'],
    ['the top bar', 'verify', 'ask'],
  ])('in %s have one height, padding, size and border, and no margin', (_, a, b) => {
    expect(box(a)).toEqual(box(b))
    expect(box(a).height).toBe('28px')
    expect([box(a).marginTop, box(a).marginBottom]).toEqual(['0px', '0px'])
  })
  it('sit on one centre line in their rows', () => {
    for (const sel of ['.rp-head', '.rp-actions', '.top .dd']) {
      expect(getComputedStyle(document.querySelector(sel)!).alignItems).toBe('center')
    }
  })
})
