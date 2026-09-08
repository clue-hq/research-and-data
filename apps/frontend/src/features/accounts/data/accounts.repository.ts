import {
  AccountsResponseSchema,
  type Account,
  type AccountsResponse,
  type ResearchStatus,
} from "../model/account";
import { accountFixtures } from "./accounts.fixture";
import { fetchRead } from "./frontend-api";
import { accountsFixtureMode } from "./repository-mode";

export interface AccountsQuery {
  cursor?: string;
  limit?: number;
  overallFit?: Account["overallFit"];
  projectId?: string;
  researchStatus?: ResearchStatus;
  search?: string;
  sort?:
    | "name_asc"
    | "name_desc"
    | "project_asc"
    | "project_desc"
    | "fit_score_desc"
    | "fit_score_asc";
}

export interface AccountsRepository {
  list(query?: AccountsQuery): Promise<AccountsResponse>;
}

/**
 * Development adapter for the frontend-only phase.
 * Replace this implementation with an HTTP adapter when the backend is ready;
 * account components do not import fixtures or know how records are fetched.
 */
export const fixtureAccountsRepository: AccountsRepository = {
  async list(query = {}) {
    const normalizedSearch = query.search?.trim().toLocaleLowerCase();
    const searched = normalizedSearch
      ? accountFixtures.filter((account) =>
          account.name.toLocaleLowerCase().includes(normalizedSearch),
        )
      : accountFixtures;
    const filtered = query.projectId
      ? searched.filter((account) =>
          account.projects.some((project) => project.id === query.projectId),
        )
      : searched;
    const data = query.sort
      ? [...filtered].sort((first, second) => {
          if (query.sort === "name_asc" || query.sort === "name_desc") {
            const nameComparison = first.name.localeCompare(second.name);
            return query.sort === "name_desc" ? -nameComparison : nameComparison;
          }
          if (
            query.sort === "fit_score_asc" ||
            query.sort === "fit_score_desc"
          ) {
            if (first.fitScore === null) return second.fitScore === null ? 0 : 1;
            if (second.fitScore === null) return -1;
            const scoreComparison = first.fitScore - second.fitScore;
            return query.sort === "fit_score_desc"
              ? -scoreComparison
              : scoreComparison;
          }
          const firstProject =
            first.projects.find(
              (project) => project.id === first.primaryProjectId,
            )?.name ?? "";
          const secondProject =
            second.projects.find(
              (project) => project.id === second.primaryProjectId,
            )?.name ?? "";
          const comparison =
            firstProject.localeCompare(secondProject) ||
            first.name.localeCompare(second.name);
          return query.sort === "project_desc" ? -comparison : comparison;
        })
      : filtered;

    return AccountsResponseSchema.parse({
      data,
      meta: {
        total: data.length,
        nextCursor: null,
      },
    });
  },
};

/** The largest page E1 serves (`MAX_LIMIT` on `GET /frontend/v1/accounts`). */
export const ACCOUNTS_PAGE_LIMIT = 200;

/**
 * How many pages the list read will follow before it stops.
 *
 * 25 × 200 = 5,000 rows. Beyond that the read returns what it has rather than
 * walking an unbounded workspace on one server render; the table would not be
 * usable at that size anyway, and the honest fix is server-side paging on the
 * screen, not a longer walk here.
 */
export const ACCOUNTS_PAGE_CAP = 25;

/**
 * The live accounts list: `GET /frontend/v1/accounts?limit=200`.
 *
 * The table keeps the design build's browser-side search, filter, sort and
 * pagination (D4 ruling a), so this read returns the WHOLE list: it follows
 * `meta.nextCursor` and concatenates each page's `data` in server order. The
 * returned `meta.total` is the server's own count of the filtered set; the
 * cursor is `null` because there is nothing left for the caller to page.
 *
 * `projectId` is the one query knob the backend owns, so it is forwarded.
 * `search`, `sort`, `overallFit`, `researchStatus`, `limit` and `cursor` are
 * browser-side concerns on this path and are deliberately not sent — E1 has no
 * parameter for them, and a silently-ignored parameter is worse than none.
 */
export function createHttpAccountsRepository(
  read: typeof fetchRead = fetchRead,
): AccountsRepository {
  return {
    async list(query = {}) {
      const data: Account[] = [];
      let cursor: string | undefined = undefined;
      let total = 0;

      for (let page = 0; page < ACCOUNTS_PAGE_CAP; page += 1) {
        const body = AccountsResponseSchema.parse(
          await read("/accounts", {
            searchParams: {
              limit: ACCOUNTS_PAGE_LIMIT,
              cursor,
              projectId: query.projectId,
            },
          }),
        );
        data.push(...body.data);
        if (page === 0) total = body.meta.total;
        if (body.meta.nextCursor === null) break;
        cursor = body.meta.nextCursor;
      }

      return { data, meta: { total, nextCursor: null } };
    },
  };
}

export async function getAccounts(
  query?: AccountsQuery,
  read: typeof fetchRead = fetchRead,
): Promise<AccountsResponse> {
  const repository = accountsFixtureMode()
    ? fixtureAccountsRepository
    : createHttpAccountsRepository(read);

  return repository.list(query);
}

export async function getAccountPreviewRows(): Promise<Account[]> {
  return (await getAccounts()).data;
}
