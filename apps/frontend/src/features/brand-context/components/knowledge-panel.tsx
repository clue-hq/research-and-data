import { MarkdownArticle } from "@/components/markdown/markdown-article";
import { MarkdownEditor } from "@/components/markdown/markdown-editor";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { ProductActionsController } from "../hooks/use-product-actions";
import { ProductCatalogNotes } from "./product-actions";
import styles from "./brand-context.module.css";

export function KnowledgePanel({
  controller, productActions,
}: {
  controller: BrandContextController;
  productActions?: ProductActionsController;
}) {
  if (!controller.selectedDocument) {
    return <div className={styles.emptyState}>Select a knowledge document.</div>;
  }

  return (
    <>
      {controller.selectedDocument.generated && productActions ? (
        <ProductCatalogNotes actions={productActions} />
      ) : null}
      {controller.knowledgeEditor.error ? (
        <p className={styles.documentSaveError} role="alert">{controller.knowledgeEditor.error}</p>
      ) : null}
      {controller.knowledgeEditor.editorOpened ? (
        <div className={styles.knowledgeEditorFrame} hidden={controller.knowledgeEditor.mode !== "edit"} inert={controller.knowledgeEditor.busy} aria-busy={controller.knowledgeEditor.busy}>
          <MarkdownEditor
            documentKey={controller.knowledgeEditor.documentKey}
            resetKey={controller.knowledgeEditor.resetKey}
            value={controller.knowledgeEditor.body}
            onChange={controller.knowledgeEditor.setBody}
            readOnly={!controller.knowledgeEditor.canEdit}
            onStatusChange={controller.knowledgeEditor.setEditorStatus}
          />
        </div>
      ) : null}
      {controller.knowledgeEditor.mode === "preview" ? (
        <MarkdownArticle markdown={controller.knowledgeEditor.body} />
      ) : null}
    </>
  );
}
