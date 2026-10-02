"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { readProjectDocument } from "../data/project-document-queries";
import { useProjectDocuments } from "./use-project-documents";

/** Named, on-demand tabs. Stable paths own drafts; immutable IDs resolve through the repository. */
export function useProjectDocumentTabs({ projectId, active, initialPath, writeRevision, writtenDocumentId, onOpen, onEmpty }: {
  projectId: string; active: boolean; initialPath?: string; writeRevision: number;
  writtenDocumentId?: string; onOpen: () => void; onEmpty: () => void;
}) {
  const [paths, setPaths] = useState<string[]>(() => initialPath ? [initialPath] : []);
  const [visited, setVisited] = useState<string[]>(() => initialPath ? [initialPath] : []);
  const [selectedPath, setSelectedPath] = useState(initialPath);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const request = useRef<AbortController | null>(null);
  const handledWrite = useRef(0);
  const list = useProjectDocuments(projectId, { active: active || writeRevision > 0, refreshToken: writeRevision });
  const { reload } = list;

  const openPath = useCallback((path: string) => {
    setPaths((current) => current.includes(path) ? current : [...current, path]);
    setVisited((current) => current.includes(path) ? current : [...current, path]);
    setSelectedPath(path);
    setError(null);
    onOpen();
  }, [onOpen]);

  const openById = useCallback(async (id: string) => {
    request.current?.abort();
    const pending = new AbortController();
    request.current = pending;
    setOpening(true);
    setError(null);
    try {
      // Even a historic card's version identifies the stable path. The surface then reads
      // the current listed revision, never silently edits that historic version.
      const document = await readProjectDocument(projectId, id, pending.signal);
      if (!pending.signal.aborted) { openPath(document.path); reload(); }
    } catch (cause) {
      if (!pending.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not open this document.");
    } finally {
      if (!pending.signal.aborted) setOpening(false);
    }
  }, [openPath, projectId, reload]);

  useEffect(() => () => request.current?.abort(), [projectId]);
  useEffect(() => {
    if (writeRevision <= handledWrite.current || !writtenDocumentId) return;
    handledWrite.current = writeRevision;
    void openById(writtenDocumentId);
  }, [openById, writeRevision, writtenDocumentId]);

  return {
    list, paths, visited, selectedPath, openById, opening, error,
    openPath(path: string) { request.current?.abort(); setOpening(false); openPath(path); },
    close(path: string) {
      const remaining = paths.filter((entry) => entry !== path);
      setPaths(remaining);
      if (selectedPath === path) {
        const next = remaining.at(-1);
        setSelectedPath(next);
        if (next) onOpen(); else onEmpty();
      }
    },
  };
}
