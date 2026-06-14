"use client";

import { useMemo } from "react";
import type { Diagnostic, NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";
import { canvasKitFlagEnabled } from "@/engine/wasmEngine";
import { createWorkspaceModel } from "@/engine/workspaceLayout";
import type { WorkspaceFitTarget, WorkspaceTool, WorkspaceViewport } from "@/engine/workspaceViewport";
import { CanvasSurface } from "./CanvasSurface";
import { CanvasKitCanvas } from "./CanvasKitCanvas";

export type WorkspaceViewportUpdater = (
  next: WorkspaceViewport | ((current: WorkspaceViewport) => WorkspaceViewport)
) => void;

/**
 * Wave 3 C5: the flag-gated renderer switch. With NEXT_PUBLIC_LUMEN_CANVASKIT
 * on, the editor canvas is CanvasKit (Skia parity + own interaction layer);
 * otherwise it stays on the retained-mode Konva canvas. Both consume the same
 * props; CanvasKit additionally needs the engine for authoritative
 * hit-testing.
 */
export interface EditorCanvasProps {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId | null) => void;
  onSelectPage?: (pageId: PageId) => void;
  onOperation: (operation: Operation) => void;
  engine: OptimisticEnginePort | null;
  diagnostics?: Diagnostic[];
  workspaceViewport: WorkspaceViewport;
  onWorkspaceViewportChange: WorkspaceViewportUpdater;
  workspaceTool: WorkspaceTool;
  onWorkspaceToolChange: (tool: WorkspaceTool) => void;
  workspaceFitTarget: WorkspaceFitTarget;
  onWorkspaceFitTargetChange: (target: WorkspaceFitTarget) => void;
  /** CanvasKit-only: re-sync the host scene after the C4 measurement pass. */
  onSceneRefresh?: () => void;
}

export function EditorCanvas(props: EditorCanvasProps) {
  const workspaceModel = useMemo(
    () => createWorkspaceModel(props.scene, props.activePageId, props.diagnostics ?? []),
    [props.activePageId, props.diagnostics, props.scene]
  );
  if (canvasKitFlagEnabled()) {
    return <CanvasKitCanvas {...props} workspaceModel={workspaceModel} />;
  }
  return (
    <CanvasSurface
      scene={props.scene}
      activePageId={props.activePageId}
      selectedNodeId={props.selectedNodeId}
      onSelectNode={props.onSelectNode}
      onSelectPage={props.onSelectPage}
      onOperation={props.onOperation}
      workspaceModel={workspaceModel}
      workspaceViewport={props.workspaceViewport}
      onWorkspaceViewportChange={props.onWorkspaceViewportChange}
      workspaceTool={props.workspaceTool}
      onWorkspaceToolChange={props.onWorkspaceToolChange}
      workspaceFitTarget={props.workspaceFitTarget}
      onWorkspaceFitTargetChange={props.onWorkspaceFitTargetChange}
    />
  );
}
