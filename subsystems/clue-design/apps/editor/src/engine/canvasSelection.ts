import type { NodeId, Scene } from "./contracts";
import { getNode, isNodeDirectGeometryEditable, isNodeLayoutManaged } from "./sceneQueries";

export function isCanvasDirectGeometryEditable(scene: Scene, nodeId: NodeId | null): boolean {
  return isNodeDirectGeometryEditable(scene, nodeId);
}

export function canvasDirectEditNotice(scene: Scene, nodeId: NodeId | null): string | null {
  const node = getNode(scene, nodeId);
  if (!node || isCanvasDirectGeometryEditable(scene, nodeId)) {
    return null;
  }

  if (node.locked) {
    return "Selection is locked. Unlock it in the inspector before dragging or resizing.";
  }

  if (isNodeLayoutManaged(scene, nodeId)) {
    return "Selection is managed by an auto-layout parent. Use layout sizing or layer reorder controls instead of direct canvas geometry.";
  }

  return "Selection cannot be directly transformed on the canvas. Use inspector controls for supported structured edits.";
}
