"use client";

import type { NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";
import { canvasKitFlagEnabled } from "@/engine/wasmEngine";
import { CanvasSurface } from "./CanvasSurface";
import { CanvasKitCanvas } from "./CanvasKitCanvas";

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
  onOperation: (operation: Operation) => void;
  engine: OptimisticEnginePort | null;
}

export function EditorCanvas(props: EditorCanvasProps) {
  if (canvasKitFlagEnabled()) {
    return <CanvasKitCanvas {...props} />;
  }
  return (
    <CanvasSurface
      scene={props.scene}
      activePageId={props.activePageId}
      selectedNodeId={props.selectedNodeId}
      onSelectNode={props.onSelectNode}
      onOperation={props.onOperation}
    />
  );
}
