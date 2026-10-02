import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import styles from "./markdown.module.css";

export function MarkdownArticle({ markdown, className = "" }: { markdown: string; className?: string }) {
  return <article className={`${styles.prose} ${styles.article} ${className}`}>
    <Markdown remarkPlugins={[remarkGfm]} components={{
      table: ({ children }) => <div className={styles.tableScroll} tabIndex={0} role="region" aria-label="Scrollable table"><table>{children}</table></div>,
    }}>{markdown}</Markdown>
  </article>;
}
