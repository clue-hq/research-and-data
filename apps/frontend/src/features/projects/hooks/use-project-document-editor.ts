"use client";

import { useCallback, useMemo } from "react";
import { useVersionedMarkdownEditor } from "@/components/markdown/use-versioned-markdown-editor";
import { saveProjectDocument } from "../data/project-document-actions";
import type { ProjectDocumentDetail } from "../model/project-documents";

type EditorDocument = ProjectDocumentDetail & { body: string };
const editorDocument = (document: ProjectDocumentDetail): EditorDocument => ({ ...document, body: document.markdown });

export function useProjectDocumentEditor(document: ProjectDocumentDetail | undefined, {
  projectId, workspaceId, canWrite, onSaved,
}: { projectId: string; workspaceId: string | null; canWrite: boolean; onSaved: (saved: ProjectDocumentDetail) => void }) {
  const base = useMemo(() => document ? editorDocument(document) : undefined, [document]);
  const saveDocument = useCallback(async (current: EditorDocument, body: string) => (
    editorDocument(await saveProjectDocument(projectId, current, body))
  ), [projectId]);
  const editor = useVersionedMarkdownEditor(base, {
    scopeKey: JSON.stringify([workspaceId, projectId]), canWrite: canWrite && !!workspaceId,
    saveDocument, onSaved,
  });
  return { ...editor, canSave: editor.canSave && editor.body.trim().length > 0 && editor.body.length <= 1_000_000 };
}
