import type {
  MentionDirectory,
  MentionDirectoryRepository,
} from "../data/mention-directory.repository";

/**
 * The session's copy of the @ tagger's directory, one per project.
 *
 * `peek` answers synchronously from what was last loaded, so reopening a
 * project's chat shows the directory at once; `refresh` re-checks it with the
 * cached ETag (a 304 costs no body). Concurrent refreshes of one project share
 * one request, and a failed refresh keeps the last good directory — the
 * tagger degrading to slightly stale beats it emptying.
 */
export interface MentionDirectoryStore {
  peek(projectId: string | null): MentionDirectory | null;
  refresh(projectId: string | null): Promise<MentionDirectory | null>;
}

export function createMentionDirectoryStore(
  repository: MentionDirectoryRepository,
): MentionDirectoryStore {
  const cached = new Map<string, MentionDirectory>();
  const inFlight = new Map<string, Promise<MentionDirectory | null>>();
  const keyOf = (projectId: string | null) => projectId ?? "";

  return {
    peek(projectId) {
      return cached.get(keyOf(projectId)) ?? null;
    },
    refresh(projectId) {
      const key = keyOf(projectId);
      const pending = inFlight.get(key);
      if (pending) return pending;
      const request = (async () => {
        const current = cached.get(key) ?? null;
        try {
          const result = await repository.load({
            projectId,
            etag: current?.etag ?? null,
          });
          if (result.status === "loaded") {
            cached.set(key, result.directory);
            return result.directory;
          }
          return current;
        } catch {
          return current;
        } finally {
          inFlight.delete(key);
        }
      })();
      inFlight.set(key, request);
      return request;
    },
  };
}
