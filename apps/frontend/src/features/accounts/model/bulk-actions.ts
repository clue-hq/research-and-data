import { z } from "zod";
import { ContactEmailLookupSchema } from "./contact-email-lookup";

export const BulkActionCapabilitySchema = z.object({
  allowed: z.boolean(),
  maxItems: z.number().int().positive(),
});

export const BulkProjectOptionSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: z.enum(["draft", "active"]),
});

export const AccountBulkCapabilitiesSchema = z.object({
  addToProject: BulkActionCapabilitySchema,
  addToChat: BulkActionCapabilitySchema,
  projects: z.array(BulkProjectOptionSchema).default([]),
});

export const ContactBulkCapabilitiesSchema = z.object({
  lookupWorkEmails: BulkActionCapabilitySchema,
  addToChat: BulkActionCapabilitySchema,
});

export const BulkActionOutcomeSchema = z.enum([
  "accepted",
  "completed",
  "unchanged",
  "not_found",
  "withheld",
  "ineligible",
  "failed_retryable",
  "failed_terminal",
]);

export const BulkActionResponseSchema = z.object({
  operationId: z.string(),
  state: z.enum(["pending", "completed", "partial", "failed"]),
  counts: z.object({
    requested: z.number().int().positive(),
    completed: z.number().int().nonnegative(),
    unchanged: z.number().int().nonnegative(),
    ineligible: z.number().int().nonnegative(),
    failed: z.number().int().nonnegative(),
  }),
  items: z.array(
    z.object({
      subjectId: z.string(),
      outcome: BulkActionOutcomeSchema,
      reasonCode: z.string().nullable().default(null),
      emailLookup: ContactEmailLookupSchema.nullable().default(null),
    }),
  ),
});

export type AccountBulkCapabilities = z.infer<
  typeof AccountBulkCapabilitiesSchema
>;
export type BulkActionResponse = z.infer<typeof BulkActionResponseSchema>;
export type BulkProjectOption = z.infer<typeof BulkProjectOptionSchema>;
export type ContactBulkCapabilities = z.infer<
  typeof ContactBulkCapabilitiesSchema
>;
