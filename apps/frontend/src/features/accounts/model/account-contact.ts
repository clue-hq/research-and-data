import { z } from "zod";

export const ContactSocialSchema = z.enum([
  "linkedin",
  "x",
  "facebook",
  "instagram",
  "whatsapp",
]);

export const ContactPersonaToneSchema = z.enum([
  "olive",
  "orange",
  "blue",
  "cyan",
  "green",
  "pink",
  "red",
]);

export const AccountContactSummarySchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  title: z.string().min(1),
  persona: z.string().min(1),
  personaTone: ContactPersonaToneSchema,
  influence: z.enum(["High", "Medium", "Low"]),
  avatarUrl: z.string().refine(
    (value) => value.startsWith("/") || URL.canParse(value),
    "Expected an absolute URL or a public asset path",
  ),
  emailStatus: z.enum(["available", "lookup"]),
  socials: z.array(ContactSocialSchema),
});

export const ContactEvidenceSchema = z.object({
  id: z.string().min(1),
  source: z.enum(["link", "linkedin", "x"]),
  title: z.string().min(1),
  dateLabel: z.string().min(1),
  url: z.string().url(),
});

export const AccountContactDetailSchema = AccountContactSummarySchema.extend({
  accountId: z.string().min(1),
  accountName: z.string().min(1),
  accountLogoPath: z.string().startsWith("/"),
  recentSignalsLabel: z.string().min(1),
  linkedinLabel: z.string().min(1),
  linkedinUrl: z.string().url(),
  xLabel: z.string().min(1),
  xUrl: z.string().url(),
  overviewParagraphs: z.array(z.string().min(1)).min(1),
  evidence: z.array(ContactEvidenceSchema),
});

export const AccountContactsResponseSchema = z.object({
  data: z.array(AccountContactSummarySchema),
});

export const AccountContactDetailResponseSchema = z.object({
  data: AccountContactDetailSchema,
});

export type AccountContactSummary = z.infer<
  typeof AccountContactSummarySchema
>;
export type AccountContactDetail = z.infer<typeof AccountContactDetailSchema>;
export type ContactPersonaTone = z.infer<typeof ContactPersonaToneSchema>;
export type ContactSocial = z.infer<typeof ContactSocialSchema>;
