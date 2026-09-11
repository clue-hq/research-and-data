import { getAccounts, type AccountsQuery, type AccountsRepository } from "./accounts.repository";
import { accountsForProject } from "../model/project-accounts";
import type { Account } from "../model/account";

// Browser pagination operates on the complete result, even when the HTTP
// adapter behind the directory supplies cursor pages.
export async function readAccountDirectory(query: AccountsQuery = {}, list: AccountsRepository["list"] = getAccounts) {
  const rows = new Map<string, Account>();
  const cursors = new Set<string>();
  let cursor: string | undefined;
  do {
    const result = await list({ ...query, limit: 100, cursor });
    result.data.forEach((account) => rows.set(account.id, account));
    cursor = result.meta.nextCursor ?? undefined;
    if (cursor && cursors.has(cursor)) throw new Error("Accounts API repeated a pagination cursor");
    if (cursor) cursors.add(cursor);
  } while (cursor);
  return [...rows.values()];
}

export async function getProjectAccountDirectory(projectId: string) {
  const [projectRows, directory] = await Promise.all([
    readAccountDirectory({ projectId }),
    readAccountDirectory(),
  ]);
  const accounts = accountsForProject(projectRows, projectId);
  const memberIds = new Set(accounts.map(({ id }) => id));
  return { accounts, availableAccounts: directory.filter(({ id }) => !memberIds.has(id)) };
}
