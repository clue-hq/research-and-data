"use client";

import { AssetUploadDialog } from "./asset-upload-dialog";
import { ApplicationShell } from "@/components/shell/application-shell";
import { useBrandContextController } from "../hooks/use-brand-context-controller";
import { useBrandKitActions } from "../hooks/use-brand-kit-actions";
import { useKnowledgeRefresh } from "../hooks/use-knowledge-refresh";
import type { BrandContextInitialState, BrandContextWorkspace } from "../model/brand-context";
import type { OnboardingStatus } from "../model/brand-knowledge";
import type { BrandKitMeta } from "../model/brand-kit-actions";
import { AssetDetailDialog, AssetsHeader, AssetsPanel } from "./assets-panel";
import { BrandContextHeader } from "./brand-context-header";
import { BrandContextSidebar } from "./brand-context-sidebar";
import { ColorsPanel } from "./colors-panel";
import { KnowledgePanel } from "./knowledge-panel";
import styles from "./brand-context.module.css";
import { NewStyleDialog, NewTypefaceDialog, TypographyPanel } from "./typography-panel";

export function BrandContextScreen({
  initial,
  kit,
  onboarding,
  workspace,
  scopeKey,
  canWriteKnowledge,
}: {
  initial: BrandContextInitialState;
  kit: BrandKitMeta | null;
  onboarding: OnboardingStatus | null;
  workspace: BrandContextWorkspace;
  scopeKey: string;
  canWriteKnowledge: boolean;
}) {
  // Progressive fill: while onboarding is still publishing, re-read the server page as each
  // step lands so Knowledge fills in rather than waiting for the whole run.
  useKnowledgeRefresh({ initial: onboarding });
  const controller = useBrandContextController({ initial, workspace, scopeKey, canWriteKnowledge });
  const brandKitActions = useBrandKitActions(kit);

  return (
    <ApplicationShell activeHref="/brand-context">
      <div className={styles.workspace}>
        <BrandContextSidebar controller={controller} workspace={workspace} />
        <main className={styles.main}>
          {controller.section === "assets"
            ? <AssetsHeader controller={controller} />
            : <BrandContextHeader brandKitActions={brandKitActions} controller={controller} />}
          <div className={`${styles.panelScroll} clue-view-enter`} key={controller.section}>
            {controller.section === "colors" ? <ColorsPanel controller={controller} emptyMessage={brandKitActions.colorsEmptyMessage} workspace={workspace} /> : null}
            {controller.section === "typography" ? <TypographyPanel controller={controller} emptyMessage={brandKitActions.typographyEmptyMessage} /> : null}
            {controller.section === "assets" ? <AssetsPanel controller={controller} /> : null}
            {controller.section === "knowledge" ? <KnowledgePanel controller={controller} /> : null}
          </div>
        </main>
      </div>
      <AssetUploadDialog controller={controller} />
      <AssetDetailDialog controller={controller} />
      <NewTypefaceDialog controller={controller} />
      <NewStyleDialog controller={controller} />
    </ApplicationShell>
  );
}
