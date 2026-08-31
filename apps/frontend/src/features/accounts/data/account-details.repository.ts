import {
  AccountDetailSchema,
  type AccountDetail,
} from "../model/account-detail";
import { fetchRead } from "./frontend-api";

export interface AccountDetailsRepository {
  get(accountId: string): Promise<AccountDetail | null>;
}

/**
 * The detail is a single resource: the backend returns the object itself, with
 * no `{data}` wrapper (only the two list endpoints use one). A merged loser's
 * id is followed to its survivor, with `redirectedFrom` naming what was asked
 * for; an unknown id is a `404`, which the transport turns into `null`.
 */
export function createHttpAccountDetailsRepository(
  read: typeof fetchRead = fetchRead,
): AccountDetailsRepository {
  return {
    async get(accountId) {
      const body = await read(`/accounts/${encodeURIComponent(accountId)}`, {
        recordNotFoundAllowed: true,
      });
      return body === null ? null : AccountDetailSchema.parse(body);
    },
  };
}

export async function getAccountDetails(
  accountId: string,
): Promise<AccountDetail | null> {
  return createHttpAccountDetailsRepository().get(accountId);
}
