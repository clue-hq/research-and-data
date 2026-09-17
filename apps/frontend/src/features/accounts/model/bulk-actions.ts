import { z } from "zod";
import type { AccountRow } from "./create-account";

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

/**
 * The table has exactly two bulk actions — add to project and add to chat
 * (founder ruling b) — so a bulk item carries no email-lookup payload. The
 * single-contact lookup is its own contract in `contact-email-lookup.ts`.
 */
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
    }),
  ),
});

export type AccountBulkCapabilities = z.infer<
  typeof AccountBulkCapabilitiesSchema
>;
export type BulkActionResponse = z.infer<typeof BulkActionResponseSchema>;
export type BulkProjectOption = z.infer<typeof BulkProjectOptionSchema>;

/**
 * The one-line result the operator reads after an add-to-project.
 *
 * It is assembled from the server's own counts — a partially applied action
 * says so, and a zero-count clause is omitted rather than printed as "0".
 */
export function addToProjectNotice(
  counts: BulkActionResponse["counts"],
): string {
  return [
    counts.completed ? `${counts.completed} added` : null,
    counts.unchanged ? `${counts.unchanged} already in project` : null,
    counts.ineligible ? `${counts.ineligible} ineligible` : null,
    counts.failed ? `${counts.failed} failed` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Reflect a completed add-to-project onto the rows in hand.
 *
 * Only the subjects the server actually placed in the project (`completed`) or
 * found already there (`unchanged`) gain the membership; a failed or ineligible
 * subject is left exactly as it was. The table is not re-read, so this is the
 * one place the visible rows learn about the change.
 */
export function reflectAddToProject(
  accounts: readonly AccountRow[],
  // The membership a row gains is an id and a name; the option's `status` is a
  // picker concern. Taking only those two lets a screen that already knows its
  // project (the project Target accounts tab) reflect without inventing one.
  project: Pick<BulkProjectOption, "id" | "name">,
  result: BulkActionResponse,
): AccountRow[] {
  const reflected = new Set(
    result.items
      .filter((item) => item.outcome === "completed" || item.outcome === "unchanged")
      .map((item) => item.subjectId),
  );

  return accounts.map((account) =>
    !reflected.has(account.id) ||
    account.projects.some((membership) => membership.id === project.id)
      ? account
      : {
          ...account,
          projects: [...account.projects, { id: project.id, name: project.name }],
          primaryProjectId: account.primaryProjectId ?? project.id,
        },
  );
}
