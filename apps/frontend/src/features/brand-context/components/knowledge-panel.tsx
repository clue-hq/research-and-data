import type { BrandContextController } from "../hooks/use-brand-context-controller";
import { MarkdownSourceEditor } from "./markdown-source-editor";
import styles from "./brand-context.module.css";

function renderInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
      : part,
  );
}

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
      {controller.markdownBlocks.map((block, index) => {
        if (block.type === "heading") {
          if (block.depth === 1) return <h2 key={index}>{block.text}</h2>;
          if (block.depth === 2) return <h3 key={index}>{block.text}</h3>;
          return <h4 key={index}>{block.text}</h4>;
        }
        if (block.type === "list") {
          return <ul key={index}>{block.items?.map((item) => <li key={item}>{renderInline(item)}</li>)}</ul>;
        }
        return <p key={index}>{renderInline(block.text ?? "")}</p>;
      })}
    </article>
  );
}
