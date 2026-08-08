import {
  AccountDetailSchema,
  type AccountDetail,
} from "../model/account-detail";
import { openAiAccountDetailFixture } from "./account-detail.fixture";
import { apiBaseUrl, fetchRead } from "./frontend-api";

export interface AccountDetailsRepository {
  get(accountId: string): Promise<AccountDetail | null>;
}

export const fixtureAccountDetailsRepository: AccountDetailsRepository = {
  async get(accountId) {
    if (accountId !== openAiAccountDetailFixture.id) {
      return null;
    }

    return AccountDetailSchema.parse(openAiAccountDetailFixture);
  },
};

/**
 * The detail is a single resource: the backend returns the object itself, with
 * no `{data}` wrapper (only the two list endpoints use one). A merged loser's
 * id is followed to its survivor, with `redirectedFrom` naming what was asked
 * for; an unknown id is a `404`, which the transport turns into `null`.
 */
export function createHttpAccountDetailsRepository(): AccountDetailsRepository {
  return {
    async get(accountId) {
      const body = await fetchRead(`/accounts/${encodeURIComponent(accountId)}`, {
        recordNotFoundAllowed: true,
      });
      return body === null ? null : AccountDetailSchema.parse(body);
    },
  };
}

export async function getAccountDetails(
  accountId: string,
): Promise<AccountDetail | null> {
  const repository = apiBaseUrl()
    ? createHttpAccountDetailsRepository()
    : fixtureAccountDetailsRepository;

  return repository.get(accountId);
}
