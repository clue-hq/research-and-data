/**
 * Injected configuration for the extracted web engine (W1.1).
 *
 * The engine's API functions all take this as their options argument — the
 * shape the source modules already used (`WebDocumentOptions`), promoted to
 * the package's one config seam. Field naming note: the W-plan sketch wrote
 * `apiBase`; the source modules' `apiBaseUrl` is kept because signature
 * preservation was the stronger requirement ("signatures preserved from the
 * source modules except the added leading config").
 *
 * Platform contract:
 * - `apiBaseUrl` is the authenticated BFF prefix (`"/api/clue/design"`),
 *   NEVER a FastAPI origin. The design API is workspace-header-auth only and
 *   must not be reachable from browsers; the BFF (W1.2) stamps
 *   `X-Workspace-Id` server-side from the session. Browser requests are
 *   same-origin, so session cookies ride along automatically.
 * - `fetchImpl` exists for tests and server-side callers. In the browser the
 *   default wrapper below is used; it adds NO headers (the workspace header
 *   in the browser was the dev-harness pattern this extraction retires).
 * - No module in this package reads ambient environment variables — enforced
 *   by `__tests__/no-env-reads.test.ts` (which greps sources, comments
 *   included, so even naming the forbidden global here would trip it).
 */
export interface DesignEditorConfig {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

/**
 * The default fetch: a lexical wrapper (never a stored bare `fetch`
 * reference, which browsers reject as an illegal invocation when unbound).
 */
export function defaultDesignFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  return fetch(input, init);
}
