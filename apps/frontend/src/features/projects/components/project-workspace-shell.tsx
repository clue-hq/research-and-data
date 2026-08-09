"use client";

import { useCallback } from "react";
import { useProjectChatController } from "../hooks/use-project-chat-controller";
import {
  useProjectWorkspaceController,
  type ProjectWorkspaceInitialState,
} from "../hooks/use-project-workspace-controller";
import type { ProjectWorkspace } from "../model/project-workspace";
import { ProjectWorkspaceView } from "./project-workspace-view";

export function ProjectWorkspaceShell({
  initial,
  workspace,
}: {
  initial: ProjectWorkspaceInitialState;
  workspace: ProjectWorkspace;
}) {
  const controller = useProjectWorkspaceController({ initial, workspace });
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
