import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { ProductActionsController } from "../hooks/use-product-actions";
import type { BrandContextSection, BrandContextWorkspace, BrandKnowledgeDocument } from "../model/brand-context";
import { productOfPage } from "../model/product-links";
import { BrandContextIcon, type BrandContextIconName } from "./brand-context-icon";
import { PendingProductPages, ProductFolderFooter, ProductMenu } from "./product-actions";
import styles from "./brand-context.module.css";

const brandKitItems: Array<{
  icon: BrandContextIconName;
  id: BrandContextSection;
  label: string;
}> = [
  { icon: "colors", id: "colors", label: "Colors" },
  { icon: "typography", id: "typography", label: "Typography" },
  { icon: "assets", id: "assets", label: "Assets" },
];

function DocumentButton({ controller, document }: { controller: BrandContextController; document: BrandKnowledgeDocument }) {
  return (
    <button
      aria-current={controller.selectedDocument?.id === document.id ? "page" : undefined}
      className={`${styles.documentItem} ${controller.section === "knowledge" && controller.selectedDocument?.id === document.id ? styles.contextNavItemActive : ""}`}
      onClick={() => controller.selectDocument(document.id)}
      title={document.name}
      type="button"
    >
      <span aria-hidden="true" className={styles.documentTreeRule} />
      <span className={styles.documentItemContent}>
        <BrandContextIcon className={styles.documentIcon} name="document" size={16} />
        <span className={styles.documentTitle}>
          <span className={styles.documentTitleText}>{document.name}</span>
        </span>
        {document.generated ? <span className={styles.generatedBadge}>Generated</span> : null}
      </span>
    </button>
  );
}

export function BrandContextSidebar({
  controller,
  productActions,
  workspace,
}: {
  controller: BrandContextController;
  productActions?: ProductActionsController;
  workspace: BrandContextWorkspace;
}) {
  return (
    <aside aria-label="Brand context navigation" className={styles.contextSidebar}>
      <div className={styles.contextSidebarTitle}>Brand context</div>
      <div className={styles.contextSidebarScroll}>
        <div className={styles.sidebarSection}>
          <div className={styles.sidebarLabel}>Brand kit</div>
          <nav className={styles.sidebarItems}>
            {brandKitItems.map((item) => (
              <button
                aria-current={controller.section === item.id ? "page" : undefined}
                className={`${styles.contextNavItem} ${controller.section === item.id ? styles.contextNavItemActive : ""}`}
                key={item.id}
                onClick={() => controller.selectSection(item.id)}
                type="button"
              >
                <BrandContextIcon name={item.icon} />
                <span>{item.label}</span>
              </button>
            ))}
          </nav>
        </div>

        <div className={styles.sidebarSection}>
          <div className={styles.sidebarLabelRow}>
            <div className={styles.sidebarLabel}>Knowledge</div>
            <div className={styles.sidebarLabelActions}>
              <button aria-label="New knowledge folder" className={styles.sidebarActionButton} title="New folder" type="button">
                <BrandContextIcon name="folderPlus" size={12} />
              </button>
              <button aria-label="New knowledge document" className={styles.sidebarActionButton} title="New document" type="button">
                <BrandContextIcon name="plus" size={12} />
              </button>
            </div>
          </div>
          <div className={styles.sidebarItems}>
            {workspace.knowledgeFolders.map((folder) => {
              const open = controller.openFolderIds.has(folder.id);
              return (
                <div key={folder.id}>
                  <button
                    aria-expanded={open}
                    className={styles.contextNavItem}
                    onClick={() => controller.toggleFolder(folder.id)}
                    type="button"
                  >
                    <BrandContextIcon name={open ? "folderOpen" : "folderClosed"} />
                    <span>{folder.label}</span>
                  </button>
                  {open ? (
                    <div className={styles.folderChildren}>
                      {folder.documents.map((document) => {
                        // A product's page carries that product's actions (spec 2026-10-15 §10).
                        const product = productActions
                          ? productOfPage(document, productActions.products)
                          : undefined;
                        return product && productActions ? (
                          <div className={styles.productRow} key={document.id}>
                            <DocumentButton controller={controller} document={document} />
                            <ProductMenu actions={productActions} product={product} />
                          </div>
                        ) : (
                          <DocumentButton controller={controller} document={document} key={document.id} />
                        );
                      })}
                      {folder.id === "product" && productActions ? (
                        <>
                          <PendingProductPages actions={productActions} />
                          <ProductFolderFooter actions={productActions} />
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </aside>
  );
}
