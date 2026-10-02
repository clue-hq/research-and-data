"use client";

import { useCallback } from "react";
import { useChatViewerIdentity } from "../data/projects-transport";
import { selectedProjectDocument, type ProjectDocumentDetail } from "../model/project-documents";
import { useProjectDocumentEditor } from "./use-project-document-editor";
import { useProjectDocument, useProjectDocuments } from "./use-project-documents";

export function useProjectDocumentSurface({ active, projectId, canWrite, list, documentPath }: {
  active: boolean; projectId: string; canWrite: boolean;
  list: ReturnType<typeof useProjectDocuments>; documentPath?: string;
}) {
  const { workspaceId } = useChatViewerIdentity();
  const selected = selectedProjectDocument(list.documents, documentPath);
  const detail = useProjectDocument(projectId, selected, active && !!workspaceId);
  const { acceptSave } = detail;
  const { reload } = list;
  const onSaved = useCallback((saved: ProjectDocumentDetail) => { acceptSave(saved); reload(); }, [acceptSave, reload]);
  const editor = useProjectDocumentEditor(detail.document, { projectId, workspaceId, canWrite, onSaved });
  return {
    document: detail.document, editor, loading: list.loading || (!!selected && !detail.document && !detail.error),
    error: !workspaceId ? "Your workspace is unavailable. Please sign in again." : list.error || detail.error || (documentPath && !list.loading && !selected ? "This document is no longer available in this project." : null),
    reload() { list.reload(); detail.reload(); },
  };
}
