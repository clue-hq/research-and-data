import { z } from "zod";
import { ProseReadSchema, type ProseRead } from "./prose";
import { IsoTimestampSchema } from "./vocabulary";

/** The closed event vocabulary emitted by the durable Account activity projection. */
export const AccountActivityKindSchema = z.enum([
  "research_view.updated",
  "research_view.section_stale",
  "research_view.recheck_completed",
]);

/** Human activity is withheld until the backend can resolve a durable actor identity. */
export const AccountActivityActorCategorySchema = z.enum([
  "system",
  "agent",
  "worker",
]);

export const AccountActivityReferenceSchema = z.object({
  target: z.enum(["account_insights", "contact_profile"]),
  eventId: z.string().min(1),
  snapshotId: z.string().min(1),
  reportId: z.string().min(1).nullable().default(null),
  sectionIds: z.array(z.string()).default([]),
  itemIds: z.array(z.string()).default([]),
});

export const AccountActivityEventSchema = z.object({
  id: z.string().min(1),
  kind: AccountActivityKindSchema,
  occurredAt: IsoTimestampSchema,
  actorCategory: AccountActivityActorCategorySchema,
  subject: z.object({
    type: z.enum(["account", "contact"]),
    id: z.string().min(1),
    name: z.string().min(1).nullable().default(null),
  }),
  project: z.object({
    id: z.string().min(1),
    name: z.string().min(1),
  }),
  projectRunId: z.string().min(1),
  accountRunId: z.string().min(1),
  reference: AccountActivityReferenceSchema,
});

export const AccountActivitySchema = z.object({
  accountId: z.string().min(1),
  state: z.object({
    committeeCount: z.number().int().nonnegative(),
    summary: ProseReadSchema,
  }),
  events: z.array(AccountActivityEventSchema),
});

export type AccountActivity = z.infer<typeof AccountActivitySchema>;
export type AccountActivityActorCategory = z.infer<
  typeof AccountActivityActorCategorySchema
>;
export type AccountActivityEvent = z.infer<typeof AccountActivityEventSchema>;
export type AccountActivityKind = z.infer<typeof AccountActivityKindSchema>;

const eventLabels: Record<AccountActivityKind, string> = {
  "research_view.updated": "Research view updated",
  "research_view.section_stale": "Research view needs review",
  "research_view.recheck_completed": "Research view recheck completed",
};

const actorLabels: Record<AccountActivityActorCategory, string> = {
  system: "Clue system",
  agent: "Research agent",
  worker: "Research worker",
};

export function accountActivityEventLabel(kind: AccountActivityKind): string {
  return eventLabels[kind];
}

export function accountActivityActorLabel(
  category: AccountActivityActorCategory,
): string {
  return actorLabels[category];
}

export function accountActivitySummaryLabel(summary: ProseRead): string {
  if (summary.state === "available") return "Summary available";
  return summary.state === "restricted"
    ? "Summary restricted"
    : "Summary not composed";
}

export function accountActivityEventHref(
  accountId: string,
  event: AccountActivityEvent,
): string {
  return event.reference.target === "contact_profile"
    ? `/accounts/${accountId}/contacts/${event.subject.id}`
    : `/accounts/${accountId}/insights`;
}

export function accountActivitySubjectLabel(event: AccountActivityEvent): string {
  if (event.subject.name) return event.subject.name;
  return event.subject.type === "contact" ? "Unnamed contact" : "Unnamed account";
}
