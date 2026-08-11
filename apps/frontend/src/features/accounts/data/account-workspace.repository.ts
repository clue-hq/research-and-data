import {
  AccountWorkspaceResponseSchema,
  type AccountWorkspace,
} from "../model/account-workspace";

/**
 * The Insights / Artifacts / Activity tabs.
 *
 * Slice 1 serves no workspace endpoint: there is no activity feed or artifact
 * index, and account insights arrive on the Overview detail contract. Until
 * those live contracts land, every real account receives an explicit empty
 * workspace model. It contains no demo data and performs no guessed request.
 */
export interface AccountWorkspaceRepository {
  get(accountId: string): Promise<AccountWorkspace | null>;
}

export const emptyAccountWorkspaceRepository: AccountWorkspaceRepository = {
  async get(accountId) {
    return AccountWorkspaceResponseSchema.parse({
      data: { accountId, insights: [], artifacts: [], activity: [] },
    }).data;
  },
};

export async function getAccountWorkspace(
  accountId: string,
): Promise<AccountWorkspace | null> {
  return emptyAccountWorkspaceRepository.get(accountId);
}
