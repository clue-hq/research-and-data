import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import { MarkdownSourceEditor } from "./markdown-source-editor";
import styles from "./brand-context.module.css";

export function KnowledgePanel({ controller }: { controller: BrandContextController }) {
  if (!controller.selectedDocument) {
    return <div className={styles.emptyState}>Select a knowledge document.</div>;
  }

  if (controller.documentMode === "edit") {
    return (
      <div className={styles.markdownEditorShell}>
        <MarkdownSourceEditor
          label={`Edit ${controller.selectedDocument.name}`}
          onChange={controller.setDocumentBody}
          value={controller.documentBody}
        />
      </div>
    );
  }

  return (
    <article className={styles.markdownPreview}>
      <Markdown remarkPlugins={[remarkGfm]}>{controller.documentBody}</Markdown>
    </article>
  );
}
