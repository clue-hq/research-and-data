import type {
  AssetId,
  Node,
  NodeId,
  PageId,
  Rect,
  Scene,
} from "../engine/scene/contracts";
import {
  nodePageSpaceBox,
  pageIdForNode,
  parentComputedOrigin,
} from "../engine/scene/sceneQueries";

/**
 * Scene clipboard Task 1 — the versioned DTO and the subtree serializer.
 *
 * The payload is a DTO, not the live store: `Node` is already a serializable
 * contract type, so the DTO reuses it verbatim, but every node is deep-cloned
 * at capture — a clipboard payload is a snapshot, and a later edit to the
 * scene must not reach into it. The envelope carries `kind` + `version` so a
 * future contract drift becomes a migration, not a crash.
 *
 * Everything here is pure: no clipboard API, no DOM, no transport. The event
 * wiring (Task 7) composes these functions; nothing composes them the other
 * way around.
 */

export const SCENE_CLIPBOARD_KIND = "clue.scene/clipboard";
export const SCENE_CLIPBOARD_MIME = "application/vnd.clue.scene+json";

export interface SceneClipboardPayloadV1 {
  kind: typeof SCENE_CLIPBOARD_KIND;
  version: 1;
  /** Display/debug only — NEVER trusted for auth. Asset resolution against
   * the pasting workspace's own store is the actual cross-workspace gate.
   * Born null here (a Scene names no workspace); the copy gesture may stamp
   * one before the payload reaches the OS clipboard. */
  workspaceHint: string | null;
  /** V1: exactly one root (the shipped selection model is single-node). */
  roots: NodeId[];
  /** Root + full descendant closure, DFS preorder — document order, parents
   * before children, which is exactly the insert order paste needs. */
  nodes: Node[];
  /** Workspace-scoped refs for every ImageNode in `nodes`, deduplicated. */
  assetIds: AssetId[];
  /** The root's page-space box — what placement planning offsets from. */
  bounds: { x: number; y: number; width: number; height: number };
  /** Pre-extracted text-node contents for the `text/plain` representation
   * (human-readable, never the JSON — the Excalidraw Safari-leak lesson). */
  readableText: string;
}

/**
 * Serialize `rootId`'s subtree from the scene's flat node map into a clipboard
 * payload. Returns null when the root resolves to no node — including a root
 * that lives on a different page than the one named, which would otherwise
 * serialize bounds against a page it is not on.
 */
export function serializeSubtree(
  scene: Scene,
  pageId: PageId,
  rootId: NodeId,
): SceneClipboardPayloadV1 | null {
  const root = scene.nodes[rootId];
  if (!root || pageIdForNode(scene, rootId) !== pageId) {
    return null;
  }

  // Closure via an iterative stack over `children`, emitting DFS preorder —
  // the same walk `flattenPageNodeIds` does, so payload order IS document
  // order. Children are pushed reversed so they pop first-child-first.
  const nodes: Node[] = [];
  const stack: NodeId[] = [rootId];
  while (stack.length > 0) {
    const id = stack.pop()!;
    const node = scene.nodes[id];
    if (!node) {
      // A dangling child id is a scene-invariant violation, not the copier's
      // to repair — the closure simply has nothing to capture for it.
      continue;
    }
    nodes.push(structuredClone(node));
    for (let index = node.children.length - 1; index >= 0; index -= 1) {
      stack.push(node.children[index]);
    }
  }

  const assetIds: AssetId[] = [];
  const seenAssets = new Set<AssetId>();
  for (const node of nodes) {
    if (node.kind.kind === "image" && !seenAssets.has(node.kind.asset_id)) {
      seenAssets.add(node.kind.asset_id);
      assetIds.push(node.kind.asset_id);
    }
  }

  return {
    kind: SCENE_CLIPBOARD_KIND,
    version: 1,
    workspaceHint: null,
    roots: [rootId],
    nodes,
    assetIds,
    bounds: rootPageSpaceBounds(scene, root),
    readableText: extractReadableText(nodes),
  };
}

/** Text-node contents in the order given (callers pass document order),
 * newline-joined — the payload's human-readable `text/plain` face. */
export function extractReadableText(nodes: readonly Node[]): string {
  const lines: string[] = [];
  for (const node of nodes) {
    if (node.kind.kind === "text") {
      lines.push(node.kind.content);
    }
  }
  return lines.join("\n");
}

/**
 * The root's page-space box. The engine's solved geometry (`absolute_box` /
 * `computed.layout_bounds`, via `nodePageSpaceBox`) is authoritative when it
 * exists; a node that has never been solved falls back to its parent-relative
 * transform rebased through `parentComputedOrigin` — (0,0) for page-parented
 * nodes, so the transform IS the page-space position there. Non-fixed
 * dimensions (hug/fill) have no honest unsolved size and read as 0.
 */
function rootPageSpaceBounds(scene: Scene, node: Node): Rect {
  const solved = nodePageSpaceBox(scene, node.id);
  if (solved) {
    return solved;
  }
  const origin = parentComputedOrigin(scene, node.id);
  return {
    x: origin.x + node.transform.x,
    y: origin.y + node.transform.y,
    width: node.size.width.kind === "fixed" ? node.size.width.value : 0,
    height: node.size.height.kind === "fixed" ? node.size.height.value : 0,
  };
}
