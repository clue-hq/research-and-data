import { Fragment } from "react";
import type { BrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandKitActionsController } from "../hooks/use-brand-kit-actions";
import { knowledgeBreadcrumb } from "../model/knowledge-breadcrumb";
import { BrandContextIcon } from "./brand-context-icon";
import { BrandKitActionsRow } from "./brand-kit-actions";
import styles from "./brand-context.module.css";

function Segment({
  active,
  children,
  onClick,
  disabled = false,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      aria-pressed={active}
      disabled={disabled}
      className={`${styles.segment} ${active ? styles.segmentActive : ""}`}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

export function BrandContextHeader({
  brandKitActions,
  controller,
}: {
  brandKitActions: BrandKitActionsController;
  controller: BrandContextController;
}) {
  const labels = {
    assets: "Assets",
    colors: "Colors",
    knowledge: controller.selectedDocument?.name ?? "Knowledge",
    typography: "Typography",
  };

  if (controller.section === "knowledge" && controller.selectedDocument) {
    // The trail is the selected document's own path — the same value the route
    // carries as `?file=`. The dummy hardcoded `Company / brand-kit.md` here,
    // which read as a lie the moment the store served any other document.
    const breadcrumb = knowledgeBreadcrumb(controller.selectedDocument.path);
    return (
      <div className={styles.documentHeaderStack}>
        <header className={styles.documentNavigationBar}>
          <nav aria-label="Document breadcrumb" className={styles.documentBreadcrumbs}>
            {breadcrumb.map((segment, index) => (
              <Fragment key={`${segment.kind}-${index}-${segment.label}`}>
                {index > 0 ? (
                  <BrandContextIcon
                    className={styles.documentBreadcrumbSlash}
                    name="slash"
                    size={8}
                  />
                ) : null}
                {segment.kind === "folder" ? (
                  <span className={styles.documentParentLabel}>{segment.label}</span>
                ) : (
                  <span className={styles.documentFileLabel}>
                    <BrandContextIcon name="document" size={12} />
                    {segment.label}
                  </span>
                )}
              </Fragment>
            ))}
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
          <div className={styles.headerActions}>
            <BrandKitActionsRow controller={brandKitActions} />
            <div aria-label="Document view" className={styles.segmentedControl} role="group">
              <Segment active={controller.knowledgeEditor.mode === "preview"} onClick={() => controller.knowledgeEditor.setMode("preview")}>
                <BrandContextIcon name="eye" size={12} /> Preview
              </Segment>
              <Segment active={controller.knowledgeEditor.mode === "edit"} disabled={!controller.knowledgeEditor.canEdit} onClick={() => controller.knowledgeEditor.setMode("edit")}>
                <BrandContextIcon name="edit" size={12} /> Edit
              </Segment>
            </div>
            {controller.knowledgeEditor.dirty ? (
              <>
                <button className={styles.secondaryButton} disabled={controller.knowledgeEditor.busy} onClick={controller.knowledgeEditor.discard} type="button">Discard changes</button>
                <button className={styles.primaryButton} disabled={!controller.knowledgeEditor.canSave} onClick={controller.knowledgeEditor.save} type="button">
                  {controller.knowledgeEditor.saving ? "Saving…" : "Save changes"}
                </button>
              </>
            ) : null}
            {controller.knowledgeEditor.saved ? <span className={styles.documentSaveStatus} role="status">Saved</span> : null}
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
        <BrandKitActionsRow controller={brandKitActions} />
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
