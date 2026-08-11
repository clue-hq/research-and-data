import {
  AccountWorkspaceResponseSchema,
  type AccountWorkspace,
} from "../model/account-workspace";

/**
 * The Insights / Artifacts tabs.
 *
 * Slice 1 serves no Insights-workspace or Artifact index endpoint; Account
 * insights arrive on the Overview detail contract. Activity has its own live
 * repository and is intentionally absent from this model. Until the remaining
 * live contracts land, every real account receives an explicit empty workspace
 * model. It contains no demo data and performs no guessed request.
 */
export interface AccountWorkspaceRepository {
  get(accountId: string): Promise<AccountWorkspace | null>;
}

export const emptyAccountWorkspaceRepository: AccountWorkspaceRepository = {
  async get(accountId) {
    return AccountWorkspaceResponseSchema.parse({
      data: { accountId, insights: [], artifacts: [] },
    }).data;
  },
};

export async function getAccountWorkspace(
  accountId: string,
): Promise<AccountWorkspace | null> {
  return emptyAccountWorkspaceRepository.get(accountId);
}
