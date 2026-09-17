"use client";

import { useCallback, useEffect, useState } from "react";
import { readProjectDocument, readProjectDocuments } from "../data/project-document-queries";
import { planDocumentOf, type ProjectDocument, type ProjectDocumentDetail } from "../model/project-documents";

/** One stable empty list, so a consumer that memoizes on `documents` is not handed a new
 * identity on every render while the first read is still in flight. */
const NO_DOCUMENTS: ProjectDocument[] = [];

/** Reads on opening/reopening and on plan arrival; failed reads never become empty lists. */
export function useProjectDocuments(projectId: string, { active, refreshToken = 0 }: { active: boolean; refreshToken?: number }) {
  const [result, setResult] = useState<{ projectId: string; requestKey: string; documents: ProjectDocument[]; error: string | null }>();
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  const requestKey = JSON.stringify([projectId, refreshToken, revision]);
  const current = result?.projectId === projectId ? result : undefined;

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void readProjectDocuments(projectId, controller.signal).then((documents) => {
      if (!controller.signal.aborted) setResult({ projectId, requestKey, documents, error: null });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setResult((previous) => ({ projectId, requestKey,
        documents: previous?.projectId === projectId ? previous.documents : [],
        error: error instanceof Error ? error.message : "Could not load project documents.",
      }));
    });
    return () => controller.abort();
  }, [active, projectId, requestKey]);

  const documents = current?.documents ?? NO_DOCUMENTS;
  return { documents, plan: planDocumentOf(documents), loading: active && current?.requestKey !== requestKey, error: current?.error, reload };
}

/** Detail cache is path-keyed, so a new immutable version does not unmount a dirty editor. */
export function useProjectDocument(projectId: string, summary: ProjectDocument | null, active: boolean) {
  const [details, setDetails] = useState<Record<string, ProjectDocumentDetail>>({});
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [request, setRequest] = useState(0);
  const key = JSON.stringify([projectId, summary?.path]);
  const id = summary?.id;
  const reload = useCallback(() => setRequest((value) => value + 1), []);
  useEffect(() => {
    if (!active || !id) return;
    const controller = new AbortController();
    void readProjectDocument(projectId, id, controller.signal).then((document) => {
      if (controller.signal.aborted) return;
      setDetails((current) => {
        const existing = current[key];
        return existing && existing.version > document.version ? current : { ...current, [key]: document };
      });
      setError(null);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError({ key, message: cause instanceof Error ? cause.message : "Could not load this document." });
    });
    return () => controller.abort();
  }, [active, id, key, projectId, request]);

  const acceptSave = useCallback((document: ProjectDocumentDetail) => {
    setDetails((current) => ({ ...current, [JSON.stringify([projectId, document.path])]: document }));
    setError(null);
  }, [projectId]);
  return { document: details[key], error: error?.key === key ? error.message : null, reload, acceptSave };
}
