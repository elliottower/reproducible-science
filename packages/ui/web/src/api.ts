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
