import {
  fetchMutation,
  fetchMutationVoid,
} from "../../accounts/data/frontend-mutation";
import {
  ProjectMemoryListResponseSchema,
  ProjectMemoryNoteResponseSchema,
  type ProjectMemoryNote,
} from "../model/project-memory";

/**
 * The memory panel's seam onto the scoped-memory write path.
 *
 * Every write goes through the backend's one seam, so a refusal is a real
 * answer, not a failure to be swallowed: `MEMORY_REJECTED` (this is a fact, not
 * a preference), `MEMORY_DISABLED` (nothing is being kept here), and
 * `MEMORY_UNAVAILABLE` all arrive as `ClueApiError` with their code intact and
 * are the caller's to state.
 */
export interface ProjectMemoryRepository {
  list(projectId: string): Promise<ProjectMemoryNote[]>;
  add(
    projectId: string,
    input: { text: string; sourceThreadId?: string },
  ): Promise<ProjectMemoryNote>;
  edit(
    projectId: string,
    memoryId: string,
    input: { text: string; sourceThreadId?: string },
  ): Promise<ProjectMemoryNote>;
  remove(projectId: string, memoryId: string): Promise<void>;
}

const collection = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/memory`;

const one = (projectId: string, memoryId: string) =>
  `${collection(projectId)}/${encodeURIComponent(memoryId)}`;

const writeBody = (input: { text: string; sourceThreadId?: string }) =>
  JSON.stringify({
    text: input.text,
    source_thread_id: input.sourceThreadId ?? null,
  });

export function createHttpProjectMemoryRepository(): ProjectMemoryRepository {
  return {
    async list(projectId) {
      return ProjectMemoryListResponseSchema.parse(
        await fetchMutation(collection(projectId), { method: "GET" }),
      );
    },
    async add(projectId, input) {
      const written = ProjectMemoryNoteResponseSchema.parse(
        await fetchMutation(collection(projectId), {
          method: "POST",
          body: writeBody(input),
        }),
      );
      return written.note;
    },
    async edit(projectId, memoryId, input) {
      const written = ProjectMemoryNoteResponseSchema.parse(
        await fetchMutation(one(projectId, memoryId), {
          method: "PUT",
          body: writeBody(input),
        }),
      );
      return written.note;
    },
    async remove(projectId, memoryId) {
      await fetchMutationVoid(one(projectId, memoryId), { method: "DELETE" });
    },
  };
}

/** Visual-development adapter: one in-memory note list per project. */
export function createFixtureProjectMemoryRepository(): ProjectMemoryRepository {
  const notes = new Map<string, ProjectMemoryNote[]>();
  const of = (projectId: string) => notes.get(projectId) ?? [];
  let counter = 0;
  const write = (
    input: { text: string; sourceThreadId?: string },
  ): ProjectMemoryNote => ({
    id: `memory-${(counter += 1)}`,
    text: input.text,
    sourceThreadId: input.sourceThreadId ?? null,
    sourceThreadTitle: input.sourceThreadId ? "Fixture chat" : null,
    createdAt: new Date().toISOString(),
  });
  return {
    async list(projectId) {
      return [...of(projectId)];
    },
    async add(projectId, input) {
      const note = write(input);
      notes.set(projectId, [note, ...of(projectId)]);
      return note;
    },
    async edit(projectId, memoryId, input) {
      const existing = of(projectId);
      if (!existing.some((note) => note.id === memoryId)) {
        throw new Error("That note is no longer there.");
      }
      // The substrate is append-only: an edit retires the old record and the
      // successor carries a new id, so the fixture does the same.
      const successor = write(input);
      notes.set(
        projectId,
        existing.map((note) => (note.id === memoryId ? successor : note)),
      );
      return successor;
    },
    async remove(projectId, memoryId) {
      notes.set(
        projectId,
        of(projectId).filter((note) => note.id !== memoryId),
      );
    },
  };
}
