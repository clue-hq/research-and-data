import {
  SidebarProjectsResponseSchema,
  type SidebarProjectsResponse,
} from "../model/sidebar-project";
import { sidebarProjectFixtures } from "./sidebar-projects.fixture";

export interface SidebarProjectsRepository {
  list(): Promise<SidebarProjectsResponse>;
}

export const fixtureSidebarProjectsRepository: SidebarProjectsRepository = {
  async list() {
    return SidebarProjectsResponseSchema.parse({
      data: sidebarProjectFixtures,
      meta: { total: sidebarProjectFixtures.length },
    });
  },
};

export function createHttpSidebarProjectsRepository(
  apiBaseUrl: string,
): SidebarProjectsRepository {
  return {
    async list() {
      const response = await fetch(
        new URL(
          "/api/v1/projects/sidebar",
          `${apiBaseUrl.replace(/\/$/, "")}/`,
        ),
        { cache: "no-store", headers: { Accept: "application/json" } },
      );

      if (!response.ok) {
        throw new Error(`Sidebar projects API returned ${response.status}`);
      }

      return SidebarProjectsResponseSchema.parse(await response.json());
    },
  };
}

export async function getSidebarProjects() {
  const apiBaseUrl = process.env.CLUE_API_BASE_URL;
  const repository = apiBaseUrl
    ? createHttpSidebarProjectsRepository(apiBaseUrl)
    : fixtureSidebarProjectsRepository;

  return repository.list();
}
