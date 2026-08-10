import { z } from "zod";
import {
  AddedViaSchema,
  IsoTimestampSchema,
  ResearchStatusSchema,
} from "./vocabulary";

export { ResearchStatusSchema } from "./vocabulary";
export type { ResearchStatus } from "./vocabulary";

/**
 * One project that targets this account, and how/when it joined.
 *
 * `name` is the project record's own name, resolved by a read-layer join, and
 * is nullable: `null` for the unattributed section and for any section whose
 * project id this workspace holds no `project` row for. Never render the id as
 * a fallback name — an unnamed project is the honest rendering.
 */
export const AccountProjectSchema = z.object({
  projectId: z.string(),
  name: z.string().nullable().default(null),
  addedVia: AddedViaSchema.nullable().default(null),
  addedAt: IsoTimestampSchema.nullable().default(null),
});

/**
 * A Pass-A score under one ICP, carrying the project it belongs to.
 *
 * `fit`/`intent` are unit-interval (0–1) and independently nullable: a project
 * may have scored fit and not intent, and reporting the missing half as `0`
 * would be a fabrication. The list is keyed by `(projectId, icpKey,
 * icpVersion)` — one project can score an account under several ICPs and
 * versions, so no representative run is chosen.
 */
export const AccountProjectScoreSchema = z.object({
  projectId: z.string(),
  fit: z.number().nullable().default(null),
  intent: z.number().nullable().default(null),
  icpKey: z.string().nullable().default(null),
  icpVersion: z.number().int().nullable().default(null),
  scoredAt: IsoTimestampSchema.nullable().default(null),
});

/**
 * The research status of this account *within* one project.
 *
 * An entry may name a project the account has no membership row for (research
 * was launched for a project that no longer targets it); that is reported
 * rather than hidden, so `projectId` is not always a member of `projects[]`.
 */
export const AccountResearchStatusSchema = z.object({
  projectId: z.string(),
  status: ResearchStatusSchema,
});

export const AccountSchema = z.object({
  id: z.string(),
  name: z.string(),
  domain: z.string().nullable().default(null),
  /** A headcount claim, not a band — banding is a display decision the frontend owns. */
  employeeCount: z.number().int().nullable().default(null),
  /**
   * The backend claim vocabulary (for example `100m_500m`), not a display
   * string, and not a guaranteed closed enum: the value is whatever the
   * field's writer produced. Rendered through a lookup with a fallback.
   */
  revenueBand: z.string().nullable().default(null),
  /** Always `null` today — no logo pipeline exists; the initials fallback renders. */
  logoUrl: z.string().nullable().default(null),
  projects: z.array(AccountProjectSchema).default([]),
  primaryProjectId: z.string().nullable().default(null),
  scores: z.array(AccountProjectScoreSchema).default([]),
  researchStatus: z.array(AccountResearchStatusSchema).default([]),
  /**
   * The `account_entity` row's update time — NOT research or claim recency. It
   * does not move when a new claim, score, or narrative lands.
   */
  updatedAt: IsoTimestampSchema.nullable().default(null),
});

export const AccountsResponseSchema = z.object({
  data: z.array(AccountSchema),
  meta: z.object({
    total: z.number().int().nonnegative(),
    nextCursor: z.string().nullable().default(null),
  }),
});

export type Account = z.infer<typeof AccountSchema>;
export type AccountProject = z.infer<typeof AccountProjectSchema>;
export type AccountProjectScore = z.infer<typeof AccountProjectScoreSchema>;
export type AccountResearchStatusEntry = z.infer<
  typeof AccountResearchStatusSchema
>;
export type AccountsResponse = z.infer<typeof AccountsResponseSchema>;
