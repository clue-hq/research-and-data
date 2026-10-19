"use client";

import { useEffect, useMemo, useState } from "react";
import { AssetUploadDialog } from "./asset-upload-dialog";
import { ApplicationShell } from "@/components/shell/application-shell";
import { useBrandContextController } from "../hooks/use-brand-context-controller";
import { useBrandKitActions } from "../hooks/use-brand-kit-actions";
import { useKnowledgeRefresh } from "../hooks/use-knowledge-refresh";
import { useProductActions } from "../hooks/use-product-actions";
import type { BrandContextInitialState, BrandContextWorkspace, BrandKnowledgeFolder } from "../model/brand-context";
import { emptyBrandContextWorkspace, withPlatformFolders } from "../model/brand-context-mapping";
import type { BrandProducts, OnboardingStatus } from "../model/brand-knowledge";
import type { BrandKitMeta } from "../model/brand-kit-actions";
import type { MeasuredBrandView } from "../model/measured-view";
import { AssetDetailDialog, AssetsHeader, AssetsPanel } from "./assets-panel";
import { BrandContextHeader } from "./brand-context-header";
import { BrandContextSidebar } from "./brand-context-sidebar";
import { ColorsPanel } from "./colors-panel";
import { KnowledgePanel } from "./knowledge-panel";
import { MeasuredStylesPanel } from "./measured-styles-panel";
import { MotionPanel } from "./motion-panel";
import { ProductDialogs } from "./product-actions";
import { SpacingPanel } from "./spacing-panel";
import styles from "./brand-context.module.css";
import { NewStyleDialog, NewTypefaceDialog, TypographyPanel } from "./typography-panel";

/** The brand kit as the server read it — streamed after the documents (2026-10-15). */
export interface StreamedKitView {
  kit: BrandKitMeta | null;
  /** What the extraction measured (Task X6); null for a kit made before measurement. */
  measured: MeasuredBrandView | null;
  workspace: BrandContextWorkspace;
}

/** The latest value of a streamed read; the previous one stays on screen while a refresh reads. */
function useStreamed<T>(promise: Promise<T>): T | null {
  const [value, setValue] = useState<T | null>(null);
  useEffect(() => {
    let live = true;
    void promise.then((resolved) => {
      if (live) setValue(resolved);
    });
    return () => {
      live = false;
    };
  }, [promise]);
  return value;
}

export function BrandContextScreen({
  initial,
  kitView: kitViewRead,
  knowledgeFolders,
  onboarding,
  products = null,
  scopeKey,
  canWriteKnowledge,
}: {
  initial: BrandContextInitialState;
  kitView: Promise<StreamedKitView>;
  knowledgeFolders: BrandKnowledgeFolder[];
  onboarding: OnboardingStatus | null;
  products?: BrandProducts | null;
  scopeKey: string;
  canWriteKnowledge: boolean;
}) {
  const kitView = useStreamed(kitViewRead);
  const kitLoading = kitView === null;
  const kit = kitView?.kit ?? null;
  const measured = kitView?.measured ?? null;
  const workspace = useMemo(
    () => withPlatformFolders(kitView?.workspace ?? emptyBrandContextWorkspace(), knowledgeFolders),
    [kitView, knowledgeFolders],
  );
  // Progressive fill: while onboarding is still publishing, re-read the server page as each
  // step lands so Knowledge fills in rather than waiting for the whole run.
  useKnowledgeRefresh({ initial: onboarding });
  const controller = useBrandContextController({ initial, workspace, scopeKey, canWriteKnowledge });
  const brandKitActions = useBrandKitActions(kit);
  const productActions = useProductActions(products, canWriteKnowledge, controller.openDocumentPath);

  return (
    <ApplicationShell activeHref="/brand-context">
      <div className={styles.workspace}>
        <BrandContextSidebar controller={controller} measured={measured} productActions={productActions} workspace={workspace} />
        <main className={styles.main}>
          {controller.section === "assets"
            ? <AssetsHeader controller={controller} />
            : <BrandContextHeader brandKitActions={brandKitActions} controller={controller} productActions={productActions} />}
          <div className={`${styles.panelScroll} clue-view-enter`} key={controller.section}>
            {kitLoading && controller.section !== "knowledge" ? (
              <div className={styles.emptyState} role="status">Loading the brand kit…</div>
            ) : null}
            {!kitLoading && controller.section === "colors" ? <ColorsPanel controller={controller} emptyMessage={brandKitActions.colorsEmptyMessage} measuredGroups={measured?.colorGroups} workspace={workspace} /> : null}
            {!kitLoading && controller.section === "typography" ? <TypographyPanel controller={controller} emptyMessage={brandKitActions.typographyEmptyMessage} /> : null}
            {!kitLoading && controller.section === "components" ? <MeasuredStylesPanel measured={measured} typefaces={controller.typefaces} /> : null}
            {!kitLoading && controller.section === "spacing" ? <SpacingPanel measured={measured} /> : null}
            {!kitLoading && controller.section === "motion" ? <MotionPanel measured={measured} /> : null}
            {!kitLoading && controller.section === "assets" ? <AssetsPanel controller={controller} /> : null}
            {controller.section === "knowledge" ? <KnowledgePanel controller={controller} productActions={productActions} /> : null}
          </div>
        </main>
      </div>
      <AssetUploadDialog controller={controller} />
      <AssetDetailDialog controller={controller} />
      <NewTypefaceDialog controller={controller} />
      <NewStyleDialog controller={controller} />
      <ProductDialogs actions={productActions} />
    </ApplicationShell>
  );
}
