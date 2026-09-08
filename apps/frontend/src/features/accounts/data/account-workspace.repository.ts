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
 * This route has only ever served contract v1, but `?contract=v1` is sent all
 * the same: the parameter is validated on every route of the surface, so
 * sending it keeps one request shape across the five reads and makes a typo'd
 * value fail here exactly as it would anywhere else.
 */
export function createHttpAccountWorkspaceRepository(
  read: typeof fetchRead = fetchRead,
): AccountWorkspaceRepository {
  return {
    async get(accountId) {
      const body = await read(
        `/accounts/${encodeURIComponent(accountId)}/workspace`,
        { recordNotFoundAllowed: true, searchParams: { contract: "v1" } },
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
