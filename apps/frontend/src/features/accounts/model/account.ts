import { z } from "zod";
import { HttpUrlSchema } from "./research-display";

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

export const AccountOwnerSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  avatarUrl: z
    .string()
    .refine(
      (value) => value.startsWith("/") || URL.canParse(value),
      "Expected an absolute URL or a public asset path",
    )
    .optional(),
});

export const AccountSocialSchema = z.object({
  id: z.string().min(1),
  label: z.enum(["LinkedIn", "Twitter", "Facebook", "Instagram"]),
  url: HttpUrlSchema,
});

export const AccountCustomFieldSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  value: z.string().min(1),
  presentation: z.enum(["text", "badge", "score"]).default("text"),
  primary: z.boolean().default(false),
});

export const AccountSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  logoPath: z.string().startsWith("/"),
  websiteUrl: HttpUrlSchema,
  researchStatus: ResearchStatusSchema,
  researchStatusLabel: z.string().min(1).optional(),
  researchIsRefreshing: z.boolean().default(false),
  overallFit: AccountFitSchema,
  fitScore: z.number().int().min(0).max(100).nullable(),
  revenueBand: z.string().min(1),
  employeeBand: z.string().min(1),
  locationCount: z.number().int().nonnegative(),
  locationsLabel: z.string().min(1).optional(),
  owner: AccountOwnerSchema.nullish(),
  createdBy: AccountOwnerSchema.nullish(),
  industryLabels: z.array(z.string().min(1)).default([]),
  socials: z.array(AccountSocialSchema).default([]),
  createdAt: z.string().datetime().optional(),
  lastModifiedAt: z.string().datetime().optional(),
  primaryProjectId: z.string().min(1).nullable().default(null),
  projects: z.array(AccountProjectSchema).default([]),
  customFields: z.array(AccountCustomFieldSchema).default([]),
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
export type AccountOwner = z.infer<typeof AccountOwnerSchema>;
export type AccountSocial = z.infer<typeof AccountSocialSchema>;
export type AccountCustomField = z.infer<typeof AccountCustomFieldSchema>;
export type AccountsResponse = z.infer<typeof AccountsResponseSchema>;
export type ResearchStatus = z.infer<typeof ResearchStatusSchema>;
