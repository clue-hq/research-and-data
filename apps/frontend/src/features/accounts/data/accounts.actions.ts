"use server";

import {
  readAccountsResult,
  type AccountsReadResult,
} from "./accounts-read-result";
import type { AccountsQuery } from "./accounts.repository";
import { getAccountContact } from "./account-contacts.repository";
import { ResearchContextQuerySchema, type ResearchContextQuery } from "../model/research-context";
import type { AccountContactDetail } from "../model/account-contact";

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

/**
 * Loads one contact's detail for the contacts-table preview drawer.
 *
 * Same seam, same reason as `loadAccountsPage`: the repositories read
 * server-only configuration, so the browser cannot call them. The drawer opens
 * on a row click and asks for that row's contact — there is no featured contact
 * chosen ahead of time (source map §6).
 */
export async function loadAccountContact(
  accountId: string,
  contactId: string,
  context?: ResearchContextQuery,
): Promise<AccountContactDetail | null> {
  return getAccountContact(accountId, contactId, undefined, ResearchContextQuerySchema.parse(context ?? {}));
}
