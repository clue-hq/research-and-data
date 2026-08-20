import type { NodeId, Scene } from "./contracts";
import {
  getNode,
  isContainerNode,
  isNodeDirectGeometryEditable,
  isNodeLayoutManaged,
  nodeDisplayName
} from "./sceneQueries";

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

/** Absolute scene-unit rectangle (page-relative), pre-canvas-scale. */
export interface SelectionRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ContainerSelectionGeometry {
  /** Display label for the container chrome (the node name/kind). */
  label: string;
  /** The container's own absolute bounds. */
  container: SelectionRect;
  /** Absolute bounds of each direct child that has been laid out. */
  children: SelectionRect[];
}

/**
 * Geometry for the container-selection overlay, in absolute scene units
 * (the caller applies canvas scale + page origin). Returns null when the
 * selection is not a container-with-children, or when the container has no
 * computed bounds yet (nothing meaningful to outline). Reads `computed`,
 * which the engine keeps fresh for the whole tree (the coordinate-model
 * fix), so the box and child outlines are always mutually coherent.
 */
export function containerSelectionGeometry(
  scene: Scene,
  nodeId: NodeId | null
): ContainerSelectionGeometry | null {
  const node = getNode(scene, nodeId);
  if (!node || !isContainerNode(node) || !node.computed) {
    return null;
  }
  const children: SelectionRect[] = [];
  for (const childId of node.children) {
    const child = scene.nodes[childId];
    if (child?.computed) {
      children.push(rectFromBounds(child.computed.layout_bounds));
    }
  }
  return {
    label: nodeDisplayName(node),
    container: rectFromBounds(node.computed.layout_bounds),
    children
  };
}

function rectFromBounds(bounds: SelectionRect): SelectionRect {
  return {
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height
  };
}
