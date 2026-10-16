/** The page as one exported file has no server: `repro ui --export` marks it, and embeds the data. */
export const STATIC = typeof document !== 'undefined' && Boolean(document.querySelector('meta[name="repro-ui-static"]'))

/** The export file as it was opened, read before the page draws anything into it, so Download as
 * HTML from an export saves the same bytes rather than the drawn page. */
export const ORIGINAL = STATIC ? `<!doctype html>\n${document.documentElement.outerHTML}` : ''

/** graph.json: embedded in an export, fetched from the server otherwise. */
export function loadGraph(): Promise<unknown> {
  if (STATIC) {
    const el = document.getElementById('repro-graph')
    return el ? Promise.resolve(JSON.parse(el.textContent ?? '{}')) : Promise.reject(new Error('no data in this file'))
  }
  return fetch(`graph.json?t=${Date.now()}`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`graph.json: ${r.status}`))))
}

/** POST to the local server as the page itself: JSON, with the token the server wrote into this
 * page when it served it. The server refuses a POST without both, so another site cannot send one. */
export function post(url: string, body: unknown): Promise<Response> {
  const token = document.querySelector<HTMLMetaElement>('meta[name="repro-ui-token"]')?.content ?? ''
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Repro-UI-Token': token },
    body: JSON.stringify(body),
  })
}

/** A POST made by a person's click: if the page's own refresh holds the server for a moment, wait
 * for it rather than reporting "already running". Waits up to ten seconds. */
export async function postWhenFree(url: string, body: unknown): Promise<Response> {
  let r = await post(url, body)
  for (let i = 0; r.status === 409 && i < 20; i++) {
    await new Promise((resolve) => setTimeout(resolve, 500))
    r = await post(url, body)
  }
  return r
}
