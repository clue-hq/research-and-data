"use client";

import {
  useEditorShellController,
  type EditorShellInitialState,
} from "../hooks/use-editor-shell-controller";
import { useSceneEditingSession } from "@/features/design-editor/hooks/use-scene-editing-session";
import { useWebEditingSession } from "@/features/design-editor/hooks/use-web-editing-session";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { ArtifactStage } from "./artifact-stage";
import { ImageInspector } from "./image-inspector";
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
  const sceneSession = useSceneEditingSession({
    activeArtifactId: controller.activeArtifactId,
    documentIds,
    enabled: controller.artifactKind === "ad",
  });
  // Exactly one lane can be enabled, so this is the active document either way
  // — the canvas branch inside the stage picks the surface by kind.
  const activeDocumentId =
    session.activeDocumentId ?? sceneSession.activeDocumentId;

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
  const inspectorVisible = webInspectorVisible || adInspectorVisible;
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
              key={session.webSelection.selection?.node.id ?? "canvas"}
              customComponentForm={session.customComponentForm}
              error={session.inspectorError}
              note={session.writes.note}
              addressing={session.addressing}
              hydrated={session.webSelection.selection?.hydrated}
              layers={session.layerRows}
              // W5.1 (§5): the mapper's fallback flag — embeds (item 32) and
              // the interactive components (item 33) land on the container
              // view and get Layout(-padding) only.
              layoutOnly={session.webSelection.selection?.schema.layoutOnly}
              onReplaceImage={session.onReplaceImage}
              onSelectLayer={session.onSelectLayer}
              onSelectionChange={controller.selectInspectorElement}
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
            {/* AD4.R-10 / GATE G-H: `inspectorDisabled` is deliberately NOT
                passed here, so this route behaves exactly as it did. The ruled
                in-flight gate reads the chat controller's `threadBusy`, and the
                artifact route has no live turn stream to read — it is the
                document open on its own, with no thread beside it. Its net
                against an agent write landing under the user's hands stays the
                D10 CAS reconciliation (the document version moves, the write is
                refused, the panel reloads and says so — proven at T8). RECORDED
                FOLLOW-UP: a DOCUMENT-scoped agent-busy signal (plausibly off the
                run_event SSE, which this route already has a reason to watch)
                would close the gap; inventing a second, thread-shaped source
                here would not. */}
            <ImageInspector
              // Keyed on the SELECTED NODE only, exactly as the web branch is.
              // Values need no remount to resynchronize — every bound field
              // derives from live hydrated state (AD4.R); remounting resets UI
              // facts (open sections, drafts), which is right exactly when the
              // selection changes.
              key={sceneSession.primaryNodeId ?? "canvas"}
              addressing={sceneSession.addressing}
              error={sceneSession.inspectorError}
              fontOptions={sceneSession.fontOptions}
              hydrated={sceneSession.hydrated}
              imageAi={sceneSession.imageAi}
              layers={sceneSession.layerRows}
              note={sceneSession.note}
              onReplaceImage={sceneSession.onReplaceImage}
              onSelectLayer={sceneSession.onSelectLayer}
              onSelectionChange={controller.selectInspectorElement}
              onToggleLayer={sceneSession.onToggleLayer}
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
      <ArtifactStage
        activeArtifactId={controller.activeArtifactId}
        activeDocumentId={activeDocumentId}
        artifacts={artifacts ?? []}
        canvasControlsRef={session.canvasControls}
        canvasReloadToken={session.reloadNonce + sceneSession.reloadNonce}
        onSceneChange={sceneSession.onSceneChange}
        onSceneFitZoom={sceneSession.onFitZoom}
        onSceneGestureZoom={sceneSession.onGestureZoom}
        onSceneHistoryChange={sceneSession.onHistoryChange}
        onSceneSelect={sceneSession.onSelectCanvas}
        onSceneZoomChange={sceneSession.onZoomChange}
        sceneCanvasControlsRef={sceneSession.canvasControls}
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
            kind: artifact.source.type === "website" ? "web" : "ad",
            title: artifact.title,
          })
        }
        onRenameArtifact={(title) => {
          if (controller.activeArtifactId) {
            controller.setArtifactTitleFor(controller.activeArtifactId, title);
          }
        }}
        onRenameArtifactFor={controller.setArtifactTitleFor}
        onToggleMaximized={controller.toggleArtifactMaximized}
        onTogglePanel={() => undefined}
        onToggleEditing={() => controller.setEditing(!controller.editing)}
        openArtifacts={controller.openArtifacts}
        // AD3.3: one pair of history-row disables in the header, so the artifact
        // on screen picks the lane whose stacks they describe (the same kind
        // switch that gates the two sessions above).
        redoDisabled={
          controller.artifactKind === "ad"
            ? sceneSession.redoDisabled
            : session.redoDisabled
        }
        selectedCanvasNodeId={session.webSelection.selection?.node.id ?? null}
        surface={controller.surface}
        undoDisabled={
          controller.artifactKind === "ad"
            ? sceneSession.undoDisabled
            : session.undoDisabled
        }
      />
    </main>
  );
}
