import { z } from "zod";
import { CRM_PROVIDER_NAMES, CrmProviderSchema, type CrmProvider } from "./crm";

/**
 * The CRM write permission card (CRM integration Phase 2; card spec
 * docs/superpowers/specs/crm-integration/2026-10-22-crm-write-permission-card-design.md).
 *
 * The card is drawn from the gate's immutable snapshot (`card_snapshot` in
 * `platform/api/clue_api/crm/write_prepare.py`, snake_case like every stored snapshot); its
 * progress after Allow from `GET /frontend/v1/crm/proposals/{id}` (camelCase, like the rest of
 * the read API). The asking-state wording (group titles, "Always allow" phrases, the overwrite
 * heading) is the server's own and is shown as sent; this module writes only what the server does
 * not: the progress and done lines, the record captions and the button labels.
 */

export const CRM_WRITE_GATE_KIND = "crm_write_permission";

const RecordSchema = z.object({
  write_id: z.string().min(1),
  record_ref: z.string().nullable().default(null),
  name: z.string(),
  before: z.unknown().optional(),
  after: z.unknown().optional(),
});

const GroupSchema = z.object({
  kind: z.string(),
  object: z.string(),
  field: z.string().nullable().default(null),
  field_label: z.string().nullable().default(null),
  list_ref: z.string().nullable().default(null),
  title: z.string(),
  count: z.number().int(),
  value_summary: z.string().nullable().default(null),
  reason: z.string().default(""),
  records: z.array(RecordSchema).min(1),
  scope_key: z.string(),
  always_allow: z.string(),
});

const OverwriteSchema = z.object({
  write_id: z.string().min(1),
  name: z.string(),
  field: z.string().nullable().default(null),
  field_label: z.string().nullable().default(null),
  before: z.unknown().optional(),
  after: z.unknown().optional(),
  set_by_text: z.string().nullable().default(null),
  reason: z.string().default(""),
});

const CrmWriteSnapshotSchema = z.object({
  crm: CrmProviderSchema,
  project_name: z.string().default(""),
  title: z.string(),
  description: z.string(),
  groups: z.array(GroupSchema),
  overwrites_heading: z.string().nullable().default(null),
  overwrites: z.array(OverwriteSchema).default([]),
  standing_permissions: z
    .array(z.object({ scope_key: z.string(), phrase: z.string() }))
    .default([]),
  caption: z.string().default("Any member of this workspace can answer."),
});

export interface CrmWriteRecord {
  writeId: string;
  name: string;
  /** "Lead → Opportunity" when the record's own change differs from the group summary. */
  change: string | null;
}

export interface CrmWriteGroup {
  kind: string;
  object: string;
  fieldLabel: string | null;
  listRef: string | null;
  title: string;
  valueSummary: string | null;
  reason: string;
  records: readonly CrmWriteRecord[];
  alwaysAllowPhrase: string;
}

export interface CrmWriteOverwrite {
  writeId: string;
  /** "Acme Hotels · Lifecycle stage: Lead → Opportunity" */
  line: string;
  setByText: string;
  reason: string;
}

export interface CrmWriteCardModel {
  provider: CrmProvider;
  providerName: string;
  title: string;
  description: string;
  caption: string;
  groups: readonly CrmWriteGroup[];
  overwritesHeading: string | null;
  overwrites: readonly CrmWriteOverwrite[];
  standingPermissions: readonly { scopeKey: string; label: string }[];
}

/** The ticked changes, by write id. */
export type CrmWriteSelection = ReadonlySet<string>;

function display(value: unknown): string {
  if (value === null || value === undefined) return "Empty";
  if (typeof value === "string") return value.trim() === "" ? "Empty" : value;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function change(before: unknown, after: unknown): string {
  return `${display(before)} → ${display(after)}`;
}

/** The card from the gate's snapshot; `null` when the snapshot is not a write card. */
export function crmWriteCard(snapshot: unknown): CrmWriteCardModel | null {
  const parsed = CrmWriteSnapshotSchema.safeParse(snapshot);
  if (!parsed.success) return null;
  const card = parsed.data;
  return {
    provider: card.crm,
    providerName: CRM_PROVIDER_NAMES[card.crm],
    title: card.title,
    description: card.description,
    caption: card.caption,
    groups: card.groups.map((group) => {
      // A record's own change is shown only when the group's records do not all make the same one.
      const changes =
        group.field === null
          ? null
          : group.records.map((record) => change(record.before, record.after));
      const varied = changes !== null && new Set(changes).size > 1;
      return {
        kind: group.kind,
        object: group.object,
        fieldLabel: group.field_label,
        listRef: group.list_ref,
        title: group.title,
        valueSummary: group.value_summary,
        reason: group.reason,
        records: group.records.map((record, index) => ({
          writeId: record.write_id,
          name: record.name,
          change: varied ? (changes?.[index] ?? null) : null,
        })),
        alwaysAllowPhrase: group.always_allow,
      };
    }),
    overwritesHeading: card.overwrites.length > 0 ? card.overwrites_heading : null,
    overwrites: card.overwrites.map((item) => ({
      writeId: item.write_id,
      line: `${item.name} · ${item.field_label ?? item.field ?? "Field"}: ${change(item.before, item.after)}`,
      setByText: item.set_by_text ?? "Who set it isn't known",
      reason: item.reason,
    })),
    standingPermissions: card.standing_permissions.map((permission) => ({
      scopeKey: permission.scope_key,
      label: `Always allow ${permission.phrase}`,
    })),
  };
}

/** The proposal a card's gate stands for (`subject_ref` is `crm_write_proposal:<id>`). */
export function crmProposalIdOf(subjectRef: string | null): string | null {
  const match = /^crm_write_proposal:([0-9a-f-]{36})$/.exec(subjectRef ?? "");
  return match?.[1] ?? null;
}

// --- the person's choices ------------------------------------------------

/** Every grouped change ticked; every overwrite of a person's value unticked (R-6.5). */
export function initialSelection(card: CrmWriteCardModel): CrmWriteSelection {
  return new Set(card.groups.flatMap((group) => group.records.map((record) => record.writeId)));
}

export function toggleRecord(selection: CrmWriteSelection, writeId: string): CrmWriteSelection {
  const next = new Set(selection);
  if (next.has(writeId)) next.delete(writeId);
  else next.add(writeId);
  return next;
}

export type GroupTickState = "all" | "some" | "none";

export function groupTickState(group: CrmWriteGroup, selection: CrmWriteSelection): GroupTickState {
  const ticked = group.records.filter((record) => selection.has(record.writeId)).length;
  if (ticked === 0) return "none";
  return ticked === group.records.length ? "all" : "some";
}

/** A fully ticked group unticks every record; a partial or empty one ticks them all. */
export function toggleGroup(selection: CrmWriteSelection, group: CrmWriteGroup): CrmWriteSelection {
  const next = new Set(selection);
  const tickAll = groupTickState(group, selection) !== "all";
  for (const record of group.records) {
    if (tickAll) next.add(record.writeId);
    else next.delete(record.writeId);
  }
  return next;
}

export function selectedCount(selection: CrmWriteSelection): number {
  return selection.size;
}

export interface CrmWriteAnswer {
  selected_write_ids: string[];
  always_allow: string[];
}

/**
 * The Allow answer: the ticked changes in the card's own order, and the "Always allow" scopes the
 * card offered and the person ticked. The server proves both again.
 */
export function crmWriteAnswer(
  card: CrmWriteCardModel,
  selection: CrmWriteSelection,
  alwaysAllow: ReadonlySet<string>,
): CrmWriteAnswer {
  const order = [
    ...card.groups.flatMap((group) => group.records.map((record) => record.writeId)),
    ...card.overwrites.map((item) => item.writeId),
  ];
  return {
    selected_write_ids: order.filter((writeId) => selection.has(writeId)),
    always_allow: card.standingPermissions
      .map((permission) => permission.scopeKey)
      .filter((scope) => alwaysAllow.has(scope)),
  };
}

// --- wording (card spec §3, §5) ------------------------------------------

const NOUNS: Readonly<Record<string, readonly [string, string]>> = {
  company: ["company", "companies"],
  account: ["account", "accounts"],
  contact: ["contact", "contacts"],
  lead: ["lead", "leads"],
};

function noun(object: string, count: number): string {
  const [one, many] = NOUNS[object] ?? [object, `${object}s`];
  return count === 1 ? one : many;
}

function changes(count: number): string {
  return `${count} ${count === 1 ? "change" : "changes"}`;
}

/** The caption above an opened group's records: "48 contacts". */
export function crmWriteRecordsCaption(group: CrmWriteGroup): string {
  const count = group.records.length;
  const object = group.kind === "list_membership" || group.kind === "list_removal" ? "contact" : group.object;
  return `${count} ${noun(object, count)}`;
}

/**
 * The paused card's caption. A reconnect makes a new connection and Clue never sends changes
 * across connections, so the changes left are not sent after it (R-11.10); the wake turn
 * (write_executor.py `_stopped`) says the same to the agent.
 */
export function pausedCaption(providerName: string): string {
  return `If you reconnect ${providerName}, the changes not yet sent are not sent; Clue will propose them again.`;
}

export function allowLabel(count: number): string {
  return count > 0 ? `Allow ${count}` : "Allow";
}

export function sendingTitle(provider: CrmProvider, count: number): string {
  return `Sending ${changes(count)} to ${CRM_PROVIDER_NAMES[provider]}`;
}

export interface CrmWriteTally {
  chosen: number;
  done: number;
  failed: number;
  skipped: number;
  pending: number;
}

/** "58 done · 2 failed · 1 skipped" (zeros left out). */
export function countsLine(counts: Omit<CrmWriteTally, "chosen">): string {
  const parts = [
    counts.done ? `${counts.done} done` : null,
    counts.failed ? `${counts.failed} failed` : null,
    counts.skipped ? `${counts.skipped} skipped` : null,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(" · ") : "Nothing sent";
}

/** One group's line in the done state: "Set "ICP tier" on 10 of 12 companies". */
export function crmWriteDoneLine(
  provider: CrmProvider,
  group: CrmWriteGroup,
  tally: CrmWriteTally,
): string {
  const count = tally.done === tally.chosen ? `${tally.done}` : `${tally.done} of ${tally.chosen}`;
  const target = provider === "hubspot" ? "list" : "campaign";
  const people = noun("contact", tally.chosen);
  const things = noun(group.object, tally.chosen);
  switch (group.kind) {
    case "list_membership":
      return `Added ${count} ${people} to the ${target} "${group.listRef ?? ""}"`;
    case "list_removal":
      return `Removed ${count} ${people} from the ${target} "${group.listRef ?? ""}"`;
    case "field_update":
      return `Set "${group.fieldLabel ?? "a field"}" on ${count} ${things}`;
    case "create_contact":
      return `Created ${count} ${people}`;
    case "create_company":
      return `Created ${count} ${things}`;
    default:
      return `Marked ${count} possible ${tally.chosen === 1 ? "duplicate" : "duplicates"}`;
  }
}

/**
 * One group's done-state line and mark: ✓ when at least one change succeeded ("N of M"); ✕ with
 * the failed/skipped count when none did.
 */
export function crmWriteGroupOutcome(
  provider: CrmProvider,
  group: CrmWriteGroup,
  tally: CrmWriteTally,
): { mark: "done" | "failed"; line: string } {
  const line = crmWriteDoneLine(provider, group, tally);
  if (tally.done > 0) return { mark: "done", line };
  return { mark: "failed", line: `${line} — ${countsLine(tally)}` };
}

/** A plain message for a refused answer; the card stays as it was (card spec §4). */
export function crmWriteRefusal(code: string): string {
  switch (code) {
    case "CRM_CONNECTION_CHANGED":
      return "The CRM connection changed or expired, so these changes can't be sent. Reconnect it, and Clue will propose them again.";
    case "CRM_WRITE_NOTHING_SELECTED":
      return "Tick at least one change to allow.";
    case "CRM_WRITE_UNKNOWN_CHANGE":
      return "One of the ticked changes is no longer part of this proposal. Refresh and try again.";
    case "GATE_REPLACED":
      return "A newer proposal replaced this one.";
    case "GATE_SUBJECT_STALE":
      return "This card can no longer be answered. Clue will propose these changes again.";
    case "GATE_ALREADY_ANSWERED":
      return "Someone already answered this card.";
    default:
      return "We couldn't save your answer. Please try again.";
  }
}

// --- progress after the answer (card spec §3 B–F) -------------------------

const TallySchema = {
  done: z.number().int(),
  failed: z.number().int(),
  skipped: z.number().int(),
  pending: z.number().int(),
};

/** `GET /frontend/v1/crm/proposals/{id}` (`proposal_progress` in write_answer.py). */
export const CrmProposalProgressSchema = z.object({
  proposalId: z.string(),
  state: z.enum(["asking", "sending", "paused", "done", "declined", "replaced", "closed"]),
  provider: CrmProviderSchema.nullable(),
  counts: z.object(TallySchema),
  groups: z.array(
    z.object({
      title: z.string().nullable(),
      kind: z.string().nullable(),
      object: z.string().nullable(),
      fieldLabel: z.string().nullable(),
      count: z.number().int().nullable(),
      chosen: z.number().int(),
      ...TallySchema,
    }),
  ),
  overwrites: z.array(
    z.object({
      writeId: z.string(),
      label: z.string().nullable(),
      field: z.string().nullable(),
      status: z.string(),
    }),
  ),
  failed: z.array(
    z.object({
      writeId: z.string(),
      label: z.string().nullable(),
      field: z.string().nullable(),
      crmMessage: z.string().nullable(),
    }),
  ),
  skipped: z.array(
    z.object({ writeId: z.string(), label: z.string().nullable(), reason: z.string().nullable() }),
  ),
  answeredBy: z.string().nullable(),
  answeredByName: z.string().nullable(),
  answeredAt: z.string().nullable(),
});
export type CrmProposalProgress = z.infer<typeof CrmProposalProgressSchema>;

/** What the card shows. */
export type CrmWriteCardView =
  | "asking"
  | "sending"
  | "done"
  | "declined"
  | "replaced"
  | "closed"
  | "paused";

/**
 * The card's state from the durable gate (answered or not, withdrawn) and, once it was answered or
 * withdrawn, the proposal's progress. The gate decides whether the person answered; the progress
 * decides how far the sending got and why a withdrawn card was withdrawn.
 */
export function crmWriteCardView(
  gateState: "requested" | "responded" | "denied" | "withdrawn",
  progress: CrmProposalProgress | null,
): CrmWriteCardView {
  if (gateState === "requested") return "asking";
  if (gateState === "denied") return "declined";
  if (gateState === "withdrawn") return progress?.state === "closed" ? "closed" : "replaced";
  switch (progress?.state) {
    case "done":
    case "closed":
      return "done";
    case "paused":
      return "paused";
    default:
      return "sending";
  }
}

/** Polling goes on while the CRM is still being written to (or nothing was read yet). */
export function crmWriteProgressPending(progress: CrmProposalProgress | null): boolean {
  return progress === null || progress.state === "asking" || progress.state === "sending";
}

/** "Allowed by Aryan Keshri · 14:02" / "Declined by …". */
export function answeredLine(
  verb: "Allowed" | "Declined",
  name: string | null,
  at: string | null,
): string | null {
  const when = at === null ? null : new Date(at);
  const time =
    when === null || Number.isNaN(when.getTime())
      ? null
      : when.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (name && time) return `${verb} by ${name} · ${time}`;
  if (name) return `${verb} by ${name}`;
  return time ? `${verb} · ${time}` : null;
}
