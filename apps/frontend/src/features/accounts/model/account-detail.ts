import { z } from "zod";
import {
  AddedViaSchema,
  FreshnessSchema,
  IsoTimestampSchema,
  JsonValueSchema,
  PersonaSchema,
} from "./vocabulary";
import { ProseReadSchema } from "./prose";
import { EvidenceReferenceSchema } from "./evidence";

/**
 * A project-neutral fact about the account: whatever the merge currently holds.
 *
 * `fieldKey` is the field registry's key (`core.employee_count`, a pack's
 * `<pack>.*`, …) and `value` is the writer's opaque JSON. The frontend renders
 * these generically off `fieldKey`, so a new industry-pack field appears with
 * no schema change and no adapter change (FI-1 D-7).
 */
export const NeutralFactSchema = z.object({
  fieldKey: z.string(),
  value: JsonValueSchema,
  freshness: FreshnessSchema.nullable().default(null),
  /** The claim's observed time, falling back to its collection time. */
  observedAt: IsoTimestampSchema.nullable().default(null),
  /** The raw backend source key (`clearbit`, `sumble`, …) — no display-name surface exists yet. */
  provider: z.string().nullable().default(null),
  evidence: EvidenceReferenceSchema,
});

/** A project-relative fact: an insight or a value narrative inside one project section. */
export const RelativeFactSchema = z.object({
  fieldKey: z.string(),
  value: JsonValueSchema,
  observedAt: IsoTimestampSchema.nullable().default(null),
  provider: z.string().nullable().default(null),
  evidence: EvidenceReferenceSchema,
});

/** A score inside a project section — the project is the section, so it is not repeated. */
export const ProjectSectionScoreSchema = z.object({
  fit: z.number().nullable().default(null),
  intent: z.number().nullable().default(null),
  icpKey: z.string().nullable().default(null),
  icpVersion: z.number().int().nullable().default(null),
  scoredAt: IsoTimestampSchema.nullable().default(null),
});

/**
 * One project's slice of the account's research.
 *
 * `projectId: null` is the unattributed bucket (claims whose run maps to no
 * project), always served last. `addedVia`/`addedAt`/`name` are independently
 * nullable — a project that produced research without a membership row is
 * reported rather than hidden. A project with a membership and no work still
 * gets an empty section, because "targeted, nothing produced yet" is real.
 */
export const AccountProjectSectionSchema = z.object({
  projectId: z.string().nullable().default(null),
  name: z.string().nullable().default(null),
  addedVia: AddedViaSchema.nullable().default(null),
  addedAt: IsoTimestampSchema.nullable().default(null),
  scores: z.array(ProjectSectionScoreSchema).default([]),
  /** Plural: value narratives are written one per persona. */
  narratives: z.array(RelativeFactSchema).default([]),
  insights: z.array(RelativeFactSchema).default([]),
});

export const CommitteeMemberSchema = z.object({
  contactId: z.string(),
  name: z.string().nullable().default(null),
  persona: PersonaSchema,
  /** An open string on the wire, not the persona enum. */
  roleOnCommittee: z.string().nullable().default(null),
  projectIds: z.array(z.string()).default([]),
});

/**
 * Coverage counters.
 *
 * `researchedFieldCount` counts the distinct fields holding at least one live,
 * non-rejected claim from ANY writer — it is "how many fields do we hold a
 * value for", not research progress, and it has no denominator. The honest
 * research-side companion is `unresolvedFieldKeys`: fields research asked for
 * and could not answer. `unresolvedFields` adds the effective registry's
 * description without replacing the legacy key list.
 */
export const UnresolvedFieldSchema = z.object({
  fieldKey: z.string(),
  description: z.string().nullable().default(null),
});

export const AccountCoverageSchema = z.object({
  researchedFieldCount: z.number().int().nonnegative().default(0),
  unresolvedFieldKeys: z.array(z.string()).default([]),
  unresolvedFields: z.array(UnresolvedFieldSchema).default([]),
});

/**
 * `GET /frontend/v1/accounts/{accountId}` — the object itself, no `data` wrapper.
 *
 * The detail carries NO research status: status is an `(account, project)` fact
 * served on the list row.
 */
export const AccountDetailSchema = z.object({
  id: z.string(),
  name: z.string(),
  domain: z.string().nullable().default(null),
  aliases: z.array(z.string()).default([]),
  // Opaque backend payload like the other pass-through blobs: the values are
  // whatever the identity writer recorded, so they are not narrowed to strings.
  registryIds: z.record(z.string(), JsonValueSchema).default({}),
  hqGeo: z.record(z.string(), JsonValueSchema).nullable().default(null),
  /** Set when a merged loser's id was requested and this survivor was served. */
  redirectedFrom: z.string().nullable().default(null),
  summary: ProseReadSchema.default({
    state: "not_composed",
    paragraphs: [],
    researchOutcome: null,
  }),
  neutralFacts: z.array(NeutralFactSchema).default([]),
  projectSections: z.array(AccountProjectSectionSchema).default([]),
  committee: z.array(CommitteeMemberSchema).default([]),
  coverage: AccountCoverageSchema.default({
    researchedFieldCount: 0,
    unresolvedFieldKeys: [],
    unresolvedFields: [],
  }),
});

export type AccountCoverage = z.infer<typeof AccountCoverageSchema>;
export type AccountDetail = z.infer<typeof AccountDetailSchema>;
export type AccountProjectSection = z.infer<typeof AccountProjectSectionSchema>;
export type CommitteeMember = z.infer<typeof CommitteeMemberSchema>;
export type NeutralFact = z.infer<typeof NeutralFactSchema>;
export type RelativeFact = z.infer<typeof RelativeFactSchema>;
