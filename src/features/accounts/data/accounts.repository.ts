import {
  AccountsResponseSchema,
  type Account,
  type AccountsResponse,
  type ResearchStatus,
} from "../model/account";
import { accountFixtures } from "./accounts.fixture";

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

export function createHttpAccountsRepository(
  apiBaseUrl: string,
): AccountsRepository {
  return {
    async list(query = {}) {
      const url = new URL("/api/v1/accounts", `${apiBaseUrl.replace(/\/$/, "")}/`);

      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== "") {
          url.searchParams.set(key, String(value));
        }
      }

      const response = await fetch(url, {
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(
          `Accounts API returned ${response.status} ${response.statusText}`,
        );
      }

      return AccountsResponseSchema.parse(await response.json());
    },
  };
}

export async function getAccounts(
  query?: AccountsQuery,
): Promise<AccountsResponse> {
  const apiBaseUrl = process.env.CLUE_API_BASE_URL;
  const repository = apiBaseUrl
    ? createHttpAccountsRepository(apiBaseUrl)
    : fixtureAccountsRepository;

  return repository.list(query);
}

export async function getAccountPreviewRows(): Promise<Account[]> {
  return (await getAccounts()).data;
}
