import { getAccounts, type AccountsQuery, type AccountsRepository } from "./accounts.repository";
import { accountsForProject } from "../model/project-accounts";

/**
 * The whole list the browser paginates over.
 *
 * Browser pagination operates on the complete result, and the list read is
 * already that whole result: the HTTP adapter follows the backend's cursor
 * pages itself, up to `ACCOUNTS_PAGE_CAP` × `ACCOUNTS_PAGE_LIMIT` rows, and
 * returns `meta.nextCursor: null`. So there is no second cursor loop here —
 * one call is the read.
 */
export async function readAccountDirectory(query: AccountsQuery = {}, list: AccountsRepository["list"] = getAccounts) {
  return (await list(query)).data;
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
