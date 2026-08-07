"use client";

import { useCallback } from "react";
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
  const copyLink = useCallback(() => {
    void navigator.clipboard?.writeText(window.location.href);
  }, []);
  return <ProjectWorkspaceView controller={controller} onCopyLink={copyLink} workspace={workspace} />;
}
