"use client";

import { useCallback } from "react";
import { useProjectChatController } from "../hooks/use-project-chat-controller";
import {
  useProjectWorkspaceController,
  workspaceRemountKey,
  type ProjectWorkspaceInitialState,
} from "../hooks/use-project-workspace-controller";
import { useProjectWorkspaceLoader } from "../hooks/use-project-workspace-loader";
import type { ProjectWorkspace } from "../model/project-workspace";
import styles from "./project-flow.module.css";
import { ProjectWorkspaceView } from "./project-workspace-view";

export function ProjectWorkspaceShell({
  initial,
  projectId,
  workspace,
}: {
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
      initial={initial}
      key={workspaceRemountKey(loaded.workspace.id, initial)}
      workspace={loaded.workspace}
    />
  );
}

function LoadedProjectWorkspace({
  initial,
  workspace,
}: {
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
  const copyLink = useCallback(() => {
    void navigator.clipboard?.writeText(window.location.href);
  }, []);
  return (
    <ProjectWorkspaceView
      chat={chat}
      controller={controller}
      onCopyLink={copyLink}
      workspace={workspace}
    />
  );
}
