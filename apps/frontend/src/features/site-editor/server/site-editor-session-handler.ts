import { editorLabelFor, editorOriginFor } from "@clue/site-kit/editor-origin";
import { ClueAuthenticationError } from "@/auth/errors";

export interface SiteEditorSessionDeps {
  authenticationEnabled: boolean;
  editorSuffix: string;
  /** The re-authorized workspace id (server-side only; it never reaches the browser). */
  workspaceId: () => Promise<string>;
}

const NO_STORE = { "cache-control": "no-store" };

function refusal(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message, requestId: null } }, { headers: NO_STORE, status });
}

/** Contract 9: the editor origin for THIS workspace — `https://<label>.<suffix>`, the label an
 * opaque token derived from the workspace id. Testable without Next (the route only composes it). */
export async function handleSiteEditorSession(deps: SiteEditorSessionDeps): Promise<Response> {
  if (!deps.authenticationEnabled || !deps.editorSuffix) {
    return Response.json({ data: { editorOrigin: null } }, { headers: NO_STORE });
  }
  let workspaceId: string;
  try {
    workspaceId = await deps.workspaceId();
  } catch (error) {
    if (error instanceof ClueAuthenticationError) return refusal(error.status, error.code, error.message);
    throw error;
  }
  let editorOrigin: string;
  try {
    editorOrigin = editorOriginFor(await editorLabelFor(workspaceId), deps.editorSuffix);
  } catch {
    return refusal(500, "SITE_EDITOR_MISCONFIGURED", "CLUE_SITE_EDITOR_SUFFIX is not a domain suffix");
  }
  return Response.json({ data: { editorOrigin } }, { headers: NO_STORE });
}
