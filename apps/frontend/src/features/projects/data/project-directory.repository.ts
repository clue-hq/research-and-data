import {
  DirectoryItemResponseSchema,
  DirectoryPageWireSchema,
  type DirectoryProject,
} from "../model/project-directory";
import { chatRequest, type ChatTransport } from "./chat-api";
import { projectDirectoryFixture } from "./project-directory.fixture";

/**
 * The projects directory's one seam onto the chat surface.
 *
 * `listAll` walks the cursor rather than paging in the UI: the directory is a
 * searchable, sortable grid, and sorting a single page would order the wrong
 * set. The page size is the backend's maximum, so the common workspace is one
 * request.
 */
export interface ProjectDirectoryRepository {
  listAll(status: "active" | "archived"): Promise<DirectoryProject[]>;
  create(input: {
    brandId: string;
    title: string;
    description: string;
    idempotencyKey: string;
  }): Promise<DirectoryProject>;
  update(
    projectId: string,
    patch: { title?: string; description?: string; pinned?: boolean },
  ): Promise<DirectoryProject>;
  setArchived(projectId: string, archived: boolean): Promise<DirectoryProject>;
}

const PAGE_LIMIT = 100;

export function createHttpProjectDirectoryRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ProjectDirectoryRepository {
  return {
    async listAll(status) {
      const projects: DirectoryProject[] = [];
      let cursor: string | null = null;
      do {
        const page = DirectoryPageWireSchema.parse(
          await chatRequest(transport, "/projects", {
            query: { status, cursor: cursor ?? undefined, limit: PAGE_LIMIT },
          }),
        );
        projects.push(...page.projects);
        cursor = page.nextCursor;
      } while (cursor);
      return projects;
    },
    async create({ idempotencyKey, brandId, title, description }) {
      return DirectoryItemResponseSchema.parse(
        await chatRequest(transport, "/projects/blank", {
          method: "POST",
          idempotencyKey,
          body: { brand_id: brandId, title, description },
        }),
      );
    },
    async update(projectId, patch) {
      return DirectoryItemResponseSchema.parse(
        await chatRequest(
          transport,
          `/projects/${encodeURIComponent(projectId)}`,
          { method: "PATCH", body: patch },
        ),
      );
    },
    async setArchived(projectId, archived) {
      return DirectoryItemResponseSchema.parse(
        await chatRequest(
          transport,
          `/projects/${encodeURIComponent(projectId)}/archive`,
          { method: "POST", body: { archived } },
        ),
      );
    },
  };
}

/**
 * The visual-development adapter. It stands in for the backend in fixture mode
 * and is never a fallback in HTTP mode: an HTTP failure is a failure.
 */
export function createFixtureProjectDirectoryRepository(): ProjectDirectoryRepository {
  let projects = structuredClone(projectDirectoryFixture);
  const now = () => new Date().toISOString();
  const find = (id: string) => {
    const project = projects.find((candidate) => candidate.id === id);
    if (!project) throw new Error("This project is no longer available.");
    return project;
  };
  return {
    async listAll(status) {
      return projects.filter((project) => project.status === status);
    },
    async create({ title, description }) {
      const id = `project-${crypto.randomUUID()}`;
      const created: DirectoryProject = {
        id,
        title,
        description,
        href: `/projects/${id}`,
        status: "active",
        pinned: false,
        brandId: "brand-clue-demo",
        productId: null,
        createdAt: now(),
        updatedAt: now(),
        archivedAt: null,
        activity: { chats: 0, running: 0, needsInput: 0 },
      };
      projects = [created, ...projects];
      return created;
    },
    async update(projectId, patch) {
      const project = find(projectId);
      if (project.status === "archived" && patch.pinned === undefined) {
        throw new Error("Restore this project before making changes.");
      }
      if (patch.title !== undefined) project.title = patch.title;
      if (patch.description !== undefined) project.description = patch.description;
      if (patch.pinned !== undefined) project.pinned = patch.pinned;
      // Pinning is a shelf, not an edit, so it does not bump the timestamp the
      // "recently updated" sort reads.
      if (patch.pinned === undefined) project.updatedAt = now();
      return { ...project };
    },
    async setArchived(projectId, archived) {
      const project = find(projectId);
      if (archived && project.activity.running > 0) {
        throw new Error(
          "This project has running work. Wait for it to finish before archiving.",
        );
      }
      project.status = archived ? "archived" : "active";
      project.archivedAt = archived ? now() : null;
      project.updatedAt = now();
      return { ...project };
    },
  };
}
