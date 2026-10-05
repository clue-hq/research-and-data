import type { ProjectEntity } from "./project-workspace";

/** The server refuses shorter queries; below this the tagger searches only what it holds. */
export const MENTION_REMOTE_SEARCH_MIN_LENGTH = 2;
export const MENTION_REMOTE_SEARCH_DELAY_MS = 120;

/**
 * Server search for a directory too large to load whole: waits for a pause in
 * typing, cancels the request a newer keystroke made stale, and reports only
 * the latest query's matches.
 */
export function createDebouncedMentionSearch({
  delayMs = MENTION_REMOTE_SEARCH_DELAY_MS,
  search,
  onResults,
}: {
  delayMs?: number;
  search: (query: string, signal: AbortSignal) => Promise<ProjectEntity[]>;
  onResults: (entities: ProjectEntity[]) => void;
}) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;

  const cancel = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    controller?.abort();
    controller = null;
  };

  return {
    request(query: string) {
      cancel();
      const needle = query.trim();
      if (needle.length < MENTION_REMOTE_SEARCH_MIN_LENGTH) {
        onResults([]);
        return;
      }
      timer = setTimeout(() => {
        timer = null;
        const mine = new AbortController();
        controller = mine;
        search(needle, mine.signal)
          .then(
            (found) => {
              if (!mine.signal.aborted) onResults(found);
            },
            () => {
              // A cancelled or failed search leaves the local matches standing.
            },
          )
          .finally(() => {
            if (controller === mine) controller = null;
          });
      }, delayMs);
    },
    dispose: cancel,
  };
}

/** What the user's own directory matched leads; server matches follow, deduplicated. */
export function mergeMentionResults(
  local: readonly ProjectEntity[],
  remote: readonly ProjectEntity[],
): ProjectEntity[] {
  const seen = new Set(local.map((entity) => `${entity.type}:${entity.id}`));
  return [
    ...local,
    ...remote.filter((entity) => !seen.has(`${entity.type}:${entity.id}`)),
  ];
}
