import { z } from "zod";
import { AccountFitSchema, ResearchStatusSchema } from "./account";

export const AccountContactSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  avatarUrl: z.string().refine(
    (value) => value.startsWith("/") || URL.canParse(value),
    "Expected an absolute URL or a public asset path",
  ),
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
  url: z.string().url(),
});

export const AccountActivitySchema = z.object({
  id: z.string().min(1),
  kind: z.enum(["contacts", "summary", "created"]),
  text: z.string().min(1),
  timeLabel: z.string().min(1),
});

export const AccountDetailSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  previewTitle: z.string().min(1),
  logoPath: z.string().startsWith("/"),
  websiteUrl: z.string().url(),
  websiteLabel: z.string().min(1),
  researchStatus: ResearchStatusSchema,
  sizeLabel: z.string().min(1),
  locationsLabel: z.string().min(1),
  revenueLabel: z.string().min(1),
  referralFit: AccountFitSchema,
  directAccessFit: AccountFitSchema,
  recallFit: AccountFitSchema,
  overallFit: AccountFitSchema,
  summaryParagraphs: z.array(z.string().min(1)).min(1),
  businessParagraphs: z.array(z.string().min(1)).min(1),
  fitCriteria: z.array(AccountFitCriterionSchema),
  contacts: z.array(AccountContactSchema),
  insights: z.array(AccountInsightSchema),
  activity: z.array(AccountActivitySchema),
});

export const AccountDetailResponseSchema = z.object({
  data: AccountDetailSchema,
});

export type AccountContact = z.infer<typeof AccountContactSchema>;
export type AccountDetail = z.infer<typeof AccountDetailSchema>;
export type AccountInsight = z.infer<typeof AccountInsightSchema>;
