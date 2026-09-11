import { readAccountBulkCapabilities } from "@/features/accounts/data/bulk-capabilities.repository";
import { getProjectAccountDirectory } from "@/features/accounts/data/project-accounts.repository";
import { getWorkspaceProfile } from "@/features/accounts/data/workspace-profile.repository";
import { getProtectedSession } from "@/features/session/data/session-dal";

/**
 * The project target-accounts read, as one browser-facing document.
 *
 * Workspace scoping is not decided here: every read below goes through the
 * accounts repositories, which forward the authenticated BFF principal. The
 * session is resolved only to name the workspace person — the design build took
 * that from its settings feature, which the platform does not have.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  // Outside the try: an authentication failure is a redirect, and a redirect
  // must never be swallowed into a "please try again" data error.
  const profile = getWorkspaceProfile(await getProtectedSession());
  try {
    const [directory, bulkCapabilities] = await Promise.all([
      getProjectAccountDirectory(projectId),
      // Bulk actions are an optional page capability: an unavailable or invalid
      // capability read hides them rather than failing the screen.
      readAccountBulkCapabilities(),
    ]);
    return Response.json({ ...directory, profile, bulkCapabilities }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "Unable to load target accounts. Please try again." }, { status: 502 });
  }
}
