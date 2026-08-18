"use client";

import { ApplicationShell } from "@/components/shell/application-shell";
import { useBrandContextController } from "../hooks/use-brand-context-controller";
import type { BrandContextInitialState, BrandContextWorkspace } from "../model/brand-context";
import { AssetDetailDialog, AssetsHeader, AssetsPanel } from "./assets-panel";
import { BrandContextHeader } from "./brand-context-header";
import { BrandContextSidebar } from "./brand-context-sidebar";
import { ColorsPanel } from "./colors-panel";
import { KnowledgePanel } from "./knowledge-panel";
import styles from "./brand-context.module.css";
import { NewStyleDialog, NewTypefaceDialog, TypographyPanel } from "./typography-panel";

export function BrandContextScreen({
  initial,
  workspace,
}: {
  initial: BrandContextInitialState;
  workspace: BrandContextWorkspace;
}) {
  const controller = useBrandContextController({ initial, workspace });

  return (
    <ApplicationShell activeHref="/brand-context">
      <div className={styles.workspace}>
        <BrandContextSidebar controller={controller} workspace={workspace} />
        <main className={styles.main}>
          {controller.section === "assets"
            ? <AssetsHeader controller={controller} />
            : <BrandContextHeader controller={controller} />}
          <div className={`${styles.panelScroll} clue-view-enter`} key={controller.section}>
            {controller.section === "colors" ? <ColorsPanel controller={controller} workspace={workspace} /> : null}
            {controller.section === "typography" ? <TypographyPanel controller={controller} /> : null}
            {controller.section === "assets" ? <AssetsPanel controller={controller} /> : null}
            {controller.section === "knowledge" ? <KnowledgePanel controller={controller} /> : null}
          </div>
        </main>
      </div>
      <AssetDetailDialog controller={controller} />
      <NewTypefaceDialog controller={controller} />
      <NewStyleDialog controller={controller} />
    </ApplicationShell>
  );
}
