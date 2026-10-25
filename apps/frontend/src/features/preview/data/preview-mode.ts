/** Server-side opt-in. A preview can never silently mix fixtures with a live workspace. */
export function isFrontendPreviewMode(env: Record<string, string | undefined> = process.env): boolean {
  if (env.CLUE_FRONTEND_PREVIEW_MODE !== "true") return false;
  let localOrigin = false;
  try {
    const url = new URL(env.CLUE_APP_ORIGIN ?? "");
    localOrigin = url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) && Boolean(url.port);
  } catch { /* An invalid origin must fail closed. */ }
  if (env.NODE_ENV !== "development" || env.CLUE_AUTH_ENABLED !== "false" || !localOrigin ||
      env.CLUE_ACCOUNTS_FIXTURE_MODE !== "true" ||
      [env.CLUE_API_BASE_URL, env.CLUE_PROJECTS_API_BASE_URL, env.LUMEN_API_BASE_URL,
        env.NEXT_PUBLIC_CLUE_API_BASE_URL, env.CLUE_LOCAL_WORKSPACE_ID, env.CLUE_LOCAL_WORKSPACE_NAME].some((value) => value?.trim())) {
    throw new Error("Frontend preview requires development mode, a loopback origin with a port, authentication disabled, Accounts fixtures enabled and no backend URLs or workspace pin. Use npm run dev:preview.");
  }
  return true;
}
