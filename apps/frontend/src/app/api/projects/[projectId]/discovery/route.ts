import { getDiscoveryStatus } from "@/features/accounts/data/discovery-status.repository";

/**
 * The Target accounts tab's live poll (spec 2026-09-12 §3). One read, forwarded through the
 * authenticated accounts read client; never cached, since it is the thing that changes.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  try {
    const data = await getDiscoveryStatus(projectId);
    return Response.json({ data }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json(
      { error: "Unable to read discovery progress. Please try again." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
