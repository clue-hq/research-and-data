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

/**
 * Pinned to fixtures until phase 2 — see the note in
 * `project-workspace.repository.ts`. `GET /api/v1/projects/sidebar` is not
 * served by slice 1, and this repository must not flip on the accounts flow's
 * variable.
 */
export async function getSidebarProjects() {
  return fixtureSidebarProjectsRepository.list();
}
