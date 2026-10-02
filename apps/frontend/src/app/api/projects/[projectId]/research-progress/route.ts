import { getResearchProgress } from "@/features/accounts/data/research-progress.repository";

/** The pinned research card's poll (spec 2026-09-12 §4). Never cached. */
export async function GET(_request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  try {
    const data = await getResearchProgress(projectId);
    return Response.json({ data }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json(
      { error: "Unable to read research progress. Please try again." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
