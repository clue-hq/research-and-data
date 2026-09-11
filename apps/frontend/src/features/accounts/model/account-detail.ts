import { z } from "zod";
import {
  AccountCustomFieldSchema,
  AccountFitSchema,
  AccountOwnerSchema,
  AccountSocialSchema,
  ResearchStatusSchema,
} from "./account";
import {
  BuyingCommitteeMemberSchema,
  HttpUrlSchema,
  ResearchDisplayBlockSchema,
  ResearchEvidenceSchema,
} from "./research-display";

export const AccountContactSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  avatarUrl: z
    .string()
    .refine(
      (value) => value.startsWith("/") || URL.canParse(value),
      "Expected an absolute URL or a public asset path",
    )
    .optional(),
  title: z.string().min(1).optional(),
  persona: z.string().min(1).optional(),
  emailVerified: z.boolean().optional(),
  hasDetail: z.boolean().default(false),
});

export const AccountFitCriterionSchema = z.object({
  id: z.string().min(1),
  matched: z.boolean(),
  title: z.string().min(1),
  evidence: z.string().min(1),
});

export const AccountInsightSchema = z.object({
  id: z.string().min(1),
  source: z.enum(["link", "linkedin", "x"]),
  title: z.string().min(1),
  dateLabel: z.string().min(1),
  url: HttpUrlSchema,
});

export const AccountActivitySchema = z.object({
  id: z.string().min(1),
  kind: z.enum(["contacts", "summary", "created", "artifact", "updated"]),
  text: z.string().min(1),
  timeLabel: z.string().min(1),
  actor: z.discriminatedUnion("type", [
    z.object({ type: z.literal("clue") }),
    AccountOwnerSchema.extend({ type: z.literal("person") }),
  ]).optional(),
  action: z.string().min(1).optional(),
  occurredAt: z.string().datetime().optional(),
  isSample: z.boolean().optional(),
});

export const AccountDetailSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  previewTitle: z.string().min(1),
  // A rooted path to the platform's logo route (a stored LinkedIn mark), or Brandfetch's Logo
  // API URL the browser embeds directly (that CDN is embed-only). Founder ruling 2026-09-11,
  // superseding D0 ruling S2's "always null".
  logoPath: z
    .string()
    .refine((value) => value.startsWith("/") || value.startsWith("https://cdn.brandfetch.io/"))
    .nullable(),
  websiteUrl: HttpUrlSchema.nullable(), // D3 ruling (source map: null when no primary_domain)
  websiteLabel: z.string().min(1),
  researchStatus: ResearchStatusSchema,
  researchStatusLabel: z.string().min(1).optional(),
  owner: AccountOwnerSchema.nullish(),
  createdBy: AccountOwnerSchema.nullish(),
  industryLabels: z.array(z.string().min(1)).default([]), // D0 ruling S5
  headcountLabel: z.string().min(1),
  locationsLabel: z.string().min(1),
  revenueLabel: z.string().min(1),
  foundedLabel: z.string().min(1).optional(),
  fundingLabel: z.string().min(1).optional(),
  fitScore: z.number().int().min(0).max(100).nullable(),
  fitScoreLabel: z.string().min(1).optional(),
  createdAt: z.string().datetime(),
  lastModifiedAt: z.string().datetime(),
  socials: z.array(AccountSocialSchema).default([]),
  customFields: z.array(AccountCustomFieldSchema).default([]),
  overallFit: AccountFitSchema.nullable(), // D0 ruling R7
  summaryParagraphs: z.array(z.string().min(1)).default([]), // D0 ruling S5
  businessParagraphs: z.array(z.string().min(1)).default([]), // D0 ruling S5
  fitCriteria: z.array(AccountFitCriterionSchema),
  contacts: z.array(AccountContactSchema),
  insights: z.array(AccountInsightSchema),
  activity: z.array(AccountActivitySchema),
  headerMetadata: z.array(z.string().min(1)).default([]),
  researchEvidence: z.array(ResearchEvidenceSchema).default([]),
  overviewDisplay: ResearchDisplayBlockSchema.optional(),
  buyingCommittee: z.array(BuyingCommitteeMemberSchema).default([]),
});

export const AccountDetailResponseSchema = z.object({
  data: AccountDetailSchema,
});

export type AccountContact = z.infer<typeof AccountContactSchema>;
export type AccountDetail = z.infer<typeof AccountDetailSchema>;
export type AccountInsight = z.infer<typeof AccountInsightSchema>;
