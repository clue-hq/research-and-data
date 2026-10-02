import { fetchRead } from "./frontend-api";
import { ResearchProgressResponseSchema, type ResearchProgress } from "@/features/projects/model/research-progress";

export async function getResearchProgress(
  projectId: string,
  read: typeof fetchRead = fetchRead,
): Promise<ResearchProgress | null> {
  const body = await read(`/projects/${encodeURIComponent(projectId)}/research/progress`);
  return ResearchProgressResponseSchema.parse(body).data;
}
