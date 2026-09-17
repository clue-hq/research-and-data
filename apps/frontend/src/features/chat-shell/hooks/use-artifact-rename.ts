"use client";

import { useCallback } from "react";
import { renameArtifactDocument } from "@/features/artifacts/data/artifact-document.repository";

/**
 * Artifacts page (2026-09-15): the editor header's rename, persisted.
 *
 * The header is presentation and may not import a repository, so the write
 * lives here and the two mounts (the chat surface and the full-width editor
 * surface) hand in their own `documentIds` map and their own "it landed"
 * follow-up. `onRenamed` receives the title the BACKEND stored — never the
 * typed string — so a server-side normalization shows up in the tab.
 *
 * A refusal leaves local state exactly as it was: the header re-renders the
 * stored title, and the operator sees the rename simply did not take rather
 * than a tab that disagrees with the document.
 */
export function useArtifactRename({
  documentIds,
  onRenamed,
}: {
  /** artifact id → design-document id; absent entries fall back to the artifact id. */
  documentIds?: Record<string, string>;
  onRenamed: (artifactId: string, title: string) => void;
}): (artifactId: string, title: string) => void {
  return useCallback(
    (artifactId: string, title: string) => {
      void renameArtifactDocument(documentIds?.[artifactId] ?? artifactId, title)
        .then((persisted) => onRenamed(artifactId, persisted))
        .catch((error: unknown) => {
          console.warn("[chat-shell] the rename was refused:", error);
        });
    },
    [documentIds, onRenamed],
  );
}
