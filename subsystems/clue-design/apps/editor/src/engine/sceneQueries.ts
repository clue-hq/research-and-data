import type { AssetId, Node, NodeId, Page, PageId, ParentRef, Rect, Scene, SizeSpec, Slot, Transform } from "./contracts";

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

/**
 * A container the user can select and accidentally drag as a unit: a
 * frame/group/auto-layout that actually holds children. Selecting one moves
 * its contents (correct), so the canvas gives it distinct chrome — a labeled
 * box plus child outlines — to make "I grabbed a container of N elements"
 * legible before any drag.
 */
export function isContainerNode(node: Node): boolean {
  return canNodeHaveChildren(node) && node.children.length > 0;
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

/**
 * The outermost ancestor of `nodeId` that is a direct child of a page — i.e.
 * the top-level container the node belongs to. Walks up the parent chain
 * until the parent is the page (or the chain ends). Returns `nodeId` itself
 * when the node is already top-level, and `null` for a null/unknown node.
 *
 * Canvas double-click uses this for deliberate container targeting: a single
 * click drills to the deepest leaf, a double-click grabs the whole top-level
 * group it belongs to — reachable even when the container's background is
 * fully covered by its children.
 */
export function topLevelAncestorId(scene: Scene, nodeId: NodeId | null): NodeId | null {
  if (!nodeId || !scene.nodes[nodeId]) {
    return null;
  }
  let current = nodeId;
  // Bounded by the node count: each step moves strictly toward the root, and
  // a malformed cycle is stopped by the visited guard.
  const visited = new Set<NodeId>([current]);
  for (;;) {
    const parentInfo = parentInfoForNode(scene, current);
    if (!parentInfo || parentInfo.parent.kind !== "node") {
      return current;
    }
    const parentId = parentInfo.parent.id;
    if (visited.has(parentId)) {
      return current;
    }
    visited.add(parentId);
    current = parentId;
  }
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

/** Phase 1d freehand: a pinned node — the solver lays it out at its
 * page-space `absolute_box`, so the human owns its geometry directly. */
export function isNodePinned(scene: Scene, nodeId: NodeId | null): boolean {
  if (!nodeId) {
    return false;
  }
  return scene.nodes[nodeId]?.position_mode === "absolute";
}

/** A node the human freehands directly: pinned Absolute, or a child of a
 * Free container (whose children all live at hand-placed transforms).
 * Mirrors the Rust engine's `is_freehand` (layout.rs). */
export function isNodeFreehand(scene: Scene, nodeId: NodeId | null): boolean {
  if (!nodeId) {
    return false;
  }
  if (isNodePinned(scene, nodeId)) {
    return true;
  }
  const parentInfo = parentInfoForNode(scene, nodeId);
  if (!parentInfo || parentInfo.parent.kind !== "node") {
    return false;
  }
  const parent = scene.nodes[parentInfo.parent.id];
  return parent?.kind.kind === "auto_layout" && parent.layout?.layout_mode === "free";
}

export function isNodeDirectGeometryEditable(scene: Scene, nodeId: NodeId | null): boolean {
  if (!nodeId) {
    return false;
  }
  const node = scene.nodes[nodeId];
  if (!node || node.locked) {
    return false;
  }
  // Freehand nodes opted out of the solver: the human owns their geometry
  // even though the parent is an auto-layout container (Phase 1d).
  return !isNodeLayoutManaged(scene, nodeId) || isNodeFreehand(scene, nodeId);
}

/**
 * Handoff-absolute (lazy seam): whether a human gesture on this node is
 * blocked FOR NO OTHER REASON than solver ownership — i.e. freezing every
 * Stack container would make it directly geometry-editable. False for a
 * locked node, an already-editable node, or a node blocked by something a
 * freeze cannot fix (there is currently no other blocking reason, but this
 * stays an explicit allow-list rather than "not editable" so a future
 * blocking reason doesn't silently start firing freezes for it). Mirrors
 * `isNodeDirectGeometryEditable`'s predicate family; the engine remains the
 * authority — this is UI pre-gating only.
 */
export function isNodeFreezableOnGesture(scene: Scene, nodeId: NodeId | null): boolean {
  if (!nodeId) {
    return false;
  }
  const node = scene.nodes[nodeId];
  if (!node || node.locked) {
    return false;
  }
  if (isNodeDirectGeometryEditable(scene, nodeId)) {
    return false;
  }
  return isNodeLayoutManaged(scene, nodeId) && !isNodeFreehand(scene, nodeId);
}

/** Z-order position of a node among its siblings (Phase 4b arrange). Null
 * when the node has no resolvable parent info. */
export interface SiblingArrangeInfo {
  siblings: NodeId[];
  index: number;
  isFront: boolean;
  isBack: boolean;
}

export function siblingArrangeInfo(scene: Scene, nodeId: NodeId | null): SiblingArrangeInfo | null {
  if (!nodeId) {
    return null;
  }
  const parentInfo = parentInfoForNode(scene, nodeId);
  if (!parentInfo) {
    return null;
  }
  return {
    siblings: parentInfo.siblings,
    index: parentInfo.index,
    isFront: parentInfo.index === parentInfo.siblings.length - 1,
    isBack: parentInfo.index === 0
  };
}

/**
 * Whether a set of nodes is eligible to be grouped (Phase 4b arrange): at
 * least two nodes, all present, none locked, all sharing the same parent,
 * and none a solver-managed child of a Stack auto-layout container (the
 * engine rejects those with LifecycleProtected — detach to freehand first).
 * Mirrors the `isNodeDirectGeometryEditable` predicate family; the engine
 * remains the authority, this is UI pre-gating only.
 */
export function canGroupNodes(scene: Scene, nodeIds: NodeId[]): boolean {
  if (nodeIds.length < 2) {
    return false;
  }
  const uniqueIds = new Set(nodeIds);
  if (uniqueIds.size !== nodeIds.length) {
    return false;
  }
  let sharedParentId: string | null = null;
  for (const nodeId of nodeIds) {
    const node = scene.nodes[nodeId];
    if (!node || node.locked) {
      return false;
    }
    if (isNodeLayoutManaged(scene, nodeId) && !isNodeFreehand(scene, nodeId)) {
      return false;
    }
    const parentInfo = parentInfoForNode(scene, nodeId);
    if (!parentInfo) {
      return false;
    }
    const parentKey = `${parentInfo.parent.kind}:${parentInfo.parent.id}`;
    if (sharedParentId === null) {
      sharedParentId = parentKey;
    } else if (sharedParentId !== parentKey) {
      return false;
    }
  }
  return true;
}

/** Whether a single node can be ungrouped (Phase 4b arrange): a Frame,
 * Group, or AutoLayout container that isn't locked. Auto-layout containers
 * are still shown but require `allow_layout` on the edit itself — the
 * engine is the authority on that override. */
export function canUngroupNode(scene: Scene, nodeId: NodeId | null): boolean {
  if (!nodeId) {
    return false;
  }
  const node = scene.nodes[nodeId];
  if (!node || node.locked) {
    return false;
  }
  return canNodeHaveChildren(node);
}

/** Whether a set of nodes is eligible for Align (2+ nodes): every node must
 * be present, unlocked, and direct-geometry-editable (pinned Absolute, or a
 * freehand child of a Free auto-layout container) — the same class of node
 * a drag can move. Mirrors `canGroupNodes`'s all-must-pass shape; the engine
 * remains the authority, this is UI pre-gating only. */
export function canAlignNodes(scene: Scene, nodeIds: NodeId[]): boolean {
  if (nodeIds.length < 2) {
    return false;
  }
  return nodeIds.every((nodeId) => isNodeDirectGeometryEditable(scene, nodeId));
}

/** Whether a set of nodes is eligible for Distribute (3+ nodes) — same
 * per-node eligibility as `canAlignNodes`, just a higher count floor since
 * distributing needs a first/last anchor plus at least one node to space. */
export function canDistributeNodes(scene: Scene, nodeIds: NodeId[]): boolean {
  if (nodeIds.length < 3) {
    return false;
  }
  return nodeIds.every((nodeId) => isNodeDirectGeometryEditable(scene, nodeId));
}

/** A node's current solved page-space box (scene units) — the same
 * geometry `canvasDragOperations` reads before computing a drag delta: the
 * pinned `absolute_box` when pinned (falling back to solved computed bounds
 * for a boxless pin), else `computed.layout_bounds`. Null when neither is
 * available (never laid out yet). */
export function nodePageSpaceBox(scene: Scene, nodeId: NodeId): Rect | null {
  const node = scene.nodes[nodeId];
  if (!node) {
    return null;
  }
  if (node.position_mode === "absolute") {
    return node.absolute_box ?? (node.computed ? { ...node.computed.layout_bounds } : null);
  }
  return node.computed ? { ...node.computed.layout_bounds } : null;
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

/** Page-space origin of a node's parent container ((0,0) for page parents
 * or unsolved parents) — the offset between parent-relative transform
 * coordinates and page space. Phase 1d uses it to commit Free-container
 * child drags in the parent's frame. */
export function parentComputedOrigin(scene: Scene, nodeId: NodeId): { x: number; y: number } {
  const parentInfo = parentInfoForNode(scene, nodeId);
  if (!parentInfo || parentInfo.parent.kind !== "node") {
    return { x: 0, y: 0 };
  }
  const bounds = scene.nodes[parentInfo.parent.id]?.computed?.layout_bounds;
  return bounds ? { x: bounds.x, y: bounds.y } : { x: 0, y: 0 };
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
