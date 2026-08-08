import {
  AccountWorkspaceResponseSchema,
  type AccountWorkspace,
} from "../model/account-workspace";
import { openAiWorkspaceFixture } from "./account-workspace.fixture";

/**
 * The Insights / Artifacts / Activity tabs.
 *
 * Slice 1 of the backend read layer serves NO workspace endpoint — there is no
 * activity feed, no artifact index, and account insights arrive on the detail's
 * `projectSections[].insights` instead. So this repository stays fixture-only
 * and grows an HTTP adapter when that endpoint is specified, rather than
 * pointing at a URL nobody serves.
 *
 * An account the fixture does not cover resolves to an empty workspace, not to
 * `null`: with `CLUE_API_BASE_URL` set the account itself is real, and an empty
 * tab is the honest rendering of "nothing here yet" — a 404 on a tab of an
 * account that plainly exists is not.
 */
export interface AccountWorkspaceRepository {
  get(accountId: string): Promise<AccountWorkspace | null>;
}

export const fixtureAccountWorkspaceRepository: AccountWorkspaceRepository = {
  async get(accountId) {
    const data =
      accountId === openAiWorkspaceFixture.accountId
        ? openAiWorkspaceFixture
        : { accountId, insights: [], artifacts: [], activity: [] };

    return AccountWorkspaceResponseSchema.parse({ data }).data;
  },
};

export async function getAccountWorkspace(
  accountId: string,
): Promise<AccountWorkspace | null> {
  return fixtureAccountWorkspaceRepository.get(accountId);
}
