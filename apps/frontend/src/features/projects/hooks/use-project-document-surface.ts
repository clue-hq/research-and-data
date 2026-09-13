"use client";

import { useCallback } from "react";
import { useChatViewerIdentity } from "../data/projects-transport";
import type { ProjectDocumentDetail } from "../model/project-documents";
import { useProjectDocumentEditor } from "./use-project-document-editor";
import { useProjectDocument, useProjectDocuments } from "./use-project-documents";

export function useProjectDocumentSurface({ active, projectId, canWrite, refreshToken }: {
  active: boolean; projectId: string; canWrite: boolean; refreshToken?: number;
}) {
  const { workspaceId } = useChatViewerIdentity();
  const list = useProjectDocuments(projectId, { active: active && !!workspaceId, refreshToken });
  const detail = useProjectDocument(projectId, list.plan, active && !!workspaceId);
  const { acceptSave } = detail;
  const { reload } = list;
  const onSaved = useCallback((saved: ProjectDocumentDetail) => { acceptSave(saved); reload(); }, [acceptSave, reload]);
  const editor = useProjectDocumentEditor(detail.document, { projectId, workspaceId, canWrite, onSaved });
  return {
    document: detail.document, editor, loading: list.loading || (!!list.plan && !detail.document && !detail.error),
    error: !workspaceId ? "Your workspace is unavailable. Please sign in again." : list.error || detail.error,
    reload() { list.reload(); detail.reload(); },
  };
}
