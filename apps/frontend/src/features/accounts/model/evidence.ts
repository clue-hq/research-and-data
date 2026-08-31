import { z } from "zod";
import { FreshnessSchema, IsoTimestampSchema } from "./vocabulary";

/** A public evidence URL must be browser-safe. The backend applies the same http(s)-only rule. */
export const SafePublicEvidenceUrlSchema = z
  .string()
  .url()
  .refine((value) => {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      !parsed.username &&
      !parsed.password
    );
  }, "public evidence URLs must use http or https without embedded credentials");

/** One display-approved evidence record mapped to the exact claim and field it supports. */
export const EvidenceReferenceSchema = z.object({
  claimId: z.string().min(1),
  fieldKey: z.string().min(1),
  /** Registered source identity; null when the substrate has no truthful title. */
  sourceTitle: z.string().min(1).nullable().default(null),
  provider: z.string().min(1).nullable().default(null),
  sourceUrl: SafePublicEvidenceUrlSchema.nullable().default(null),
  evidenceSpan: z.string().min(1).nullable().default(null),
  confidence: z.number().min(0).max(1),
  freshness: FreshnessSchema.nullable().default(null),
  observedAt: IsoTimestampSchema,
  /** The action URL is derived locally; no storage locator crosses the wire. */
  protectedArtifactAvailable: z.boolean().default(false),
});

export type EvidenceReference = z.infer<typeof EvidenceReferenceSchema>;

/** The displayed source label is the exact href, so precision can never drift. */
export function exactEvidenceSourceLabel(sourceUrl: string): string {
  return sourceUrl;
}

export function accountEvidenceArtifactHref(
  accountId: string,
  claimId: string,
): string {
  return `/api/clue/frontend/v1/accounts/${encodeURIComponent(accountId)}/evidence/${encodeURIComponent(claimId)}`;
}

export function contactEvidenceArtifactHref(
  accountId: string,
  contactId: string,
  claimId: string,
): string {
  return `/api/clue/frontend/v1/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}/evidence/${encodeURIComponent(claimId)}`;
}
