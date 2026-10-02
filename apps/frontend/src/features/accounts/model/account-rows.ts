import type { Account } from "./account";
import { isLocalDraftAccount, type AccountRow } from "./create-account";

/** Refresh persisted rows from the server while retaining this tab's unsaved drafts. */
export function reconcileAccountRows(
  current: readonly AccountRow[],
  served: readonly Account[],
): AccountRow[] {
  const servedIds = new Set(served.map(({ id }) => id));
  return [
    ...current.filter((row) => isLocalDraftAccount(row) && !servedIds.has(row.id)),
    ...served,
  ];
}
