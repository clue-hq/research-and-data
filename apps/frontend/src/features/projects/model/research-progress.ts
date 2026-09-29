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
      subject_name: z.string().nullish(),
      stage: z.enum(["deep_research", "synthesis", "committee", "member_research", "researching", "compiling_findings", "storing_claims", "writing_narrative", "completed"]).catch("deep_research"),
      subject: z.enum(["account", "person"]).catch("account"),
    }),
  ),
  attention: z.array(z.object({ account_name: z.string(), reason: z.string() })),
  /**
   * The open provider incident behind the attention rows, when one is open. `.catch(null)` so a
   * backend that predates the field still parses; `.nullable()` because the backend sends `null`
   * whenever no provider is to blame.
   */
  incident: z
    .object({
      provider_label: z.string(),
      reason_label: z.string(),
      since: z.string(),
      affected: z.number().int().nonnegative(),
      notified: z.boolean(),
    })
    .nullable()
    .catch(null),
});

export type ResearchProgress = z.infer<typeof ResearchProgressSchema>;

export const ResearchProgressResponseSchema = z.object({ data: ResearchProgressSchema.nullable() });
