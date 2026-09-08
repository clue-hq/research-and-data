import {
  AccountDetailResponseSchema,
  type AccountDetail,
} from "../model/account-detail";
import { openAiAccountDetailFixture } from "./account-detail.fixture";
import { zafranAccountDetailFixture } from "./zafran/account";
import { accountsFixtureMode } from "./repository-mode";

export interface AccountDetailsRepository {
  get(accountId: string): Promise<AccountDetail | null>;
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

export function createHttpAccountDetailsRepository(
  apiBaseUrl: string,
): AccountDetailsRepository {
  return {
    async get(accountId) {
      const url = new URL(
        `/api/v1/accounts/${encodeURIComponent(accountId)}`,
        `${apiBaseUrl.replace(/\/$/, "")}/`,
      );
      const response = await fetch(url, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });

      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        throw new Error(
          `Account details API returned ${response.status} ${response.statusText}`,
        );
      }

      return AccountDetailResponseSchema.parse(await response.json()).data;
    },
  };
}

export async function getAccountDetails(
  accountId: string,
): Promise<AccountDetail | null> {
  const repository = accountsFixtureMode()
    ? fixtureAccountDetailsRepository
    : liveRepository();

  return repository.get(accountId);
}

/**
 * The live adapter lands in D4 Task 4 (the amended read contract). Until then
 * the live path refuses loudly: it must never silently fall back to fixtures.
 */
function liveRepository(): never {
  throw new Error("accounts live adapter lands in D4 Task 4");
}
