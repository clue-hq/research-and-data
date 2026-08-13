"use server";

import {
  readAccountsResult,
  type AccountsReadResult,
} from "./accounts-read-result";

/**
 * Fetches one numbered page for the Accounts table.
 *
 * The repositories read server-only configuration (the base URL and the
 * workspace header), so the browser cannot call them directly. This server
 * action is the one seam that lets a client controller ask for more rows
 * without moving transport concerns — or the workspace id — into the browser.
 *
 * Page and page size are sent through the server-only repository; workspace
 * identity and provider proof never move into the browser.
 */
export async function loadAccountsPage(
  page: number,
  limit: number,
): Promise<AccountsReadResult> {
  return readAccountsResult({ page, limit });
}
