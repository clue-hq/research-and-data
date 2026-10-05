"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useChatRepositories } from "../data/projects-transport";
import type {
  MentionDirectory,
  MentionDirectoryRepository,
} from "../data/mention-directory.repository";
import {
  createMentionDirectoryStore,
  type MentionDirectoryStore,
} from "../model/mention-directory-store";
import {
  createDebouncedMentionSearch,
  mergeMentionResults,
} from "../model/mention-remote-search";
import type { ProjectEntity } from "../model/project-workspace";

// One store per repository, outliving any one composer: navigating between
// chats shows the directory at once and only re-checks it.
const stores = new WeakMap<MentionDirectoryRepository, MentionDirectoryStore>();

function storeFor(repository: MentionDirectoryRepository): MentionDirectoryStore {
  let store = stores.get(repository);
  if (!store) {
    store = createMentionDirectoryStore(repository);
    stores.set(repository, store);
  }
  return store;
}

/** Re-checking on every focus is cheap (a 304), but not free: once per this many ms. */
const REVALIDATE_ON_FOCUS_AFTER_MS = 30_000;

/**
 * The @ tagger's accounts and contacts for one composer.
 *
 * `entities` is the whole workspace directory (project accounts first) once it
 * has loaded, and `fallback` — the server-rendered list — until then or when
 * there is no directory to ask. When the directory was too large to send whole,
 * `onMentionQueryChange` asks the server as the user types and its matches are
 * appended after the directory's own, so local matches always lead and a
 * picked server match resolves by id like any other entity.
 */
export function useMentionDirectory(
  projectId: string | null,
  fallback: readonly ProjectEntity[],
): {
  entities: ProjectEntity[];
  onMentionQueryChange?: (query: string) => void;
} {
  const repository = useChatRepositories().mentionDirectory;
  const store = storeFor(repository);
  // Keyed by project so switching projects never shows the previous one's order.
  const [loaded, setLoaded] = useState<{
    projectId: string | null;
    directory: MentionDirectory;
  } | null>(null);
  const directory =
    loaded && loaded.projectId === projectId ? loaded.directory : store.peek(projectId);
  const [remoteHits, setRemoteHits] = useState<ProjectEntity[]>([]);

  useEffect(() => {
    let cancelled = false;
    let lastCheck = 0;
    const revalidate = () => {
      lastCheck = Date.now();
      void store.refresh(projectId).then((next) => {
        if (!cancelled && next) setLoaded({ projectId, directory: next });
      });
    };
    const onFocus = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastCheck < REVALIDATE_ON_FOCUS_AFTER_MS) return;
      revalidate();
    };
    revalidate();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [projectId, store]);

  const incomplete = directory !== null && !directory.complete;
  const search = useMemo(
    () =>
      incomplete
        ? createDebouncedMentionSearch({
            search: (query, signal) => repository.search({ query, signal }),
            // Hits accumulate for the session, so a picked match keeps resolving by id after
            // the next query replaces the visible results.
            onResults: (found) =>
              setRemoteHits((current) => mergeMentionResults(current, found)),
          })
        : null,
    [incomplete, repository],
  );
  useEffect(() => () => search?.dispose(), [search]);

  const onMentionQueryChange = useCallback(
    (query: string) => search?.request(query),
    [search],
  );

  const entities = useMemo(() => {
    const base = directory ? directory.entities : [...fallback];
    return remoteHits.length ? mergeMentionResults(base, remoteHits) : base;
  }, [directory, fallback, remoteHits]);

  return {
    entities,
    ...(incomplete ? { onMentionQueryChange } : {}),
  };
}
