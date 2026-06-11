import type { Node as SceneNodeModel, Operation, Page, Scene, Transform } from "./contracts";
import { updateNodeTransform, updateNodeTransformAndSize } from "./operations";
import { nodeSizeForRender, sceneUnitFromCanvas } from "./renderAdapter";
import {
  clampNodeSizeToParentBounds,
  clampNodeTransformToParentBounds,
  isNodeDirectGeometryEditable,
  parentInfoForNode
} from "./sceneQueries";

const SNAP_THRESHOLD_CANVAS_PX = 6;

export interface CanvasPoint {
  x: number;
  y: number;
}

export interface CanvasTransformInput {
  canvasX: number;
  canvasY: number;
  rotation: number;
  scaleX: number;
  scaleY: number;
}

export function canvasDragOperation({
  scene,
  node,
  page,
  pageOrigin,
  canvasX,
  canvasY
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  pageOrigin: CanvasPoint;
  canvasX: number;
  canvasY: number;
}): Operation | null {
  if (!isNodeDirectGeometryEditable(scene, node.id) || !Number.isFinite(canvasX) || !Number.isFinite(canvasY)) {
    return null;
  }

  const rawTransform = {
    ...node.transform,
    x: sceneUnitFromCanvas(canvasX - pageOrigin.x, page),
    y: sceneUnitFromCanvas(canvasY - pageOrigin.y, page)
  };
  const nextTransform = clampNodeTransformToParentBounds(
    scene,
    node,
    snapTransformToGuides({
      scene,
      node,
      page,
      transform: rawTransform,
      size: nodeSceneUnitSize(node, page)
    })
  );
  return updateNodeTransform(node, nextTransform);
}

export function canvasResizeOperation({
  scene,
  node,
  page,
  pageOrigin,
  transform
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  pageOrigin: CanvasPoint;
  transform: CanvasTransformInput;
}): Operation | null {
  if (!isNodeDirectGeometryEditable(scene, node.id) || !validCanvasTransform(transform)) {
    return null;
  }

  const baseSize = nodeSizeForRender(node, page);
  const nextWidth = Math.max(2, baseSize.width * Math.abs(transform.scaleX));
  const nextHeight = Math.max(2, baseSize.height * Math.abs(transform.scaleY));
  const nextTransform: Transform = {
    ...node.transform,
    x: sceneUnitFromCanvas(transform.canvasX - pageOrigin.x, page),
    y: sceneUnitFromCanvas(transform.canvasY - pageOrigin.y, page),
    rotation: transform.rotation
  };
  const rawSize = {
    width: sceneUnitFromCanvas(nextWidth, page),
    height: sceneUnitFromCanvas(nextHeight, page)
  };
  const snapped = snapTransformAndSizeToGuides({
    scene,
    node,
    page,
    transform: nextTransform,
    size: rawSize
  });
  const nextSize = clampNodeSizeToParentBounds(scene, node, snapped.size);
  const clampedTransform = clampNodeTransformToParentBounds(scene, node, snapped.transform, nextSize);

  return updateNodeTransformAndSize(node, clampedTransform, {
    width: {
      kind: "fixed",
      value: nextSize.width
    },
    height: {
      kind: "fixed",
      value: nextSize.height
    }
  });
}

function validCanvasTransform(transform: CanvasTransformInput): boolean {
  return (
    Number.isFinite(transform.canvasX) &&
    Number.isFinite(transform.canvasY) &&
    Number.isFinite(transform.rotation) &&
    Number.isFinite(transform.scaleX) &&
    Number.isFinite(transform.scaleY) &&
    transform.scaleX !== 0 &&
    transform.scaleY !== 0
  );
}

function snapTransformToGuides({
  scene,
  node,
  page,
  transform,
  size
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  transform: Transform;
  size: { width: number; height: number };
}): Transform {
  const guides = guidesForNodeParent(scene, node, page);
  if (!guides) {
    return transform;
  }
  const threshold = sceneUnitFromCanvas(SNAP_THRESHOLD_CANVAS_PX, page);
  return {
    ...transform,
    x: snapPosition(transform.x, size.width, guides.x, threshold),
    y: snapPosition(transform.y, size.height, guides.y, threshold)
  };
}

function snapTransformAndSizeToGuides({
  scene,
  node,
  page,
  transform,
  size
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  transform: Transform;
  size: { width: number; height: number };
}): { transform: Transform; size: { width: number; height: number } } {
  const guides = guidesForNodeParent(scene, node, page);
  if (!guides) {
    return {
      transform,
      size
    };
  }
  const threshold = sceneUnitFromCanvas(SNAP_THRESHOLD_CANVAS_PX, page);
  const snapped = {
    transform: { ...transform },
    size: { ...size }
  };
  const snappedX = snapPosition(snapped.transform.x, snapped.size.width, guides.x, threshold, false);
  const snappedY = snapPosition(snapped.transform.y, snapped.size.height, guides.y, threshold, false);
  snapped.transform.x = snappedX;
  snapped.transform.y = snappedY;
  snapped.size.width = snapExtent(snapped.transform.x, snapped.size.width, guides.x, threshold);
  snapped.size.height = snapExtent(snapped.transform.y, snapped.size.height, guides.y, threshold);
  return snapped;
}

function snapPosition(
  position: number,
  extent: number,
  guides: number[],
  threshold: number,
  includeEnd = true
): number {
  const candidates = [
    {
      distance: Infinity,
      value: position
    }
  ];
  for (const guide of guides) {
    candidates.push({
      distance: Math.abs(position - guide),
      value: guide
    });
    candidates.push({
      distance: Math.abs(position + extent / 2 - guide),
      value: guide - extent / 2
    });
    if (includeEnd) {
      candidates.push({
        distance: Math.abs(position + extent - guide),
        value: guide - extent
      });
    }
  }
  const best = candidates.reduce((current, candidate) =>
    candidate.distance < current.distance ? candidate : current
  );
  return best.distance <= threshold ? roundForOperation(best.value) : position;
}

function snapExtent(position: number, extent: number, guides: number[], threshold: number): number {
  const end = position + extent;
  const best = guides
    .map((guide) => ({
      distance: Math.abs(end - guide),
      value: guide - position
    }))
    .filter((candidate) => candidate.value > 0)
    .reduce<{ distance: number; value: number } | null>(
      (current, candidate) => (!current || candidate.distance < current.distance ? candidate : current),
      null
    );
  return best && best.distance <= threshold ? roundForOperation(best.value) : extent;
}

function guidesForNodeParent(
  scene: Scene,
  node: SceneNodeModel,
  page: Page
): { x: number[]; y: number[] } | null {
  const parentInfo = parentInfoForNode(scene, node.id);
  if (!parentInfo) {
    return null;
  }

  if (parentInfo.parent.kind === "page") {
    const parentPage = scene.pages[parentInfo.parent.id];
    if (!parentPage) {
      return null;
    }
    const guides = guidesForBounds(parentPage.size.width, parentPage.size.height);
    if (parentPage.safe_area) {
      guides.x.push(parentPage.safe_area.x, parentPage.safe_area.x + parentPage.safe_area.width, parentPage.safe_area.x + parentPage.safe_area.width / 2);
      guides.y.push(parentPage.safe_area.y, parentPage.safe_area.y + parentPage.safe_area.height, parentPage.safe_area.y + parentPage.safe_area.height / 2);
    }
    return dedupeGuides(guides);
  }

  const parentNode = scene.nodes[parentInfo.parent.id];
  if (!parentNode) {
    return null;
  }
  const parentSize = nodeSceneUnitSize(parentNode, page);
  return dedupeGuides(guidesForBounds(parentSize.width, parentSize.height));
}

function nodeSceneUnitSize(node: SceneNodeModel, page: Page): { width: number; height: number } {
  const canvasSize = nodeSizeForRender(node, page);
  return {
    width: sceneUnitFromCanvas(canvasSize.width, page),
    height: sceneUnitFromCanvas(canvasSize.height, page)
  };
}

function guidesForBounds(width: number, height: number): { x: number[]; y: number[] } {
  return {
    x: [0, width / 2, width],
    y: [0, height / 2, height]
  };
}

function dedupeGuides(guides: { x: number[]; y: number[] }): { x: number[]; y: number[] } {
  return {
    x: [...new Set(guides.x.filter(Number.isFinite))],
    y: [...new Set(guides.y.filter(Number.isFinite))]
  };
}

function roundForOperation(value: number): number {
  return Math.round(value * 1000) / 1000;
}
