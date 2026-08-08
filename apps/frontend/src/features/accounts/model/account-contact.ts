import { z } from "zod";
import {
  IsoTimestampSchema,
  JsonValueSchema,
  PersonaSchema,
  type Persona,
} from "./vocabulary";

/**
 * Presentation-only persona tone. It is a frontend display decision (D-5) and
 * never leaves or enters the wire.
 */
export const ContactPersonaToneSchema = z.enum([
  "olive",
  "orange",
  "blue",
  "cyan",
  "green",
  "pink",
  "red",
]);

export type ContactPersonaTone = z.infer<typeof ContactPersonaToneSchema>;

const personaTones: Record<Persona, ContactPersonaTone> = {
  champion: "green",
  economic_buyer: "orange",
  technical_evaluator: "blue",
  blocker: "red",
};

const personaLabels: Record<Persona, string> = {
  champion: "Champion",
  economic_buyer: "Economic buyer",
  technical_evaluator: "Technical evaluator",
  blocker: "Blocker",
};

export function contactPersonaTone(persona: Persona): ContactPersonaTone {
  return personaTones[persona] ?? "olive";
}

export function contactPersonaLabel(persona: Persona): string {
  return personaLabels[persona] ?? persona;
}

/**
 * The committee role with the confidence behind it — the real signal that the
 * fixture-era `influence` band was standing in for.
 */
export const RoleOnCommitteeSchema = z.object({
  value: z.string(),
  confidence: z.number().nullable().default(null),
});

/**
 * How many signal TYPES currently hold a display-eligible statement.
 *
 * Bounded by a two-family whitelist, so a list-valued field with five items
 * still counts 1. Label it as signal types, never as a count of items.
 */
export const ContactSignalsSchema = z.object({
  typeCount: z.number().int().nonnegative().default(0),
});

/**
 * One contacts-table row.
 *
 * `titleRestricted` marks a display-denied value: the field is served absent
 * with the marker and with no provenance, while a field the backend simply does
 * not hold is absent and unmarked. Absence and redaction are different answers.
 */
export const AccountContactSummarySchema = z.object({
  id: z.string(),
  name: z.string().nullable().default(null),
  title: z.string().nullable().default(null),
  titleRestricted: z.boolean().default(false),
  persona: PersonaSchema,
  roleOnCommittee: RoleOnCommitteeSchema,
  linkedinUrl: z.string().nullable().default(null),
  projectIds: z.array(z.string()).default([]),
  signals: ContactSignalsSchema.default({ typeCount: 0 }),
});

/** A professional fact on the contact profile, with the same redaction marker. */
export const GovernedFactSchema = z.object({
  fieldKey: z.string(),
  value: JsonValueSchema.nullable().default(null),
  observedAt: IsoTimestampSchema.nullable().default(null),
  provider: z.string().nullable().default(null),
  restricted: z.boolean().default(false),
});

/** A non-link evidence chip: provider and time only — evidence URLs stay off this wire (G4). */
export const ContactEvidenceSchema = z.object({
  provider: z.string(),
  observedAt: IsoTimestampSchema.nullable().default(null),
});

/**
 * `GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` — the object
 * itself, no `data` wrapper.
 *
 * `redirectedFrom` tracks a merged **contact** only. A merged account id is
 * followed silently, so a client that wants to correct a stale account link
 * must compare `accountId` with the id it asked for.
 */
export const AccountContactDetailSchema = AccountContactSummarySchema.extend({
  accountId: z.string(),
  accountName: z.string().nullable().default(null),
  professionalFacts: z.array(GovernedFactSchema).default([]),
  evidence: z.array(ContactEvidenceSchema).default([]),
  redirectedFrom: z.string().nullable().default(null),
});

export const AccountContactsResponseSchema = z.object({
  data: z.array(AccountContactSummarySchema),
  meta: z
    .object({ total: z.number().int().nonnegative() })
    .default({ total: 0 }),
});

export type AccountContactDetail = z.infer<typeof AccountContactDetailSchema>;
export type AccountContactSummary = z.infer<typeof AccountContactSummarySchema>;
export type ContactEvidence = z.infer<typeof ContactEvidenceSchema>;
export type GovernedFact = z.infer<typeof GovernedFactSchema>;
export type RoleOnCommittee = z.infer<typeof RoleOnCommitteeSchema>;
