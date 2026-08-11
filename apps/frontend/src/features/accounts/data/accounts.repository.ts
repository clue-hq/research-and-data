import {
  AccountsResponseSchema,
  type AccountsResponse,
} from "../model/account";
import { fetchRead } from "./frontend-api";

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

export function createHttpAccountsRepository(
  read: typeof fetchRead = fetchRead,
): AccountsRepository {
  return {
    async list(query = {}) {
      // No `recordNotFoundAllowed`: this endpoint has no domain 404 by
      // contract — an unknown project is an empty page — so any 404 here is a
      // misconfiguration and must surface as one.
      const body = await read("/accounts", {
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

export async function getAccounts(
  query?: AccountsQuery,
): Promise<AccountsResponse> {
  return createHttpAccountsRepository().list(query);
}
