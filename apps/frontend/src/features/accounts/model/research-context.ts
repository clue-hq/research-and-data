import { z } from "zod";

export const ResearchContextQuerySchema = z.object({
  projectId: z.string().min(1).optional(),
  contextId: z.string().uuid().optional(),
});
export type ResearchContextQuery = z.infer<typeof ResearchContextQuerySchema>;

export function researchContextQuery(query: Record<string, string | string[] | undefined>): ResearchContextQuery {
  return ResearchContextQuerySchema.parse({
    projectId: typeof query.projectId === "string" ? query.projectId : undefined,
    contextId: typeof query.contextId === "string" ? query.contextId : undefined,
  });
}

export function withResearchContext(path: string, context?: ResearchContextQuery): string {
  const params = new URLSearchParams();
  if (context?.projectId) params.set("projectId", context.projectId);
  if (context?.contextId) params.set("contextId", context.contextId);
  return params.size ? `${path}${path.includes("?") ? "&" : "?"}${params}` : path;
}

export const ResearchQualitySchema = z.object({
  projectId: z.string().nullish(),
  contextId: z.string().uuid().nullish(),
  generationId: z.string().uuid().nullish(),
  qualityState: z.enum(["researching", "provisional", "reconciled", "partial", "needs_review",
    "suspended", "privacy_stopped", "context_required", "legacy"]),
  refreshPending: z.boolean().default(false),
  gaps: z.array(z.string()).default([]),
  contexts: z.array(z.object({projectId: z.string(), projectName: z.string(), contextId: z.string().uuid(), accountId: z.string()})).default([]),
});
export type ResearchQuality = z.infer<typeof ResearchQualitySchema>;

export function researchHref(path: string, accountId: string, context?: ResearchContextQuery): string {
  const base = `/accounts/${accountId}`;
  return !path.includes("?") && (path === base || path.startsWith(`${base}/`))
    ? withResearchContext(path, context) : path;
}
