"use client";

import { useMemo } from "react";
import type { Diagnostic, NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import type { StructuredEdit } from "@/engine/structuredEdits";
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
  /** Full multi-selection set (CanvasKit path renders secondary outlines). */
  selectedNodeIds?: NodeId[];
  onSelectNode: (nodeId: NodeId | null, additive?: boolean) => void;
  onSelectPage?: (pageId: PageId) => void;
  /** Commits land as one atomic batch (one undo frame); Phase 1d container
   * drags carry pinned-descendant box translations alongside the primary op. */
  onOperations: (operations: Operation[]) => void;
  engine: OptimisticEnginePort | null;
  diagnostics?: Diagnostic[];
  workspaceViewport: WorkspaceViewport;
  onWorkspaceViewportChange: WorkspaceViewportUpdater;
  workspaceTool: WorkspaceTool;
  onWorkspaceToolChange: (tool: WorkspaceTool) => void;
  workspaceFitTarget: WorkspaceFitTarget;
  onWorkspaceFitTargetChange: (target: WorkspaceFitTarget) => void;
  onOpenDiagnostics?: () => void;
  onOpenExport?: () => void;
  /** CanvasKit-only: re-sync the host scene after the C4 measurement pass. */
  onSceneRefresh?: () => void;
  /** Handoff-absolute (lazy seam), CanvasKit-only: applies a structured edit
   * through the canonical engine-apply-then-commit path and returns the
   * post-apply engine scene (or null if the engine rejected/was
   * unavailable), so a gesture blocked only by solver ownership can freeze
   * the layout and continue against fresh geometry in the same pointer
   * gesture. Omitted on the Konva fallback (test-only; freeze is a
   * CanvasKit-path concern). */
  onStructuredEdit?: (edit: StructuredEdit) => Scene | null;
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
      // The legacy Konva surface commits one op at a time; wrap into the
      // atomic batch contract. (Multi-op parent-drag pin translation is a
      // CanvasKit-path behavior; Konva is the retained test surface.)
      onOperation={(operation: Operation) => props.onOperations([operation])}
      workspaceModel={workspaceModel}
      workspaceViewport={props.workspaceViewport}
      onWorkspaceViewportChange={props.onWorkspaceViewportChange}
      workspaceTool={props.workspaceTool}
      onWorkspaceToolChange={props.onWorkspaceToolChange}
      workspaceFitTarget={props.workspaceFitTarget}
      onWorkspaceFitTargetChange={props.onWorkspaceFitTargetChange}
      onOpenDiagnostics={props.onOpenDiagnostics}
      onOpenExport={props.onOpenExport}
    />
  );
}
