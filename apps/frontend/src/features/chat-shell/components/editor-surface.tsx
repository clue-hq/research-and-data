"use client";

import {
  useEditorShellController,
  type EditorShellInitialState,
} from "../hooks/use-editor-shell-controller";
import { ArtifactStage } from "./artifact-stage";
import styles from "./chat-shell.module.css";

// Full-width editor surface at the canonical artifact route
// (/projects/{projectId}/artifacts/{artifactId}); the composition the branch's
// chat-shell-view.tsx provided, re-authored without the chat pane.
//
// The gallery rides along as presentation-only chrome (W0.5 founder amendment,
// 2026-08-17): the Gallery tab and gallery surface render with an EMPTY
// artifact list — never fixture data — until the W1.3 artifact read seam feeds
// them; closing the last tab falls back to the gallery (founder Decision 1).
// This lifted gallery is the intended replacement for the existing
// /projects/{id}/gallery screen; the route swap is deferred until real data
// lands (founder Decision 2).
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
  documentIds,
  initial,
}: {
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

  return (
    <main
      className={`${styles.shellPanelOpen} grid h-full min-h-0 w-full grid-cols-1`}
      style={{ gridTemplateColumns: "minmax(0, 1fr)" }}
      data-artifact-id={controller.activeArtifactId ?? undefined}
      data-artifact-kind={controller.artifactKind ?? "none"}
      data-editing={controller.editing}
      data-project-id={controller.projectId}
      data-surface={controller.surface}
    >
      <ArtifactStage
        activeArtifactId={controller.activeArtifactId}
        activeDocumentId={activeDocumentId}
        artifacts={[]}
        artifactKind={controller.artifactKind}
        artifactMaximized={controller.artifactMaximized}
        artifactTitle={controller.artifactTitle}
        editing={controller.editing}
        onActivateArtifact={controller.activateArtifact}
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
        surface={controller.surface}
      />
    </main>
  );
}
