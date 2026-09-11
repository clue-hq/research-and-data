import dynamic from "next/dynamic";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import styles from "./brand-context.module.css";

const MarkdownSourceEditor = dynamic(() => import("./markdown-source-editor"), {
  ssr: false,
  loading: () => <div className={styles.emptyState} role="status">Loading editor…</div>,
});

export function KnowledgePanel({ controller }: { controller: BrandContextController }) {
  if (!controller.selectedDocument) {
    return <div className={styles.emptyState}>Select a knowledge document.</div>;
  }

  return (
    <>
      {controller.knowledgeEditor.error ? (
        <p className={styles.documentSaveError} role="alert">{controller.knowledgeEditor.error}</p>
      ) : null}
      {controller.knowledgeEditor.editorOpened ? (
        <div hidden={controller.knowledgeEditor.mode !== "edit"}>
          <MarkdownSourceEditor
            key={controller.selectedDocument.path}
            value={controller.knowledgeEditor.body}
            onChange={controller.knowledgeEditor.setBody}
            readOnly={controller.knowledgeEditor.busy}
          />
        </div>
      ) : null}
      {controller.knowledgeEditor.mode === "preview" ? (
        <article className={styles.markdownPreview}>
          <Markdown remarkPlugins={[remarkGfm]}>{controller.knowledgeEditor.body}</Markdown>
        </article>
      ) : null}
    </>
  );
}
