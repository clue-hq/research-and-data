import { useState, type PointerEvent as ReactPointerEvent } from "react";
import type { EditorPanelMode } from "@/engine/editorModes";
import {
  defaultWorkspaceViewport,
  type WorkspaceFitTarget,
  type WorkspaceTool
} from "@/engine/workspaceViewport";

/**
 * Workspace chrome state: which right panel is open, the center-workspace
 * mode, the canvas viewport/tool, and the agent-sidebar width (with its
 * pointer-drag resizer). Pure presentation state — no workflow policy.
 */
export function useWorkspaceChrome() {
  const [editorPanelMode, setEditorPanelMode] = useState<EditorPanelMode>("inspector");
  const [agentSidebarWidth, setAgentSidebarWidth] = useState(420);
  const [workspaceMode, setWorkspaceMode] = useState<"canvas" | "export" | "compare">("canvas");
  const [workspaceViewport, setWorkspaceViewport] = useState(defaultWorkspaceViewport);
  const [workspaceTool, setWorkspaceTool] = useState<WorkspaceTool>("select");
  const [workspaceFitTarget, setWorkspaceFitTarget] = useState<WorkspaceFitTarget>("all");

  const startAgentSidebarResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = agentSidebarWidth;
    const resize = (moveEvent: PointerEvent) => {
      if (!Number.isFinite(moveEvent.clientX)) {
        return;
      }
      const nextWidth = clampNumber(startWidth + startX - moveEvent.clientX, 320, 720);
      setAgentSidebarWidth(nextWidth);
    };
    const stopResize = () => {
      window.removeEventListener("pointermove", resize);
    };
    window.addEventListener("pointermove", resize);
    window.addEventListener("pointerup", stopResize, { once: true });
  };

  return {
    editorPanelMode,
    setEditorPanelMode,
    agentSidebarWidth,
    workspaceMode,
    setWorkspaceMode,
    workspaceViewport,
    setWorkspaceViewport,
    workspaceTool,
    setWorkspaceTool,
    workspaceFitTarget,
    setWorkspaceFitTarget,
    startAgentSidebarResize
  };
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
