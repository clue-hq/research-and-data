"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { renameArtifactDocument } from "@/features/artifacts/data/artifact-document.repository";
import { DocumentRenameError } from "@/features/design-editor/engine/scene/documentStore";
import { AGENT_RUN_LOCK_NOTE } from "../model/agent-run-lock";

/** A rename the server refused because a design run drives the document. */
export interface ArtifactRenameRefusal {
  artifactId: string;
  note: string;
}

export interface ArtifactRename {
  rename: (artifactId: string, title: string) => void;
  /** Set when the last rename lost the race to a design run (409
   * `document.agent_run_active`); `note` is the lock's own sentence. */
  refusal: ArtifactRenameRefusal | null;
}

function isAgentRunRefusal(error: unknown): boolean {
  return (
    error instanceof DocumentRenameError &&
    error.status === 409 &&
    error.code === "document.agent_run_active"
  );
}

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
 *
 * K1-5 (founder ruling 2026-10-16): no rename while a design run drives the
 * document. The mounts disable Rename under their agent-run lock; a rename
 * that still loses the race (the run started before the lock knew) is refused
 * by the server, and `refusal` then carries the lock's sentence for the header
 * to show. It clears on the next rename that lands and when the run lets go
 * (`locked` falls back to false), because the sentence is no longer true then.
 */
export function useArtifactRename({
  documentIds,
  locked = false,
  onRenamed,
  rename = renameArtifactDocument,
}: {
  /** artifact id → design-document id; absent entries fall back to the artifact id. */
  documentIds?: Record<string, string>;
  /** The mount's agent-run lock for the open document. */
  locked?: boolean;
  onRenamed: (artifactId: string, title: string) => void;
  /** The document write; the repository's own by default. */
  rename?: (documentId: string, title: string) => Promise<string>;
}): ArtifactRename {
  const [refusal, setRefusal] = useState<ArtifactRenameRefusal | null>(null);
  const wasLocked = useRef(locked);
  useEffect(() => {
    if (wasLocked.current && !locked) setRefusal(null);
    wasLocked.current = locked;
  }, [locked]);
  const renameArtifact = useCallback(
    (artifactId: string, title: string) => {
      void rename(documentIds?.[artifactId] ?? artifactId, title)
        .then((persisted) => {
          setRefusal(null);
          onRenamed(artifactId, persisted);
        })
        .catch((error: unknown) => {
          if (isAgentRunRefusal(error)) {
            setRefusal({ artifactId, note: AGENT_RUN_LOCK_NOTE });
            return;
          }
          console.warn("[chat-shell] the rename was refused:", error);
        });
    },
    [documentIds, onRenamed, rename],
  );
  return { rename: renameArtifact, refusal };
}
