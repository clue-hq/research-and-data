"use client";

import { useCallback, useRef, useState } from "react";
import {
  useEditorShellController,
  type EditorShellInitialState,
} from "../hooks/use-editor-shell-controller";
import { buildWebLayerRows } from "@/features/design-editor/adapter/layers";
import type { WebArtifactCanvasControls } from "@/features/design-editor/components/web-artifact-canvas";
import { useInspectorWrites } from "@/features/design-editor/hooks/use-inspector-writes";
import { useWebArtifactSelection } from "@/features/design-editor/hooks/use-web-artifact-selection";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { ArtifactStage } from "./artifact-stage";
import { WebInspector } from "./web-inspector";
import styles from "./chat-shell.module.css";

// Full-width editor surface at the canonical artifact route
// (/projects/{projectId}/artifacts/{artifactId}); the composition the branch's
// chat-shell-view.tsx provided, re-authored without the chat pane.
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
  const activeDocumentId = controller.activeArtifactId
    ? (documentIds?.[controller.activeArtifactId] ?? null)
    : null;
  // W2.2: the canvas bridge's nonce-validated selections joined with the
  // loaded document → {node, nodeInfo} + schema + hydrated inspector state,
  // also surfaced on data attributes below for verification.
  // W3.2: after a committed write the reload nonce bumps — the document
  // refetches (fresh currentVersion → next base_version) and the canvas
  // remounts its render (rotating the bridge nonce with the rebuilt DOM).
  const [reloadNonce, setReloadNonce] = useState(0);
  const webSelection = useWebArtifactSelection(activeDocumentId, reloadNonce);
  const canvasControls = useRef<WebArtifactCanvasControls | null>(null);
  const onWriteReload = useCallback(() => {
    setReloadNonce((nonce) => nonce + 1);
  }, []);
  const writes = useInspectorWrites({
    document: webSelection.document,
    documentId: activeDocumentId,
    onReload: onWriteReload,
    selection: webSelection.selection,
  });

  // W2.3 (completing the W2 exit gate): while EDITING a real web document,
  // the inspector docks beside the canvas — the dummy's own editing
  // arrangement (ruling R6: the inspector replaces the conversation column;
  // at this chat-less route that column is simply the dock) using the
  // dummy's split grid template verbatim. Not editing → full-width stage,
  // exactly as W0.4 shipped. Remounted per selected node so W2.2's hydrated
  // values re-apply (the dummy's own schema-swap behavior).
  const inspectorVisible =
    controller.editing &&
    controller.artifactKind === "web" &&
    activeDocumentId !== null;
  const page = webSelection.document?.webDoc?.pages?.[0];
  const layerRows =
    page?.root && page.nodes
      ? buildWebLayerRows(
          { nodes: page.nodes, page_root: page.root },
          webSelection.selection?.node.id ?? null,
        )
      : undefined;
  const inspectorSelection =
    webSelection.selection?.schema.selection ?? controller.inspectorSelection;

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
      data-selected-node={webSelection.selection?.node.id}
      data-selected-schema={
        webSelection.selection
          ? `${webSelection.selection.schema.selection}${webSelection.selection.schema.layoutOnly ? ":layout-only" : ""}`
          : undefined
      }
      data-surface={controller.surface}
    >
      {inspectorVisible ? (
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
              key={webSelection.selection?.node.id ?? "canvas"}
              error={writes.error}
              note={writes.note}
              addressing={{
                // W3.1: what this surface holds — the write adapter (W3.2)
                // resolves events against exactly these three values.
                artifactId: controller.activeArtifactId,
                documentVersion: webSelection.document?.currentVersion ?? null,
                selectionId: webSelection.selection?.node.id ?? null,
              }}
              hydrated={webSelection.selection?.hydrated}
              layers={layerRows}
              onSelectLayer={(nodeId) =>
                canvasControls.current?.selectNode(nodeId)
              }
              onSelectionChange={controller.selectInspectorElement}
              selection={inspectorSelection}
            />
          </div>
        </div>
      ) : null}
      <ArtifactStage
        activeArtifactId={controller.activeArtifactId}
        activeDocumentId={activeDocumentId}
        artifacts={artifacts ?? []}
        canvasControlsRef={canvasControls}
        canvasReloadToken={reloadNonce}
        artifactKind={controller.artifactKind}
        artifactMaximized={controller.artifactMaximized}
        artifactTitle={controller.artifactTitle}
        editing={controller.editing}
        onActivateArtifact={controller.activateArtifact}
        onCanvasSelect={webSelection.onSelect}
        onCloseArtifact={controller.closeArtifact}
        onOpenGallery={controller.openGallery}
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
        redoDisabled={(webSelection.document?.redoDepth ?? 0) === 0}
        selectedCanvasNodeId={webSelection.selection?.node.id ?? null}
        surface={controller.surface}
        undoDisabled={(webSelection.document?.undoDepth ?? 0) === 0}
      />
    </main>
  );
}
