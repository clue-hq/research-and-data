import { authenticatedBackendContext } from "@/auth/authenticated-backend";
import { isAuthenticationEnabled, siteEditorSuffix } from "@/auth/config";
import { handleSiteEditorSession } from "@/features/site-editor/server/site-editor-session-handler";

/**
 * Lane C / Contract 9: the browser's read of its workspace's site-editor origin. The label is
 * derived here from the re-authorized workspace id, which never reaches the browser. GET handlers
 * are dynamic by default in this Next version (route.md, v15 change), and this one reads cookies.
 */
export async function GET() {
  return handleSiteEditorSession({
    authenticationEnabled: isAuthenticationEnabled(),
    editorSuffix: siteEditorSuffix(),
    workspaceId: async () => (await authenticatedBackendContext()).workspaceId,
  });
}
