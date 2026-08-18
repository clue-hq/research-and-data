"use client";

import { ChatSurface } from "@/features/chat-shell/components/chat-surface";
import { useProjectChatController } from "../hooks/use-project-chat-controller";
import {
  useProjectWorkspaceController,
  workspaceRemountKey,
  type ProjectWorkspaceInitialState,
} from "../hooks/use-project-workspace-controller";
import { useProjectWorkspaceLoader } from "../hooks/use-project-workspace-loader";
import type {
  ProjectArtifact,
  ProjectWorkspace,
} from "../model/project-workspace";
import styles from "./project-flow.module.css";

export function ProjectWorkspaceShell({
  artifacts,
  documentIds,
  initial,
  projectId,
  workspace,
}: {
  /** Chat-flow slice 1: the page's server-fetched gallery feed — real cards
   * for the artifact rail. Absent (the legacy /projects/{id} absorber) → the
   * gallery keeps its honest empty state. */
  artifacts?: ProjectArtifact[];
  /** Artifact id → design-document id over the whole feed; the canvas mount
   * (next slice) resolves the active tab's document through it. */
  documentIds?: Record<string, string>;
  initial: ProjectWorkspaceInitialState;
  projectId: string;
  workspace: ProjectWorkspace | null;
}) {
  const loaded = useProjectWorkspaceLoader({
    initialWorkspace: workspace,
    projectId,
  });
  if (loaded.loading) {
    return (
      <main className={styles.projectWorkspace}>
        <p className={styles.projectLoadState} role="status">Loading project…</p>
      </main>
    );
  }
  if (loaded.error || !loaded.workspace) {
    return (
      <main className={styles.projectWorkspace}>
        <p className={styles.projectLoadState} role="alert">
          {loaded.error ?? "Project unavailable."}
        </p>
      </main>
    );
  }
  return (
    <LoadedProjectWorkspace
      artifacts={artifacts}
      documentIds={documentIds}
      initial={initial}
      key={workspaceRemountKey(loaded.workspace.id, initial)}
      workspace={loaded.workspace}
    />
  );
}

function LoadedProjectWorkspace({
  artifacts,
  documentIds,
  initial,
  workspace,
}: {
  artifacts?: ProjectArtifact[];
  documentIds?: Record<string, string>;
  initial: ProjectWorkspaceInitialState;
  workspace: ProjectWorkspace;
}) {
  const controller = useProjectWorkspaceController(workspace, initial);
  // Two controllers, two responsibilities: the conversation is durable state
  // over real repositories, the artifact side is local view state over the
  // project shell. They share nothing but the screen.
  const chat = useProjectChatController({
    projectId: workspace.id,
    initialThreadId: initial.threadId,
  });
  // Phase C (C-3): the designed chat shell is the workspace's view layer —
  // ChatSurface renders the chat pane + artifact rail around production chat.
  return (
    <ChatSurface
      artifacts={artifacts}
      chat={chat}
      controller={controller}
      documentIds={documentIds}
      paneState={{
        edit: initial.edit,
        selection: initial.selection,
        surface: initial.surface,
      }}
      projectId={workspace.id}
      workspace={workspace}
    />
  );
}
