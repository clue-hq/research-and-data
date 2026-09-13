"use client";

import { MarkdownArticle } from "@/components/markdown/markdown-article";
import { MarkdownEditor } from "@/components/markdown/markdown-editor";
import type { useProjectDocuments } from "../hooks/use-project-documents";
import { useProjectDocumentSurface } from "../hooks/use-project-document-surface";
import { ProjectIcon } from "./project-icon";
import styles from "./project-document-surface.module.css";

export function ProjectDocumentSurface(props: {
  active: boolean;
  projectId: string;
  canWrite: boolean;
  list: ReturnType<typeof useProjectDocuments>;
  documentPath?: string;
}) {
  const state = useProjectDocumentSurface(props);
  const { document, editor } = state;
  if (!document) {
    return (
      <section className={styles.empty} aria-label="Project document">
        {state.error ? (
          <>
            <p role="alert">{state.error}</p>
            <button type="button" className={styles.secondary} onClick={state.reload}>Try again</button>
          </>
        ) : state.loading ? (
          <p role="status">Loading document…</p>
        ) : (
          <>
            <ProjectIcon name="file-text" size={24} />
            <h2>No document selected.</h2>
            <p>Open a file from Gallery to view or edit it.</p>
          </>
        )}
      </section>
    );
  }
  return (
    <section className={styles.surface} aria-label="Project document" data-document-path={document.path}>
      <header className={styles.header}>
        <div className={styles.name}>
          <ProjectIcon name="file-text" size={12} />
          <span title={document.title}>{document.title}</span>
        </div>
        <div className={styles.controls}>
          {editor.mode === "edit" ? (
            <span role="status" className={styles.status}>
              {editor.saving ? "Saving…" : editor.dirty ? "Unsaved changes" : "Saved"}
            </span>
          ) : null}
          {!editor.canEdit ? (
            <span className={styles.status}>Read only</span>
          ) : (
            <div className={styles.segmented} aria-label="Document view">
              <button type="button" aria-pressed={editor.mode === "preview"} onClick={() => editor.setMode("preview")}>
                <ProjectIcon name="visibility" size={14} />Preview
              </button>
              <button type="button" aria-pressed={editor.mode === "edit"} onClick={() => editor.setMode("edit")}>
                <ProjectIcon name="edit" size={14} />Edit
              </button>
            </div>
          )}
          {editor.mode === "edit" ? (
            <>
              <button className={styles.secondary} type="button" disabled={!editor.dirty || editor.busy} onClick={editor.discard}>Discard</button>
              <button className={styles.primary} type="button" disabled={!editor.canSave} onClick={() => void editor.save()}>Save</button>
            </>
          ) : null}
        </div>
      </header>
      <div className={styles.scroll}>
        {state.error ? (
          <div className={styles.notice}>
            <p role="alert">{state.error}</p>
            <button className={styles.secondary} type="button" onClick={state.reload}>Try again</button>
          </div>
        ) : null}
        {editor.error ? (
          <div className={styles.notice}>
            <p role="alert">{editor.error}</p>
            <button className={styles.secondary} type="button" disabled={editor.busy} onClick={state.reload}>Check for updates</button>
          </div>
        ) : null}
        {editor.editorOpened ? (
          <div className={styles.editor} hidden={editor.mode !== "edit"} inert={editor.busy} aria-busy={editor.busy}>
            <MarkdownEditor
              documentKey={editor.documentKey}
              resetKey={editor.resetKey}
              value={editor.body}
              onChange={editor.setBody}
              onStatusChange={editor.setEditorStatus}
              readOnly={!editor.canEdit}
            />
          </div>
        ) : null}
        {editor.mode === "preview" ? <MarkdownArticle markdown={editor.body} /> : null}
      </div>
    </section>
  );
}
