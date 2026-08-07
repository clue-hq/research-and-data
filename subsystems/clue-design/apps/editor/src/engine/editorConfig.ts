/**
 * Editor runtime configuration — the single source for the API base URL.
 * A function (not a const) so every caller keeps read-at-call-time
 * semantics; Next.js inlines NEXT_PUBLIC_* per expression, so client
 * bundles and jsdom tests behave identically.
 */
export function editorApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000";
}
