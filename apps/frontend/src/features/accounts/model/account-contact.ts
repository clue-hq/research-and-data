import { AccountCustomFieldSchema } from "./account";
import { z } from "zod";
import {
  HttpUrlSchema,
  ResearchContactReferenceSchema,
  ResearchDisplayBlockSchema,
  ResearchEvidenceSchema,
} from "./research-display";

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
  title: z.string().min(1).nullable(), // D0 ruling S7
  persona: z.string().min(1),
  membershipState: z.enum(["candidate", "supported", "needs_verification", "excluded"]).nullish(),
  outreachEligible: z.boolean().optional(),
  membershipGaps: z.array(z.string()).optional(),
  personaTone: ContactPersonaToneSchema,
  influence: z.enum(["High", "Medium", "Low"]).nullable(),
  avatarUrl: z
    .string()
    .refine(
      (value) => value.startsWith("/") || URL.canParse(value),
      "Expected an absolute URL or a public asset path",
    )
    .optional(),
  emailStatus: z.enum(["available", "lookup"]),
  emailLabel: z.string().email().optional(),
  socials: z.array(ContactSocialSchema),
  profileAction: z.enum(["none", "preview", "page"]).default("none"),
});

export const ContactEvidenceSchema = z.object({
  id: z.string().min(1),
  source: z.enum(["link", "linkedin", "x"]),
  title: z.string().min(1),
  dateLabel: z.string().min(1),
  url: HttpUrlSchema,
});

export const AccountContactDetailSchema = AccountContactSummarySchema.extend({
  accountId: z.string().min(1),
  accountName: z.string().min(1),
  // A rooted path to the platform's logo route (a stored LinkedIn mark), or Brandfetch's Logo
  // API URL the browser embeds directly (that CDN is embed-only). Founder ruling 2026-09-11,
  // superseding D0 ruling S2's "always null".
  accountLogoPath: z
    .string()
    .refine((value) => value.startsWith("/") || value.startsWith("https://cdn.brandfetch.io/"))
    .nullable(),
  recentSignalsLabel: z.string().min(1),
  linkedinLabel: z.string().min(1),
  linkedinUrl: HttpUrlSchema,
  xLabel: z.string().min(1).optional(),
  xUrl: HttpUrlSchema.optional(),
  emailVerifiedAt: z.string().date().optional(),
  emailClaimId: z.string().min(1).nullable().default(null), // D0 ruling R5
  locationLabel: z.string().min(1).optional(),
  bestFirstChannelLabel: z.string().min(1).optional(),
  educationLabel: z.string().min(1).optional(),
  tenureLabel: z.string().min(1).optional(),
  employmentStartedAt: z.string().date().optional(),
  linkedinFollowers: z.number().int().nonnegative().optional(),
  linkedinCreator: z.boolean().optional(),
  locationClaimId: z.string().optional(),
  reports: z.array(ResearchContactReferenceSchema).default([]),
  overviewParagraphs: z.array(z.string().min(1)).default([]), // D0 ruling S5
  evidence: z.array(ContactEvidenceSchema),
  researchEvidence: z.array(ResearchEvidenceSchema).default([]),
  customFields: z.array(AccountCustomFieldSchema).default([]),
  contactDisplay: ResearchDisplayBlockSchema.optional(),
  lastModifiedAt: z.string().datetime(), // D0 ruling R8 (the contact's own latest verifiedAt)
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
