import { z } from "zod";

export const ResearchStatusSchema = z.enum([
  "not_started",
  "in_progress",
  "fully_enriched",
  "failed",
]);

export const AccountFitSchema = z.enum(["High", "Medium", "Low"]);

export const AccountProjectSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
});

export const AccountSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  logoPath: z.string().startsWith("/"),
  websiteUrl: z.string().url(),
  researchStatus: ResearchStatusSchema,
  researchIsRefreshing: z.boolean().default(false),
  overallFit: AccountFitSchema,
  fitScore: z.number().int().min(0).max(100),
  revenueBand: z.string().min(1),
  employeeBand: z.string().min(1),
  locationCount: z.number().int().nonnegative(),
  primaryProjectId: z.string().min(1).nullable().default(null),
  projects: z.array(AccountProjectSchema).default([]),
});

export const AccountsResponseSchema = z.object({
  data: z.array(AccountSchema),
  meta: z.object({
    total: z.number().int().nonnegative(),
    nextCursor: z.string().nullable(),
  }),
});

export type Account = z.infer<typeof AccountSchema>;
export type AccountProject = z.infer<typeof AccountProjectSchema>;
export type AccountsResponse = z.infer<typeof AccountsResponseSchema>;
export type ResearchStatus = z.infer<typeof ResearchStatusSchema>;
