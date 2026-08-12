import {
  AccountWorkspaceResponseSchema,
  type AccountWorkspace,
} from "../model/account-workspace";

/**
 * The remaining legacy Insights workspace payload.
 *
 * Slice 1 serves no Insights-workspace endpoint; Account insights arrive on
 * the Overview detail contract. Activity has its own live repository, while
 * Artifacts has an explicit capability-unavailable state in its route. Both
 * are intentionally absent here. Until the Insights contract lands, every
 * real account receives an explicit empty model with no demo data or guessed
 * request.
 */
export interface AccountWorkspaceRepository {
  get(accountId: string): Promise<AccountWorkspace | null>;
}

export const emptyAccountWorkspaceRepository: AccountWorkspaceRepository = {
  async get(accountId) {
    return AccountWorkspaceResponseSchema.parse({
      data: { accountId, insights: [] },
    }).data;
  },
};

export async function getAccountWorkspace(
  accountId: string,
): Promise<AccountWorkspace | null> {
  return emptyAccountWorkspaceRepository.get(accountId);
}
