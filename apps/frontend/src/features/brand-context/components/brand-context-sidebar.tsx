import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandContextSection, BrandContextWorkspace } from "../model/brand-context";
import { BrandContextIcon, type BrandContextIconName } from "./brand-context-icon";
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

export function BrandContextSidebar({
  controller,
  workspace,
}: {
  controller: BrandContextController;
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
                      {folder.documents.map((document) => (
                        <button
                          aria-current={controller.selectedDocument?.id === document.id ? "page" : undefined}
                          className={`${styles.documentItem} ${controller.section === "knowledge" && controller.selectedDocument?.id === document.id ? styles.contextNavItemActive : ""}`}
                          key={document.id}
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
                          </span>
                        </button>
                      ))}
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
