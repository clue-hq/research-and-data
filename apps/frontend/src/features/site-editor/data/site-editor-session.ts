import { z } from "zod";

const SiteEditorSessionWireSchema = z.object({ data: z.object({ editorOrigin: z.url().nullable() }) });

/** The workspace's site-editor origin, or null when no editor domain is configured. */
export async function fetchSiteEditorSession(
  fetchImpl: typeof fetch = (input, init) => fetch(input, init),
): Promise<{ editorOrigin: string | null }> {
  const response = await fetchImpl("/api/clue/site-editor/session", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`The website editor session could not be read (HTTP ${response.status}).`);
  }
  return SiteEditorSessionWireSchema.parse(await response.json()).data;
}
