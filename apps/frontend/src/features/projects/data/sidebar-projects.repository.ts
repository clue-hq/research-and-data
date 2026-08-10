import {
  SidebarProjectsResponseSchema,
  SidebarProjectsWireResponseSchema,
  type SidebarProjectsResponse,
} from "../model/sidebar-project";
import { chatRequest, type ChatTransport } from "./chat-api";
import { sidebarProjectFixtures } from "./sidebar-projects.fixture";

export interface SidebarProjectsQuery {
  cursor?: string;
  limit?: number;
}

export interface SidebarProjectsRepository {
  list(query?: SidebarProjectsQuery): Promise<SidebarProjectsResponse>;
}

export const fixtureSidebarProjectsRepository: SidebarProjectsRepository = {
  async list() {
    return SidebarProjectsResponseSchema.parse({
      data: sidebarProjectFixtures,
      meta: { nextCursor: null },
    });
  },
};

export function createHttpSidebarProjectsRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): SidebarProjectsRepository {
  return {
    async list(query = {}) {
      return SidebarProjectsWireResponseSchema.parse(
        await chatRequest(transport, "/projects/sidebar", {
          query: { cursor: query.cursor, limit: query.limit },
        }),
      );
    },
  };
}

export function createSidebarProjectsRepository(
  transport: ChatTransport,
): SidebarProjectsRepository {
  return transport.mode === "http"
    ? createHttpSidebarProjectsRepository(transport)
    : fixtureSidebarProjectsRepository;
}

/** Fixture-only server read; authenticated HTTP sidebar data loads client-side. */
export function getSidebarProjects() {
  return fixtureSidebarProjectsRepository.list();
}
