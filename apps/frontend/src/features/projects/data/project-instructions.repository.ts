import { fetchMutation } from "../../accounts/data/frontend-mutation";
import {
  ProjectInstructionsResponseSchema,
  type ProjectInstructions,
} from "../model/project-instructions";

/**
 * The instructions panel's seam.
 *
 * Instructions are a project *document*, so they live on the `/frontend/v1`
 * read surface rather than the chat mount, and every call — the GET included —
 * rides `fetchMutation`, which is the one place the BFF prefix and the error
 * envelope are known.
 */
export interface ProjectInstructionsRepository {
  get(projectId: string): Promise<ProjectInstructions | null>;
  save(
    projectId: string,
    input: { body: string; expectedRevision: number | null },
  ): Promise<ProjectInstructions | null>;
}

const path = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/instructions`;

export function createHttpProjectInstructionsRepository(): ProjectInstructionsRepository {
  return {
    async get(projectId) {
      return ProjectInstructionsResponseSchema.parse(
        await fetchMutation(path(projectId), { method: "GET" }),
      );
    },
    async save(projectId, { body, expectedRevision }) {
      return ProjectInstructionsResponseSchema.parse(
        await fetchMutation(path(projectId), {
          method: "PUT",
          body: JSON.stringify({ body, expected_revision: expectedRevision }),
        }),
      );
    },
  };
}

/** Visual-development adapter: one in-memory document per project. */
export function createFixtureProjectInstructionsRepository(): ProjectInstructionsRepository {
  const saved = new Map<string, ProjectInstructions>();
  return {
    async get(projectId) {
      return saved.get(projectId) ?? null;
    },
    async save(projectId, { body, expectedRevision }) {
      const current = saved.get(projectId) ?? null;
      if (expectedRevision !== (current?.revision ?? null)) {
        throw new Error(
          "These instructions changed somewhere else. Reload before saving.",
        );
      }
      const next: ProjectInstructions = {
        body,
        revision: (current?.revision ?? 0) + 1,
        updatedAt: new Date().toISOString(),
      };
      saved.set(projectId, next);
      return next;
    },
  };
}
