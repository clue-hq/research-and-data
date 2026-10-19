/**
 * Review finding S7-2: a production app without CLUE_SITE_EDITOR_SUFFIX answers every site with
 * "The website editor is not configured" — a 200, not an error, so nothing was ever logged. The
 * server says so once, loudly, when it starts (src/instrumentation.ts). It does not refuse to
 * start: everything but websites still works.
 */
export function siteEditorStartupProblem(env: Record<string, string | undefined>): string | null {
  if (env.NODE_ENV !== "production") return null;
  if ((env.CLUE_SITE_EDITOR_SUFFIX ?? "").trim()) return null;
  return (
    "CLUE_SITE_EDITOR_SUFFIX is not set: every website will show \"The website editor is not configured\". " +
    "Set it to the site editor's domain (docs/deploy/runbook.md §2, the frontend and site editor services)."
  );
}
