import { withResearchContext, type ResearchContextQuery } from "../model/research-context";
import {
  AccountDetailResponseSchema,
  type AccountDetail,
} from "../model/account-detail";
import { openAiAccountDetailFixture } from "./account-detail.fixture";
import { zafranAccountDetailFixture } from "./zafran/account";
import { fetchRead } from "./frontend-api";
import { accountsFixtureMode } from "./repository-mode";

export interface AccountDetailsRepository {
  get(accountId: string, context?: ResearchContextQuery): Promise<AccountDetail | null>;
}

export const fixtureAccountDetailsRepository: AccountDetailsRepository = {
  async get(accountId) {
    const account = [
      openAiAccountDetailFixture,
      zafranAccountDetailFixture,
    ].find((candidate) => candidate.id === accountId);
    if (!account) return null;

    return AccountDetailResponseSchema.parse({
      data: account,
    }).data;
  },
};

/**
 * The live account detail: `GET /frontend/v1/accounts/{id}` → `{data}`.
 *
 * `ACCOUNT_NOT_FOUND` is the one 404 that means "no such account"; `fetchRead`
 * turns it into `null` and every other failure into a `ClueApiError`, so a
 * wrong mount or a disabled read surface never renders as an empty account.
 */
export function createHttpAccountDetailsRepository(
  read: typeof fetchRead = fetchRead,
): AccountDetailsRepository {
  return {
    async get(accountId, context) {
      const body = await read(withResearchContext(`/accounts/${encodeURIComponent(accountId)}`, context), {
        recordNotFoundAllowed: true,
      });
      if (body === null) return null;
      return AccountDetailResponseSchema.parse(body).data;
    },
  };
}

export async function getAccountDetails(
  accountId: string,
  read: typeof fetchRead = fetchRead,
  context?: ResearchContextQuery,
): Promise<AccountDetail | null> {
  const repository = accountsFixtureMode()
    ? fixtureAccountDetailsRepository
    : createHttpAccountDetailsRepository(read);

  return repository.get(accountId, context);
}
