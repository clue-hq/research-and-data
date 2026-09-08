import {
  AccountWorkspaceResponseSchema,
  type AccountWorkspace,
} from "../model/account-workspace";
import { openAiWorkspaceFixture } from "./account-workspace.fixture";
import { zafranWorkspaceFixture } from "./zafran/insights";
import { accountsFixtureMode } from "./repository-mode";

export interface AccountWorkspaceRepository {
  get(accountId: string): Promise<AccountWorkspace | null>;
}

export const fixtureAccountWorkspaceRepository: AccountWorkspaceRepository = {
  async get(accountId) {
    const workspace = [openAiWorkspaceFixture, zafranWorkspaceFixture].find(
      (candidate) => candidate.accountId === accountId,
    );
    if (!workspace) return null;
    return AccountWorkspaceResponseSchema.parse({
      data: workspace,
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
  const repository = accountsFixtureMode()
    ? fixtureAccountWorkspaceRepository
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
