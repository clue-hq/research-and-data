import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import styles from "./brand-context.module.css";

export function KnowledgePanel({ controller }: { controller: BrandContextController }) {
  if (!controller.selectedDocument) {
    return <div className={styles.emptyState}>Select a knowledge document.</div>;
  }

  return (
    <article className={styles.markdownPreview}>
      <Markdown remarkPlugins={[remarkGfm]}>{controller.selectedDocument.body}</Markdown>
    </article>
  );
}
