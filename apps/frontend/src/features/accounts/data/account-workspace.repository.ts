import {
  AccountWorkspaceResponseSchema,
  type AccountWorkspace,
} from "../model/account-workspace";
import { openAiWorkspaceFixture } from "./account-workspace.fixture";
import { zafranWorkspaceFixture } from "./zafran/insights";
import { fetchRead } from "./frontend-api";
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

/**
 * The live account workspace: `GET /frontend/v1/accounts/{id}/workspace` → `{data}`.
 *
 */
export function createHttpAccountWorkspaceRepository(
  read: typeof fetchRead = fetchRead,
): AccountWorkspaceRepository {
  return {
    async get(accountId) {
      const body = await read(
        `/accounts/${encodeURIComponent(accountId)}/workspace`,
        { recordNotFoundAllowed: true },
      );
      if (body === null) return null;
      return AccountWorkspaceResponseSchema.parse(body).data;
    },
  };
}

export async function getAccountWorkspace(
  accountId: string,
  read: typeof fetchRead = fetchRead,
): Promise<AccountWorkspace | null> {
  const repository = accountsFixtureMode()
    ? fixtureAccountWorkspaceRepository
    : createHttpAccountWorkspaceRepository(read);
  return repository.get(accountId);
}
