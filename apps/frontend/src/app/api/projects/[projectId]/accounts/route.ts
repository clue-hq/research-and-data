import { readAccountBulkCapabilities } from "@/features/accounts/data/bulk-capabilities.repository";
import { getProjectAccountDirectory } from "@/features/accounts/data/project-accounts.repository";
import { getWorkspaceProfile } from "@/features/accounts/data/workspace-profile.repository";
import { getSettingsProfile } from "@/features/settings/data/profile.repository";
import { shellProfile } from "@/features/settings/model/profile";
import { getProtectedSession } from "@/features/session/data/session-dal";

/**
 * The project target-accounts read, as one browser-facing document.
 *
 * Workspace scoping is not decided here: every read below goes through the
 * accounts repositories, which forward the authenticated BFF principal. The
 * person comes from the same authenticated Settings read as the shared shell.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  // Outside the try: an authentication failure is a redirect, and a redirect
  // must never be swallowed into a "please try again" data error.
  const session = await getProtectedSession();
  try {
    const [directory, bulkCapabilities, profile] = await Promise.all([
      getProjectAccountDirectory(projectId),
      // Bulk actions are an optional page capability: an unavailable or invalid
      // capability read hides them rather than failing the screen.
      readAccountBulkCapabilities(),
      session ? getSettingsProfile().then(shellProfile) : getWorkspaceProfile(null),
    ]);
    return Response.json({ ...directory, profile, bulkCapabilities }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "Unable to load target accounts. Please try again." }, { status: 502 });
  }
}
