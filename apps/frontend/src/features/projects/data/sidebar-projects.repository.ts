import { threadLabel } from "../model/chat-thread";
import {
  SidebarProjectsResponseSchema,
  type SidebarProjectsResponse,
} from "../model/sidebar-project";
import type { ChatRepositories } from "./chat-repositories";
import { sidebarProjectFixtures } from "./sidebar-projects.fixture";

/**
 * The sidebar's project/thread tree.
 *
 * **Contract status.** The proposal's `GET /api/v1/projects/sidebar` is not
 * implemented, and neither is any project *catalog* read: the as-built section
 * puts project lifecycle (`POST /projects`, `DELETE /projects/:projectId`)
 * outside the chat shell's ownership, phase-2 and a separate owner. What the
 * backend does serve is the per-project paginated thread list. So the HTTP
 * adapter below is honest about being a *hybrid*: the project rows still come
 * from the fixture catalog, and each project's conversations are replaced with
 * the real threads — including their derived status, which is what makes the
 * sidebar's approval / needs-input / running badges true. When a project read
 * lands, only this file changes.
 */
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

export function createHydratedSidebarProjectsRepository(
  repositories: ChatRepositories,
): SidebarProjectsRepository {
  return {
    async list() {
      const catalog = await fixtureSidebarProjectsRepository.list();
      const hydrated = await Promise.all(
        catalog.data.map(async (project) => {
          const page = await repositories.threads.list({ projectId: project.id });
          return {
            ...project,
            conversations: page.threads.map((thread) => ({
              href: thread.href,
              id: thread.id,
              status: thread.status,
              title: threadLabel(thread),
            })),
          };
        }),
      );
      return SidebarProjectsResponseSchema.parse({
        data: hydrated,
        meta: { total: hydrated.length },
      });
    },
  };
}

export function createSidebarProjectsRepository(
  repositories: ChatRepositories,
): SidebarProjectsRepository {
  return repositories.transport.mode === "http"
    ? createHydratedSidebarProjectsRepository(repositories)
    : fixtureSidebarProjectsRepository;
}

/** The server-rendered read used before the browser has a transport. */
export async function getSidebarProjects() {
  return fixtureSidebarProjectsRepository.list();
}
