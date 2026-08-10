"use server";

import type { AccountsResponse } from "../model/account";
import { getAccounts } from "./accounts.repository";

/**
 * Fetches the next keyset page for the accounts table.
 *
 * The repositories read server-only configuration (the base URL and the
 * workspace header), so the browser cannot call them directly. This server
 * action is the one seam that lets a client controller ask for more rows
 * without moving transport concerns — or the workspace id — into the browser.
 *
 * The cursor is opaque and is passed straight back to the endpoint that issued
 * it; a cursor this API did not mint is a `400`, never a silent restart.
 */
export async function loadMoreAccounts(
  cursor: string,
): Promise<AccountsResponse> {
  return getAccounts({ cursor });
}
