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
// Split view is deferred to the chat-flow integration: the ratified route
// shape also mounts this surface beside a chat via `?artifact=` on
// /projects/{id}/chats/{chatId}, where the inspector dock replaces the
// conversation column (composer stays docked). Until that lands, this surface
// renders the artifact rail (tabs + header + stage) full-width only, matching
// the dummy's maximized presentation (no inspector at full width). The
// "Close artifact panel" tab action is a no-op here for the same reason —
// there is no chat pane to return to at the canonical artifact URL; its
// wiring is a split-view decision.
//
// The wrapper carries styles.shellPanelOpen: the lifted stylesheet's
// `.shellPanelOpen .artifactWorkspace` rule is what makes the stage visible
// (the stage is born opacity-0 for the dummy's slide-in entry transition).

export function EditorSurface({
  initial,
}: {
  initial?: EditorShellInitialState;
}) {
  const controller = useEditorShellController(initial);

  return (
    <main
      className={`${styles.shellPanelOpen} grid h-full min-h-0 w-full grid-cols-1`}
      data-artifact-id={controller.activeArtifactId ?? undefined}
      data-artifact-kind={controller.artifactKind ?? "none"}
      data-editing={controller.editing}
      data-project-id={controller.projectId}
    >
      <ArtifactStage
        activeArtifactId={controller.activeArtifactId}
        artifactKind={controller.artifactKind}
        artifactMaximized={controller.artifactMaximized}
        artifactTitle={controller.artifactTitle}
        editing={controller.editing}
        onActivateArtifact={controller.activateArtifact}
        onCloseArtifact={controller.closeArtifact}
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
      />
    </main>
  );
}
