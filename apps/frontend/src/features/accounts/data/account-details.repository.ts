import {
  AccountDetailResponseSchema,
  type AccountDetail,
} from "../model/account-detail";
import { openAiAccountDetailFixture } from "./account-detail.fixture";

export interface AccountDetailsRepository {
  get(accountId: string): Promise<AccountDetail | null>;
}

export const fixtureAccountDetailsRepository: AccountDetailsRepository = {
  async get(accountId) {
    if (accountId !== openAiAccountDetailFixture.id) {
      return null;
    }

    return AccountDetailResponseSchema.parse({
      data: openAiAccountDetailFixture,
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
  const apiBaseUrl = process.env.CLUE_API_BASE_URL;
  const repository = apiBaseUrl
    ? createHttpAccountDetailsRepository(apiBaseUrl)
    : fixtureAccountDetailsRepository;

  return repository.get(accountId);
}
