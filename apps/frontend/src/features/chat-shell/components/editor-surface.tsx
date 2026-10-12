"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";
import { useArtifactRename } from "../hooks/use-artifact-rename";
import {
  useEditorShellController,
  type EditorShellInitialState,
} from "../hooks/use-editor-shell-controller";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import { useDocumentAgentRun } from "@/features/design-editor/hooks/use-document-agent-run";
import { useSceneEditingSession } from "@/features/design-editor/hooks/use-scene-editing-session";
import { useSiteEditingSession } from "@/features/site-editor/hooks/use-site-editing-session";
import { useWebEditingSession } from "@/features/design-editor/hooks/use-web-editing-session";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { chatShellKindForCard } from "../model/artifact-kind";
import { ArtifactStage } from "./artifact-stage";
import { AssetLibraryPanel } from "./asset-library-panel";
import { ImageInspector } from "./image-inspector";
import { SiteImageField } from "./site-image-field";
import { SiteInspector } from "./site-inspector";
import { WebInspector } from "./web-inspector";
import styles from "./chat-shell.module.css";

// Full-width editor surface at the canonical artifact route
// (/projects/{projectId}/artifacts/{artifactId}); the composition the branch's
// chat-shell-view.tsx provided, re-authored without the chat pane.
//
// Chat-flow slice 2: the entire editing session (document/selection joins,
// writes, rich-text, custom-component form, theme, layers) lives in the
// shared `useWebEditingSession` hook so the chats route mounts the exact
// same machinery beside a conversation. This file is now layout only: the
// route's own shell controller + the hook + the dummy's arrangement.
//
// The gallery rides along as presentation-only chrome (W0.5 founder amendment,
// 2026-08-17): the Gallery tab and gallery surface render real cards only —
// never fixture data. The leg-derived feed (ratified 2026-08-18) supplies them
// through the `artifacts` prop; with no feed the gallery keeps its honest
// empty state. Closing the last tab falls back to the gallery (founder
// Decision 1). This lifted gallery is the intended replacement for the
// existing /projects/{id}/gallery screen (founder Decision 2 — the route swap
// is a separate follow-up now that real data lands).
//
// Split view is deferred to the chat-flow integration: the ratified route
// shape also mounts this surface beside a chat on
// /projects/{id}/chats/{chatId} via `?surface=web|ad` (+ `?edit=`,
// `?selection=`) — ruling R2, 2026-08-17, superseding the earlier
// `?artifact=` param, which was never built and must not be introduced —
// where the inspector dock replaces the conversation column (composer stays
// docked). Until that lands, this surface
// renders the artifact rail (tabs + header + stage) full-width only, matching
// the dummy's maximized presentation (no inspector at full width). The
// "Close artifact panel" tab action is a no-op here for the same reason —
// there is no chat pane to return to at the canonical artifact URL; its
// wiring is a split-view decision.
//
// The wrapper carries styles.shellPanelOpen: the lifted stylesheet's
// `.shellPanelOpen .artifactWorkspace` rule is what makes the stage visible
// (the stage is born opacity-0 for the dummy's slide-in entry transition).
// Since C-1 restored the chat-chrome CSS, `.shellPanelOpen` also carries the
// split-view grid-template-columns (chat column + artifact column), and the
// CSS module is emitted unlayered so it beats Tailwind's layered
// `grid-cols-1`. The inline gridTemplateColumns pins this full-width surface
// back to a single column — the class stays purely an opacity lever here.

export function EditorSurface({
  artifacts,
  documentIds,
  initial,
}: {
  /** Slice 3 (gallery leg-derived feed): the project's real gallery cards,
   * mapped server-side from the design-artifact list read. Absent → the
   * gallery keeps its honest empty state. */
  artifacts?: ProjectArtifact[];
  /** W2.1: artifact id → design-document id, from the page's W1.3 read-seam
   * fetch. The active artifact's entry mounts the real web render; artifacts
   * without one keep the dummy's empty canvas. */
  documentIds?: Record<string, string>;
  initial?: EditorShellInitialState;
}) {
  const controller = useEditorShellController(initial);
  // AD2.7: one session per LANE, each gated on the active tab's kind. React
  // forbids a conditional hook, so both are always called and the kind rides
  // in as `enabled` — the disabled one touches no transport at all (audit
  // finding F3: before this, every ad load ran the web theme/document fetches
  // and swallowed their 409s).
  const session = useWebEditingSession({
    activeArtifactId: controller.activeArtifactId,
    documentIds,
    enabled: controller.artifactKind === "web",
  });
  // The recorded follow-up, now built (2026-09-03): the lock on this route comes
  // from the DOCUMENT-scoped agent-busy read (`useDocumentAgentRun` polling
  // `GET /documents/{id}/agent-run`), which answers from the same predicate the
  // manual-write routes' 409 uses — ruling R1 of the standalone-artifact-lock
  // plan, so no thread-shaped source is invented for a route with no turn stream.
  // The ad lane's document-scoped lock (R1), extended to sites (Wave 2 ruling): one read, keyed on
  // whichever locked kind is open.
  const lockedKind = controller.artifactKind === "ad" || controller.artifactKind === "site";
  const lockDocumentId =
    lockedKind && controller.activeArtifactId
      ? (documentIds?.[controller.activeArtifactId] ?? null)
      : null;
  const agentRun = useDocumentAgentRun({ documentId: lockDocumentId, enabled: lockedKind });
  const sceneLocked = controller.artifactKind === "ad" && agentRun.active;
  const siteLocked = controller.artifactKind === "site" && agentRun.active;
  const sceneSession = useSceneEditingSession({
    activeArtifactId: controller.activeArtifactId,
    // Task 4 (scene live-streaming rung A), closed here: the lock is the
    // document-scoped agent-busy read above, not a turn stream this route lacks.
    agentRunLocked: sceneLocked,
    documentIds,
    enabled: controller.artifactKind === "ad",
  });
  const siteSession = useSiteEditingSession({
    activeArtifactId: controller.activeArtifactId,
    documentIds,
    editing: controller.editing,
    enabled: controller.artifactKind === "site",
    locked: siteLocked,
    warm: (artifacts ?? []).some((artifact) => artifact.documentKind === "site"),
  });
  // This route has no turn stream: an agent write to an open site is seen only by the poll above,
  // whose `reloadNonce` moves when the document's version does. The persistent site stage takes no
  // reload token, so a moved nonce reloads the site session. The nonce starts at 0 for each
  // document (and resets on a switch), so 0 never reloads; web and ad tabs never reload here.
  const agentReloadNonce = agentRun.reloadNonce;
  const siteOpen = controller.artifactKind === "site";
  const reloadSiteSession = siteSession.reload;
  const seenAgentReloadNonce = useRef(agentReloadNonce);
  useEffect(() => {
    if (agentReloadNonce === seenAgentReloadNonce.current) return;
    seenAgentReloadNonce.current = agentReloadNonce;
    if (siteOpen && agentReloadNonce > 0) reloadSiteSession();
  }, [agentReloadNonce, reloadSiteSession, siteOpen]);
  // Exactly one lane can be enabled, so this is the active document either way
  // — the canvas branch inside the stage picks the surface by kind.
  const activeDocumentId =
    session.activeDocumentId ?? sceneSession.activeDocumentId ?? siteSession.activeDocumentId;

  // The header's rename is a document write (the design API stores it and
  // advances the version), so the tab takes the title the backend stored and
  // both lanes reload through the SAME seam an inspector write uses. The page
  // also fetches this route's gallery feed server-side, so `router.refresh()`
  // is what re-reads it — without it the gallery card would keep the old name.
  const router = useRouter();
  const setArtifactTitleFor = controller.setArtifactTitleFor;
  const reloadWebCanvas = session.onWriteReload;
  const reloadSceneCanvas = sceneSession.onWriteReload;
  const reloadSiteCanvas = siteSession.reload;
  const onArtifactRenamed = useCallback(
    (artifactId: string, persisted: string) => {
      setArtifactTitleFor(artifactId, persisted);
      reloadWebCanvas();
      reloadSceneCanvas();
      reloadSiteCanvas();
      router.refresh();
    },
    [reloadSceneCanvas, reloadSiteCanvas, reloadWebCanvas, router, setArtifactTitleFor],
  );
  const renameArtifact = useArtifactRename({
    documentIds,
    onRenamed: onArtifactRenamed,
  });

  // W2.3 (completing the W2 exit gate): while EDITING a real document, the
  // inspector docks beside the canvas — the dummy's own editing arrangement
  // (ruling R6: the inspector replaces the conversation column; at this
  // chat-less route that column is simply the dock) using the dummy's split
  // grid template verbatim. Not editing → full-width stage, exactly as W0.4
  // shipped. Remounted per selected node so the hydrated values re-apply (the
  // dummy's own schema-swap behavior).
  //
  // AD2.7 (audit finding F2): this used to demand `artifactKind === "web"`,
  // so the ad inspector had no call site on this route at all and the ad
  // editor was unreachable here. It is now kind-aware — the SAME dock markup,
  // the SAME grid columns, one inspector per kind.
  const webInspectorVisible =
    controller.editing &&
    controller.artifactKind === "web" &&
    session.activeDocumentId !== null;
  const adInspectorVisible =
    controller.editing &&
    controller.artifactKind === "ad" &&
    sceneSession.activeDocumentId !== null;
  const siteInspectorVisible =
    controller.editing &&
    controller.artifactKind === "site" &&
    siteSession.activeDocumentId !== null;
  const inspectorVisible = webInspectorVisible || adInspectorVisible || siteInspectorVisible;
  const inspectorSelection =
    session.webSelection.selection?.schema.selection ??
    sceneSession.selection?.selection ??
    controller.inspectorSelection;

  return (
    <main
      className={`${styles.shellPanelOpen} grid h-full min-h-0 w-full grid-cols-1`}
      style={{
        gridTemplateColumns: inspectorVisible
          ? "minmax(400px, 480px) minmax(0, 1fr)" // the dummy's .shellPanelOpen split template
          : "minmax(0, 1fr)",
      }}
      data-artifact-id={controller.activeArtifactId ?? undefined}
      data-artifact-kind={controller.artifactKind ?? "none"}
      data-editing={controller.editing}
      data-project-id={controller.projectId}
      data-selected-node={
        session.webSelection.selection?.node.id ??
        sceneSession.primaryNodeId ??
        undefined
      }
      data-selected-schema={
        session.webSelection.selection
          ? `${session.webSelection.selection.schema.selection}${session.webSelection.selection.schema.layoutOnly ? ":layout-only" : ""}`
          : adInspectorVisible && sceneSession.selection
            ? `${sceneSession.selection.selection}${sceneSession.selection.suppressAutoLayoutSection ? ":no-auto-layout" : ""}`
            : undefined
      }
      data-surface={controller.surface}
    >
      {webInspectorVisible ? (
        <div className={styles.chatBody}>
          <div className={styles.inspectorDock}>
            <WebInspector
              // Keyed on the SELECTED NODE only — never the document version.
              // A per-write version key remounted the whole inspector on
              // every edit (the founder-observed defect); the controller's
              // own state already reflects the user's edit, so re-hydration
              // belongs to selection changes alone. (Known, accepted drift:
              // an engine-snapped value — padding 7→6 — displays as typed
              // until the node is reselected.)
              // The canvas key carries the theme's page surface, so the one time the
                // theme lands after mount the canvas inspector re-seeds from it
                // (the web lane hydrates at mount, not live).
                key={session.webSelection.selection?.node.id ?? `canvas:${session.canvasHydrated?.backgroundColor ?? ""}`}
              customComponentForm={session.customComponentForm}
              error={session.inspectorError}
              note={session.writes.note}
              addressing={session.addressing}
              // R-A6 (slice 3): the human's own text edits inside the selected
              // cloned band, each with its Clear (the session decides whether
              // the selection owns a list at all).
              cloneTextEdits={session.cloneTextEdits}
              hydrated={session.webSelection.selection?.hydrated ?? session.canvasHydrated}
              layers={session.layerRows}
              // W5.1 (§5): the mapper's fallback flag — embeds (item 32) and
              // the interactive components (item 33) land on the container
              // view and get Layout(-padding) only.
              layoutOnly={session.webSelection.selection?.schema.layoutOnly}
              onReplaceImage={session.onReplaceImage}
              onSelectLayer={session.onSelectLayer}
              onSelectionChange={controller.selectInspectorElement}
              // F5 task 19 (FLAGGED): the page/route controls, present only while
              // no node is selected (the session decides).
              pageSection={session.pageSection}
              richTextRange={session.richTextRange}
              selection={inspectorSelection}
              themeColors={session.themeColors}
            />
          </div>
        </div>
      ) : null}
      {adInspectorVisible ? (
        <div className={styles.chatBody}>
          {/* AD2.7 (F2): the SAME dock the web branch above uses — same
              wrapper, same class, same grid column. Only the panel differs. */}
          <div className={styles.inspectorDock}>
            {/* AD4.R-10 / GATE G-H: the in-flight gate now holds on this route
                too. Its source is the document-scoped agent-busy read polled
                above (`useDocumentAgentRun`), not the chat controller's
                `threadBusy` — ruling R1 of the standalone-artifact-lock plan. */}
            <ImageInspector
              // Keyed on the SELECTED NODE only, exactly as the web branch is.
              // Values need no remount to resynchronize — every bound field
              // derives from live hydrated state (AD4.R); remounting resets UI
              // facts (open sections, drafts), which is right exactly when the
              // selection changes.
              key={sceneSession.primaryNodeId ?? "canvas"}
              addressing={sceneSession.addressing}
              arrange={sceneSession.arrange}
              assetLibrary={sceneSession.assetLibrary}
              error={sceneSession.inspectorError}
              fontOptions={sceneSession.fontOptions}
              hydrated={sceneSession.hydrated}
              imageAi={sceneSession.imageAi}
              inspectorDisabled={sceneLocked}
              layers={sceneSession.layerRows}
              note={sceneSession.note}
              onReplaceImage={sceneSession.onReplaceImage}
              onSelectLayer={sceneSession.onSelectLayer}
              onSelectionChange={controller.selectInspectorElement}
              onToggleLayer={sceneSession.onToggleLayer}
              pageless={sceneSession.pageless}
              palette={sceneSession.palette}
              selectedIds={sceneSession.selectedIds}
              selection={inspectorSelection}
              suppressAutoLayoutSection={
                sceneSession.selection?.suppressAutoLayoutSection
              }
            />
          </div>
        </div>
      ) : null}
      {siteInspectorVisible ? (
        <div className={styles.chatBody}>
          <div className={styles.inspectorDock}>
            <SiteInspector
              binding={siteSession.inspector}
              key={siteSession.inspector.selectionKey}
              renderImageField={(field, path, value) => {
                const binding = siteSession.imageField(path, value);
                return binding ? (
                  <SiteImageField binding={binding} disabled={siteLocked} key={path} label={field.label} />
                ) : null;
              }}
            />
          </div>
        </div>
      ) : null}
      <ArtifactStage
        annotations={session.canvasAnnotations}
        activeArtifactId={controller.activeArtifactId}
        activeDocumentId={activeDocumentId}
        // F5 task 18: the header's page switcher and the canvas read ONE
        // value — the web editing session's active page.
        activePageId={session.activePageId}
        onPageChange={session.setActivePageId}
        pages={session.pages}
        artifacts={artifacts ?? []}
        canvasControlsRef={session.canvasControls}
        canvasReloadToken={
          session.reloadNonce + sceneSession.reloadNonce + siteSession.reloadNonce + agentRun.reloadNonce
        }
        exportPreview={sceneSession.exportPreview}
        exportStatus={sceneSession.exportStatus}
        onRequestExportPreview={sceneSession.requestExportPreview}
        onSceneChange={sceneSession.onSceneChange}
        // Clipboard Task 8, the artifact route's half: the same drop binding
        // the chat surface passes, so a picture dragged onto the canvas lands
        // the same way on both surfaces.
        onSceneDropImageFiles={sceneSession.onSceneDropImageFiles}
        onSceneFitZoom={sceneSession.onFitZoom}
        onSceneGestureZoom={sceneSession.onGestureZoom}
        onSceneHistoryChange={sceneSession.onHistoryChange}
        // AD4.C / Ruling C-3: committed canvas gestures ride the session's own
        // `applyOps`, the same write path this route's inspector uses.
        onSceneAppliedOperations={sceneSession.writes.persistAppliedOps}
        onSceneOperations={sceneSession.writes.applyOps}
        onSceneSelect={sceneSession.onSelectCanvas}
        onSceneZoomChange={sceneSession.onZoomChange}
        sceneCanvasControlsRef={sceneSession.canvasControls}
        // AD4.C / GATE G-H: the canvas half of the same lock `inspectorDisabled`
        // implements above, off the same fact — the document-scoped agent-busy
        // read polled at the top of this component (ruling R1), not a turn
        // stream this route does not have.
        sceneGestureDisabled={sceneLocked}
        onSceneLockedEdit={sceneSession.onLockedEdit}
        // Rung C / §1.6: one document, one brand palette — the caret
        // session's colour control offers exactly what the inspector's do.
        scenePalette={sceneSession.palette}
        sceneSelectedNodeId={sceneSession.primaryNodeId}
        sceneZoomLabel={sceneSession.zoom}
        sceneZoomOverride={sceneSession.zoomOverride}
        artifactKind={controller.artifactKind}
        artifactMaximized={controller.artifactMaximized}
        artifactTitle={controller.artifactTitle}
        editing={controller.editing}
        onActivateArtifact={controller.activateArtifact}
        onCanvasSelect={session.webSelection.onSelect}
        onCloseArtifact={controller.closeArtifact}
        onOpenGallery={controller.openGallery}
        onCloneTextCommit={session.onCloneTextCommit}
        onRichTextCommit={session.onRichTextCommit}
        onRichTextSessionChange={session.onRichTextSessionChange}
        richTextBusy={session.writes.busy}
        // W4.8a editing gate: the SAME condition that mounts the WEB editing
        // dock (never the ad one — an ad has no in-canvas text session).
        // Outside editing the canvas cancels any session the bridge starts, so
        // a double-click on the read-only render changes nothing.
        richTextEnabled={webInspectorVisible}
        richTextTheme={session.theme}
        onOpenGalleryArtifact={(artifact) =>
          controller.openArtifact({
            id: artifact.id,
            kind: chatShellKindForCard({
              documentKind: artifact.source?.documentKind,
              type: artifact.source?.type,
            }),
            title: artifact.title,
          })
        }
        onRenameArtifact={(title) => {
          if (controller.activeArtifactId) {
            renameArtifact(controller.activeArtifactId, title);
          }
        }}
        // The tab strip's rename of a NON-active tab is unchanged local state
        // (it carries no document handle of its own here).
        onRenameArtifactFor={controller.setArtifactTitleFor}
        onToggleMaximized={controller.toggleArtifactMaximized}
        onTogglePanel={() => undefined}
        onToggleEditing={() => controller.setEditing(!controller.editing)}
        // Task 4: the Edit affordance itself. Entering edit mode is refused
        // while the lock holds — an editor whose every control is inert is not
        // an editor — but LEAVING it never is, or a lock engaging mid-edit would
        // trap the user in a dock they cannot close.
        editDisabled={(sceneLocked || siteLocked) && !controller.editing}
        editDisabledReason={AGENT_RUN_LOCK_NOTE}
        openArtifacts={controller.openArtifacts}
        // Replace-image Task 6: the asset-library picker floats over the stage,
        // rendered by the surface (the stage is pass-through chrome). The Task-4
        // binding derives `isOpen` from the armed document, so switching
        // artifacts closes it by construction.
        overlay={
          sceneSession.assetLibrary?.isOpen ? (
            <AssetLibraryPanel
              library={sceneSession.assetLibrary}
              onUploadFile={sceneSession.onReplaceImage}
            />
          ) : siteSession.images.library?.isOpen ? (
            <AssetLibraryPanel
              library={siteSession.images.library}
              onUploadFile={siteSession.images.uploadToLibraryTarget}
            />
          ) : null
        }
        // AD3.3: one pair of history-row disables in the header, so the artifact
        // on screen picks the lane whose stacks they describe (the same kind
        // switch that gates the two sessions above).
        redoDisabled={
          controller.artifactKind === "ad"
            ? sceneSession.redoDisabled
            : controller.artifactKind === "site"
              ? siteSession.history.redoDisabled
              : session.redoDisabled
        }
        selectedCanvasNodeId={session.webSelection.selection?.node.id ?? null}
        site={siteSession.stage}
        surface={controller.surface}
        undoDisabled={
          controller.artifactKind === "ad"
            ? sceneSession.undoDisabled
            : controller.artifactKind === "site"
              ? siteSession.history.undoDisabled
              : session.undoDisabled
        }
      />
    </main>
  );
}
