import type { AssetId, Node, NodeId, Page, PageId, ParentRef, Scene, SizeSpec, Slot, Transform } from "./contracts";

export function listPages(scene: Scene): Page[] {
  return Object.values(scene.pages);
}

export function firstPageId(scene: Scene): PageId | null {
  return listPages(scene)[0]?.id ?? null;
}

export function getPage(scene: Scene, pageId: PageId | null): Page | null {
  if (!pageId) {
    return null;
  }
  return scene.pages[pageId] ?? null;
}

export function getNode(scene: Scene, nodeId: NodeId | null): Node | null {
  if (!nodeId) {
    return null;
  }
  return scene.nodes[nodeId] ?? null;
}

export function canNodeHaveChildren(node: Node): boolean {
  return ["frame", "group", "auto_layout"].includes(node.kind.kind);
}

export function pageNodeTree(scene: Scene, pageId: PageId): Node[] {
  const page = scene.pages[pageId];
  if (!page) {
    return [];
  }
  return page.children.map((nodeId) => scene.nodes[nodeId]).filter(Boolean);
}

export function flattenPageNodeIds(scene: Scene, pageId: PageId): NodeId[] {
  const page = scene.pages[pageId];
  if (!page) {
    return [];
  }
  const ids: NodeId[] = [];
  const visit = (nodeId: NodeId) => {
    const node = scene.nodes[nodeId];
    if (!node) {
      return;
    }
    ids.push(node.id);
    for (const childId of node.children) {
      visit(childId);
    }
  };
  for (const nodeId of page.children) {
    visit(nodeId);
  }
  return ids;
}

export function pageIdForNode(scene: Scene, nodeId: NodeId): PageId | null {
  for (const page of Object.values(scene.pages)) {
    if (flattenPageNodeIds(scene, page.id).includes(nodeId)) {
      return page.id;
    }
  }
  return null;
}

export function nodeIdForAsset(scene: Scene, assetId: AssetId): NodeId | null {
  const visitedNodeIds = new Set<NodeId>();

  for (const page of Object.values(scene.pages)) {
    for (const nodeId of flattenPageNodeIds(scene, page.id)) {
      visitedNodeIds.add(nodeId);
      const node = scene.nodes[nodeId];
      if (node && nodeUsesAsset(node, assetId)) {
        return node.id;
      }
    }
  }

  for (const node of Object.values(scene.nodes)) {
    if (!visitedNodeIds.has(node.id) && nodeUsesAsset(node, assetId)) {
      return node.id;
    }
  }

  return null;
}

export interface NodeParentInfo {
  parent: ParentRef;
  siblings: NodeId[];
  index: number;
}

export function parentInfoForNode(scene: Scene, nodeId: NodeId): NodeParentInfo | null {
  for (const page of Object.values(scene.pages)) {
    const index = page.children.indexOf(nodeId);
    if (index >= 0) {
      return {
        parent: {
          kind: "page",
          id: page.id
        },
        siblings: page.children,
        index
      };
    }
  }

  for (const node of Object.values(scene.nodes)) {
    const index = node.children.indexOf(nodeId);
    if (index >= 0) {
      return {
        parent: {
          kind: "node",
          id: node.id
        },
        siblings: node.children,
        index
      };
    }
  }

  return null;
}

export function isNodeLayoutManaged(scene: Scene, nodeId: NodeId | null): boolean {
  if (!nodeId) {
    return false;
  }
  const parentInfo = parentInfoForNode(scene, nodeId);
  if (!parentInfo || parentInfo.parent.kind !== "node") {
    return false;
  }
  return scene.nodes[parentInfo.parent.id]?.kind.kind === "auto_layout";
}

export function isNodeDirectGeometryEditable(scene: Scene, nodeId: NodeId | null): boolean {
  if (!nodeId) {
    return false;
  }
  const node = scene.nodes[nodeId];
  if (!node || node.locked) {
    return false;
  }
  return !isNodeLayoutManaged(scene, nodeId);
}

export function clampNodeTransformToParentBounds(
  scene: Scene,
  node: Node,
  transform: Transform,
  size: { width: number; height: number } = nodeSceneSize(node)
): Transform {
  const parentBounds = parentBoundsForNode(scene, node.id);
  if (!parentBounds) {
    return transform;
  }
  return {
    ...transform,
    x: clampForEditor(transform.x, 0, Math.max(0, parentBounds.width - size.width)),
    y: clampForEditor(transform.y, 0, Math.max(0, parentBounds.height - size.height))
  };
}

export function clampNodeSizeToParentBounds(
  scene: Scene,
  node: Node,
  size: { width: number; height: number }
): { width: number; height: number } {
  const parentBounds = parentBoundsForNode(scene, node.id);
  if (!parentBounds) {
    return {
      width: positiveFiniteSize(size.width),
      height: positiveFiniteSize(size.height)
    };
  }

  return {
    width: clampForEditor(positiveFiniteSize(size.width), 1, Math.max(1, parentBounds.width)),
    height: clampForEditor(positiveFiniteSize(size.height), 1, Math.max(1, parentBounds.height))
  };
}

export function slotsForNode(scene: Scene, nodeId: NodeId | null): Slot[] {
  if (!nodeId) {
    return [];
  }
  return Object.values(scene.slots).filter((slot) => slot.bound_nodes.includes(nodeId));
}

export function slotByNode(scene: Scene, nodeId: NodeId | null): Slot | null {
  return slotsForNode(scene, nodeId)[0] ?? null;
}

export function nodeDisplayName(node: Node): string {
  return node.name ?? `${node.kind.kind} ${node.id}`;
}

export interface SlotBoundNodeSummary {
  nodeId: NodeId;
  nodeName: string;
  pageId: PageId | null;
  pageName: string | null;
}

export function slotBoundNodeSummaries(scene: Scene, slot: Slot): SlotBoundNodeSummary[] {
  return slot.bound_nodes.map((nodeId) => {
    const node = scene.nodes[nodeId] ?? null;
    const pageId = pageIdForNode(scene, nodeId);
    const page = pageId ? scene.pages[pageId] ?? null : null;
    return {
      nodeId,
      nodeName: node ? nodeDisplayName(node) : "Missing node",
      pageId,
      pageName: page?.name ?? null
    };
  });
}

function nodeUsesAsset(node: Node, assetId: AssetId): boolean {
  return node.source_asset_id === assetId || (node.kind.kind === "image" && node.kind.asset_id === assetId);
}

function parentBoundsForNode(scene: Scene, nodeId: NodeId): { width: number; height: number } | null {
  const parentInfo = parentInfoForNode(scene, nodeId);
  if (!parentInfo) {
    return null;
  }
  if (parentInfo.parent.kind === "page") {
    const page = scene.pages[parentInfo.parent.id];
    return page
      ? {
          width: page.size.width,
          height: page.size.height
        }
      : null;
  }
  const parent = scene.nodes[parentInfo.parent.id];
  return parent ? nodeSceneSize(parent) : null;
}

function nodeSceneSize(node: Node): { width: number; height: number } {
  if (node.computed) {
    return {
      width: node.computed.layout_bounds.width,
      height: node.computed.layout_bounds.height
    };
  }
  return {
    width: dimensionSceneValue(node.size.width),
    height: dimensionSceneValue(node.size.height)
  };
}

function dimensionSceneValue(dimension: SizeSpec["width"]): number {
  return dimension.kind === "fixed" ? dimension.value : 0;
}

function clampForEditor(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function positiveFiniteSize(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 1;
}
