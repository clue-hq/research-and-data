/**
 * Editor runtime configuration — the single source for the API base URL.
 * A function (not a const) so every caller keeps read-at-call-time
 * semantics; Next.js inlines NEXT_PUBLIC_* per expression, so client
 * bundles and jsdom tests behave identically.
 */
export function editorApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000";
}

/**
 * The workspace this editor session talks to (design-integration Part II, O4).
 *
 * The API's workspace seam is strict: every request carries `X-Workspace-Id`
 * or is refused with 401 `workspace.header_required`. Until Part IV puts a
 * real auth/workspace picker in the platform shell, the dev harness pins one
 * workspace from the environment — same read-at-call-time reasoning as
 * `editorApiBaseUrl` (Next.js inlines NEXT_PUBLIC_* per expression).
 */
export function editorWorkspaceId(): string {
  return process.env.NEXT_PUBLIC_LUMEN_WORKSPACE_ID ?? "ws_lumen_dev";
}

/**
 * The run-stream handshake pair (design-integration Part II, D7).
 *
 * The stream used to carry its tenant in the query string, because `EventSource`
 * cannot set request headers — strict about the parameter being present, but
 * unable to be strict about it being *true*. D7 replaces that with a single-use
 * token: mint it through a normal header-authenticated POST (`lumenFetch`), then
 * present it on the GET. The workspace is read off the token row the mint wrote,
 * so no client-supplied tenant is ever trusted.
 */
export function runStreamTokenUrl(apiBaseUrl: string, runId: string): string {
  return new URL(
    `/agent/runs/${encodeURIComponent(runId)}/stream-token`,
    apiBaseUrl
  ).toString();
}

export function runEventsUrl(apiBaseUrl: string, runId: string, streamToken: string): string {
  const url = new URL(`/agent/runs/${encodeURIComponent(runId)}/events`, apiBaseUrl);
  url.searchParams.set("stream_token", streamToken);
  return url.toString();
}

/**
 * `fetch` with the workspace header attached — the ONE way the editor talks to
 * the design API.
 *
 * Caller-supplied headers win, so a call site can still override the workspace
 * (nothing does today). Do NOT use this for `/asset-store/{digest}`: those
 * bytes are public and are fetched from contexts whose origin is "null" (the
 * web-preview srcdoc iframe), where adding a custom header would turn the
 * request into a preflight the wildcard CORS response cannot satisfy.
 */
export function lumenFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, {
    ...init,
    headers: { "X-Workspace-Id": editorWorkspaceId(), ...(init?.headers ?? {}) }
  });
}
