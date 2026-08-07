import {
  AccountWorkspaceResponseSchema,
  type AccountWorkspace,
} from "../model/account-workspace";
import { openAiWorkspaceFixture } from "./account-workspace.fixture";

export interface AccountWorkspaceRepository {
  get(accountId: string): Promise<AccountWorkspace | null>;
}

export const fixtureAccountWorkspaceRepository: AccountWorkspaceRepository = {
  async get(accountId) {
    if (accountId !== openAiWorkspaceFixture.accountId) return null;
    return AccountWorkspaceResponseSchema.parse({
      data: openAiWorkspaceFixture,
    }).data;
  },
};

export function createHttpAccountWorkspaceRepository(
  apiBaseUrl: string,
): AccountWorkspaceRepository {
  return {
    async get(accountId) {
      const url = new URL(
        `/api/v1/accounts/${encodeURIComponent(accountId)}/workspace`,
        `${apiBaseUrl.replace(/\/$/, "")}/`,
      );
      const response = await fetch(url, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (response.status === 404) return null;
      if (!response.ok) {
        throw new Error(`Account workspace API returned ${response.status}`);
      }
      return AccountWorkspaceResponseSchema.parse(await response.json()).data;
    },
  };
}

export async function getAccountWorkspace(
  accountId: string,
): Promise<AccountWorkspace | null> {
  const apiBaseUrl = process.env.CLUE_API_BASE_URL;
  const repository = apiBaseUrl
    ? createHttpAccountWorkspaceRepository(apiBaseUrl)
    : fixtureAccountWorkspaceRepository;
  return repository.get(accountId);
}
