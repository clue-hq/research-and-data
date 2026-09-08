"use server";

import {
  readAccountsResult,
  type AccountsReadResult,
} from "./accounts-read-result";
import type { AccountsQuery } from "./accounts.repository";

/**
 * Fetches one more slice of the Accounts table.
 *
 * The repositories read server-only configuration (the fixture switch today,
 * the base URL and workspace header once the live adapter lands), so the
 * browser cannot call them directly. This server action is the one seam that
 * lets a client controller ask for more rows without moving transport concerns
 * — or the workspace id — into the browser.
 *
 * The query vocabulary is the read contract's own (cursor + limit). The
 * page-numbered form left with the Band-2 pagination view in the D4 re-lift;
 * D4 Task 4 owns the live query this forwards.
 */
export async function loadAccountsPage(
  query: AccountsQuery,
): Promise<AccountsReadResult> {
  return readAccountsResult(query);
}
