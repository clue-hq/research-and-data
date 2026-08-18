import type { BrandContextController } from "../hooks/use-brand-context-controller";
import { BrandContextIcon } from "./brand-context-icon";
import styles from "./brand-context.module.css";

function Segment({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      aria-pressed={active}
      className={`${styles.segment} ${active ? styles.segmentActive : ""}`}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

export function BrandContextHeader({ controller }: { controller: BrandContextController }) {
  const labels = {
    assets: "Assets",
    colors: "Colors",
    knowledge: controller.selectedDocument?.name ?? "Knowledge",
    typography: "Typography",
  };

  if (controller.section === "knowledge" && controller.selectedDocument) {
    return (
      <div className={styles.documentHeaderStack}>
        <header className={styles.documentNavigationBar}>
          <nav aria-label="Document breadcrumb" className={styles.documentBreadcrumbs}>
            <span className={styles.documentParentLabel}>Company</span>
            <BrandContextIcon className={styles.documentBreadcrumbSlash} name="slash" size={8} />
            <span className={styles.documentFileLabel}>
              <BrandContextIcon name="document" size={12} />
              brand-kit.md
            </span>
          </nav>
          <button
            aria-label={controller.shareCopied ? "Document link copied" : "Copy document link"}
            className={styles.documentLinkButton}
            onClick={controller.shareCurrentView}
            type="button"
          >
            <BrandContextIcon name="link" size={14} />
          </button>
        </header>

        <header className={styles.documentTitleBar}>
          <h1>{controller.selectedDocument.name}</h1>
          <div aria-label="Document mode" className={styles.documentModeControl}>
            <Segment active={controller.documentMode === "preview"} onClick={() => controller.setDocumentMode("preview")}>
              <BrandContextIcon name="eye" size={12} />
              Preview
            </Segment>
            <Segment active={controller.documentMode === "edit"} onClick={() => controller.setDocumentMode("edit")}>
              <BrandContextIcon name="code" size={12} />
              Edit
            </Segment>
          </div>
        </header>
      </div>
    );
  }

  return (
    <header className={styles.pageHeader}>
      <div className={styles.pageHeadingGroup}>
        <h1>{labels[controller.section]}</h1>
      </div>

      <div className={styles.headerActions}>
        {controller.section === "colors" ? (
          <div aria-label="Brand color palette" className={styles.colorModeControl}>
            <Segment active={controller.colorMode === "light"} onClick={() => controller.setColorMode("light")}><BrandContextIcon name="sun" size={12} /> Light</Segment>
            <Segment active={controller.colorMode === "dark"} onClick={() => controller.setColorMode("dark")}><BrandContextIcon name="moon" size={12} /> Dark</Segment>
          </div>
        ) : null}

      </div>
    </header>
  );
}
