import { z } from "zod";

/** The pinned research card's document (`/frontend/v1/projects/:id/research/progress`). */
export const ResearchProgressSchema = z.object({
  requested_accounts: z.number().int().nonnegative(),
  queued: z.number().int().nonnegative(),
  running: z.number().int().nonnegative(),
  finished: z.number().int().nonnegative(),
  progress_pct: z.number().int().min(0).max(100),
  pill: z.enum(["running", "completed", "needs_attention"]).catch("running"),
  last_finished_at: z.string().nullable(),
  agents: z.array(
    z.object({
      account_name: z.string(),
      stage: z.enum(["deep_research", "synthesis", "committee", "member_research"]).catch("deep_research"),
      subject: z.enum(["account", "person"]).catch("account"),
    }),
  ),
  attention: z.array(z.object({ account_name: z.string(), reason: z.string() })),
});

export type ResearchProgress = z.infer<typeof ResearchProgressSchema>;

export const ResearchProgressResponseSchema = z.object({ data: ResearchProgressSchema.nullable() });
