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
