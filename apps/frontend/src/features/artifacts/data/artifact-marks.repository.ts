import { z } from "zod";
import { fetchMutation } from "@/features/accounts/data/frontend-mutation";

const SavedResponseSchema = z.object({ data: z.object({ saved: z.boolean() }) });
const ViewedResponseSchema = z.object({ data: z.object({ last_viewed_at: z.string().min(1) }) });

export async function setArtifactSaved(artifactId: string, saved: boolean): Promise<boolean> {
  const body = await fetchMutation(`/artifacts/${encodeURIComponent(artifactId)}/saved`, {
    method: "PUT",
    body: JSON.stringify({ saved }),
  });
  return SavedResponseSchema.parse(body).data.saved;
}

export async function recordArtifactViewed(artifactId: string): Promise<string> {
  const body = await fetchMutation(`/artifacts/${encodeURIComponent(artifactId)}/viewed`, { method: "POST" });
  return ViewedResponseSchema.parse(body).data.last_viewed_at;
}
