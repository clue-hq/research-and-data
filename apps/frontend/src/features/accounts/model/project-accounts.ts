import { z } from "zod";
import { AccountBulkCapabilitiesSchema } from "./bulk-actions";
import { AccountSchema, type Account } from "./account";

/**
 * The workspace person, as a parse contract.
 *
 * The design build read this off `SettingsWorkspace["profile"]`. The platform
 * has no settings feature, so the person is derived from the protected session
 * by `data/workspace-profile.repository.ts`; `model/workspace-profile.ts` owns
 * the TypeScript shape and this is that same shape, field for field, so the BFF
 * response can be parsed on the browser side.
 */
export const WorkspaceProfileSchema = z.object({
  id: z.string().optional(),
  avatarUrl: z.string().optional(),
  fullName: z.string(),
  displayName: z.string(),
  initials: z.string(),
  avatarColor: z.string(),
});

/**
 * `bulkCapabilities` is not in the design build's response: there the table's
 * bulk actions were always available. Here they are a server-declared, fail-
 * closed page capability (`data/bulk-capabilities.repository.ts`), and the
 * project table's controller needs them alongside the rows.
 */
export const ProjectAccountsResponseSchema = z.object({
  accounts: z.array(AccountSchema),
  availableAccounts: z.array(AccountSchema),
  profile: WorkspaceProfileSchema,
  bulkCapabilities: AccountBulkCapabilitiesSchema,
});

export type ProjectAccountsResponse = z.infer<typeof ProjectAccountsResponseSchema>;
export const accountPageSizes = [25, 50, 100] as const;
export type AccountPageSize = typeof accountPageSizes[number];

export function accountsForProject(accounts: Account[], projectId: string) {
  return accounts.filter((account) => account.projects.some((project) => project.id === projectId));
}

/** Call after project scoping, search, filters and sort. */
export function paginateAccounts(accounts: Account[], requestedPage: number, pageSize: AccountPageSize) {
  const total = accounts.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(1, requestedPage), pageCount);
  const offset = (page - 1) * pageSize;
  return {
    accounts: accounts.slice(offset, offset + pageSize),
    end: Math.min(offset + pageSize, total),
    page,
    pageCount,
    start: total ? offset + 1 : 0,
    total,
  };
}
