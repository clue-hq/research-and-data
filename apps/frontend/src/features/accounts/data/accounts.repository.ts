import {
  AccountsResponseSchema,
  type AccountsResponse,
} from "../model/account";
import { accountFixtures } from "./accounts.fixture";
import { apiBaseUrl, fetchRead } from "./frontend-api";

/**
 * The only query parameters the as-built list endpoint accepts.
 *
 * No `search`, no `sort`, no filter-rule POST: those surfaces do not exist yet,
 * and the authored filter/sort shell runs client-side over the loaded page
 * (`model/account-query.ts`). `limit` defaults to 50 and is capped at 200 —
 * a value outside `1..200` is a `422`.
 */
export interface AccountsQuery {
  cursor?: string;
  limit?: number;
  projectId?: string;
}

export interface AccountsRepository {
  list(query?: AccountsQuery): Promise<AccountsResponse>;
}

/**
 * Development adapter. Mirrors the endpoint's own semantics: `projectId`
 * filters by membership, an unknown project yields an empty page rather than
 * an error, and rows keep their full `projects` array either way.
 */
export const fixtureAccountsRepository: AccountsRepository = {
  async list(query = {}) {
    const filtered = query.projectId
      ? accountFixtures.filter((account) =>
          account.projects.some(
            (project) => project.projectId === query.projectId,
          ),
        )
      : accountFixtures;
    const data = query.limit ? filtered.slice(0, query.limit) : filtered;

    return AccountsResponseSchema.parse({
      data,
      meta: {
        total: filtered.length,
        nextCursor: null,
      },
    });
  },
};

export function createHttpAccountsRepository(): AccountsRepository {
  return {
    async list(query = {}) {
      // No `recordNotFoundAllowed`: this endpoint has no domain 404 by
      // contract — an unknown project is an empty page — so any 404 here is a
      // misconfiguration and must surface as one.
      const body = await fetchRead("/accounts", {
        searchParams: {
          cursor: query.cursor,
          limit: query.limit,
          projectId: query.projectId,
        },
      });

      return AccountsResponseSchema.parse(body);
    },
  };
}

function repository(): AccountsRepository {
  return apiBaseUrl() ? createHttpAccountsRepository() : fixtureAccountsRepository;
}

export async function getAccounts(
  query?: AccountsQuery,
): Promise<AccountsResponse> {
  return repository().list(query);
}
