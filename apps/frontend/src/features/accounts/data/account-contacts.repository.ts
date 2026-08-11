import {
  AccountContactDetailSchema,
  AccountContactsResponseSchema,
  type AccountContactDetail,
  type AccountContactSummary,
} from "../model/account-contact";
import { fetchRead } from "./frontend-api";

export interface AccountContactsRepository {
  list(accountId: string): Promise<AccountContactSummary[]>;
  get(
    accountId: string,
    contactId: string,
  ): Promise<AccountContactDetail | null>;
}

/**
 * Both contact endpoints follow a merged account silently and serve the
 * survivor's committee. An empty committee is a `200` with an empty list, not a
 * `404` — the governed committee reads M8D research references whose production
 * writer can legitimately produce no eligible members, so live data may be
 * empty and is proven through backend contract tests rather than UI fixtures.
 */
export function createHttpAccountContactsRepository(
  read: typeof fetchRead = fetchRead,
): AccountContactsRepository {
  return {
    async list(accountId) {
      // The contacts list has no domain 404 either: an account with no
      // committee is a 200 with an empty list. An unknown account id is the one
      // record-level case, so it is allowed to resolve to an empty table.
      const body = await read(
        `/accounts/${encodeURIComponent(accountId)}/contacts`,
        { recordNotFoundAllowed: true },
      );
      if (body === null) return [];
      return AccountContactsResponseSchema.parse(body).data;
    },
    async get(accountId, contactId) {
      const body = await read(
        `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}`,
        { recordNotFoundAllowed: true },
      );
      // A single resource: the profile object itself, no `data` wrapper.
      return body === null ? null : AccountContactDetailSchema.parse(body);
    },
  };
}

export function getAccountContacts(accountId: string) {
  return createHttpAccountContactsRepository().list(accountId);
}

export function getAccountContact(accountId: string, contactId: string) {
  return createHttpAccountContactsRepository().get(accountId, contactId);
}
