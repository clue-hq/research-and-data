import { z } from "zod";
import { ResearchQualitySchema } from "./research-context";

export const HttpUrlSchema = z
  .string()
  .url()
  .refine(
    (value) => {
      const protocol = new URL(value).protocol;
      return protocol === "http:" || protocol === "https:";
    },
    "Expected an HTTP(S) URL",
  );

export const ResearchEvidenceSchema = z.object({
  claimId: z.string().min(1),
  sourceKind: z.enum(["primary_quote", "source_excerpt", "provider_record", "inference"]).nullish(),
  sourceExcerpt: z.string().nullish(),
  qualifications: z.array(z.string()).optional(),
  supportingClaimIds: z.array(z.string()).optional(),
  sellerPassages: z.array(z.object({ documentId: z.string(), sha256: z.string(), quote: z.string(), start: z.number(), end: z.number() })).optional(),
  researchFieldKey: z.string().nullish(),
  sourceUrl: HttpUrlSchema.nullable(),
  sourceDomain: z.string().min(1).nullable(),
  faviconUrl: HttpUrlSchema.nullable(),
  title: z.string().min(1).nullable(),
  quote: z.string().min(1).nullable(),
  researchExcerpt: z.string().optional(),
  publishedAt: z.string().date().nullable(),
  verifiedAt: z.string().date(),
  verificationKind: z.enum(["verified", "record"]).default("verified"),
  mediaTimestamp: z.string().min(1).nullable(),
  provider: z.string().min(1).nullable(),
  outreachSafe: z.boolean(),
});

export const ResearchInlineSegmentSchema = z.object({
  text: z.string(),
  claimIds: z.array(z.string().min(1)).default([]),
});

export const ResearchSentenceSchema = z.object({
  text: z.string(),
  claimIds: z.array(z.string().min(1)).default([]),
  segments: z.array(ResearchInlineSegmentSchema).optional(),
  kind: z.enum(["fact", "inference", "quote", "qualified", "gap"]).nullish(),
  qualifications: z.array(z.string()).optional(),
});

export const ResearchContactReferenceSchema = z.object({
  accountId: z.string().min(1),
  contactId: z.string().min(1),
  name: z.string().min(1),
  title: z.string().min(1).optional(),
  persona: z.string().min(1).optional(),
  emailState: z.enum(["verified", "unverified", "not_requested"]).optional(),
  avatarUrl: z
    .string()
    .refine(
      (value) => value.startsWith("/") || URL.canParse(value),
      "Expected an absolute URL or a public asset path",
    )
    .optional(),
});

export const ResearchSendLineSchema = z.object({
  channel: z.string().min(1),
  text: z.string().min(1),
  claimIds: z.array(z.string().min(1)).default([]),
});

export const ResearchItemSchema = z.object({
  id: z.string().min(1),
  h2: z.string().min(1),
  body: z.array(ResearchSentenceSchema),
  sendLine: ResearchSendLineSchema.nullable().default(null),
  contactRefs: z.array(ResearchContactReferenceSchema).default([]),
  inlineLead: z.boolean().optional(),
  fitDisposition: z.enum(["support", "caveat"]).optional(),
  subject: ResearchContactReferenceSchema.optional(),
  priority: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  newSinceLastVisit: z.boolean().default(false),
});

export const ResearchSectionSchema = z.object({
  key: z.string().min(1),
  h1: z.string().min(1),
  empty: z.boolean(),
  items: z.array(ResearchItemSchema),
  intro: z.array(ResearchSentenceSchema).optional(),
  restricted: z.boolean().default(false),
  defaultOpen: z.boolean().default(false),
  // Plan 2026-09-21: true while the fleet is writing this section; the client polls while any
  // section on the page is pending and renders `emptyMessage` verbatim meanwhile.
  pending: z.boolean().default(false),
  emptyMessage: z.string().optional(),
  gaps: z.array(z.string()).optional(),
});

export const ResearchDisplayBlockSchema = z.object({
  page: z.enum(["insights", "overview", "contact"]),
  sections: z.array(ResearchSectionSchema),
  researchQuality: ResearchQualitySchema.nullish(),
});

export const BuyingCommitteeMemberSchema = z.object({
  contactId: z.string().min(1),
  name: z.string().min(1),
  title: z.string().min(1),
  persona: z.string().min(1),
  email: z.string().email().nullable(),
  emailClaimId: z.string().min(1).nullable(),
  // D3 ruling: a committee member resolved from a coverage row may have no LinkedIn URL;
  // the dummy renders the link only when present.
  linkedinUrl: HttpUrlSchema.nullable(),
  whyTheyMatter: z.string().min(1),
  membershipState: z.enum(["candidate", "supported", "needs_verification", "excluded"]).nullish(),
  outreachEligible: z.boolean().optional(),
  membershipGaps: z.array(z.string()).optional(),
});

export type BuyingCommitteeMember = z.infer<
  typeof BuyingCommitteeMemberSchema
>;
export type ResearchContactReference = z.infer<
  typeof ResearchContactReferenceSchema
>;
export type ResearchInlineSegment = z.infer<
  typeof ResearchInlineSegmentSchema
>;
export type ResearchSentence = z.infer<typeof ResearchSentenceSchema>;
export type ResearchDisplayBlock = z.infer<
  typeof ResearchDisplayBlockSchema
>;
export type ResearchEvidence = z.infer<typeof ResearchEvidenceSchema>;
export type ResearchItem = z.infer<typeof ResearchItemSchema>;
export type ResearchSection = z.infer<typeof ResearchSectionSchema>;
