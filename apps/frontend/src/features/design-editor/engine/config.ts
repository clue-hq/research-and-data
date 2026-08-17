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
 * - Browser callers reach the design API ONLY through the authenticated BFF
 *   (`/api/clue/design`, W1.2), which stamps `X-Workspace-Id` server-side
 *   from the session — never a FastAPI origin. W2.1 correction to the
 *   original sketch here: the engine builds URLs with `new URL(path,
 *   apiBaseUrl)`, so `apiBaseUrl` must be an ORIGIN (a path-prefix base
 *   throws, and URL resolution would drop the prefix anyway). The working
 *   form is `data/design-bff.ts`'s `designBffConfig()`: `apiBaseUrl` = the
 *   page origin plus a `fetchImpl` that re-mounts every engine URL under the
 *   same-origin BFF prefix (session cookies ride along automatically).
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
