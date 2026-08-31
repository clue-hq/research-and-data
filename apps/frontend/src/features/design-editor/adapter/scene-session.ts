import type { NodeId, PageId, Scene } from "../engine/scene/contracts";
import { rootFrameId } from "./scene-hydrate";

/**
 * AD2.7: the four pure decisions behind the shared ad editing session.
 *
 * `useSceneEditingSession` owns transport, refs and React state; everything it
 * DECIDES lives here, where it is proven against real scenes instead of a
 * browser. The website lane keeps the same split (its session hook holds the
 * wiring, `adapter/layers.ts` + `adapter/hydrate.ts` hold the rules).
 */

/**
 * A node's ancestors, nearest first, up to (but not including) the page.
 *
 * The scene stores children, never parents, so the chain is walked over a
 * parent index built once per call — `parentInfoForNode` is a full scan per
 * step and this runs on every selection change.
 *
 * A node that is not in the scene, or that sits directly under the page, has no
 * ancestors. A malformed (cyclic) scene terminates on the visited set rather
 * than looping: a broken document must not hang the panel.
 */
export function sceneAncestorIds(
  scene: Scene,
  nodeId: NodeId | null,
): NodeId[] {
  if (!nodeId || !scene.nodes[nodeId]) {
    return [];
  }
  const parents = new Map<NodeId, NodeId>();
  for (const node of Object.values(scene.nodes)) {
    for (const childId of node.children) {
      parents.set(childId, node.id);
    }
  }
  const chain: NodeId[] = [];
  const seen = new Set<NodeId>([nodeId]);
  let current = parents.get(nodeId);
  while (current && !seen.has(current)) {
    chain.push(current);
    seen.add(current);
    current = parents.get(current);
  }
  return chain;
}

/**
 * Which container rows are open, given what the user has toggled.
 *
 * `sceneLayerRows` takes `expanded` as an INPUT (AD2.6) — nobody below owns it
 * — and an empty set makes the whole panel ONE row: the artboard frame is a
 * depth-0 row and everything else is its descendant. So the set is *seeded*
 * rather than born empty:
 *
 *   • the page's root frame, always — otherwise the panel opens collapsed onto
 *     a single row and looks broken;
 *   • every ancestor of the primary selection — a node picked on the canvas
 *     must be a visible row, which is also what makes AD2.6's
 *     auto-scroll-to-primary reachable.
 *
 * `manual` is the user's own toggles (`true` opened, `false` closed) and wins
 * over the seed, so collapsing a seeded row stays collapsed. Selecting a node
 * inside a row the user closed does NOT force it back open — the seed is
 * additive, never corrective — which keeps a click on the canvas from
 * undoing an explicit collapse.
 */
export function sceneExpansion(
  scene: Scene,
  pageId: PageId | null,
  primaryNodeId: NodeId | null,
  manual: ReadonlyMap<string, boolean>,
): Set<string> {
  const expanded = new Set<string>();
  const root = pageId ? rootFrameId(scene, pageId) : null;
  if (root) {
    expanded.add(root);
  }
  for (const ancestorId of sceneAncestorIds(scene, primaryNodeId)) {
    expanded.add(ancestorId);
  }
  for (const [nodeId, open] of manual) {
    if (open) {
      expanded.add(nodeId);
    } else {
      expanded.delete(nodeId);
    }
  }
  return expanded;
}

/**
 * The next additive selection (§1.7/§1.8).
 *
 * A plain click REPLACES — one node, and it is the primary. An additive click
 * (shift/⌘, decided by the row/canvas that saw the modifier) toggles that node
 * in or out of the set, appending at the end so `[0]` — the node whose schema
 * the inspector renders — stays whatever it already was. Removing the primary
 * promotes the next member; removing the last member clears the selection,
 * which is the canvas schema, never a stale one.
 *
 * `null` clears (a press on empty canvas). An additive `null` is still a clear:
 * there is no node to add.
 */
export function nextSceneSelection(
  current: readonly string[],
  nodeId: string | null,
  additive: boolean,
): string[] {
  if (nodeId === null) {
    return [];
  }
  if (!additive) {
    return [nodeId];
  }
  return current.includes(nodeId)
    ? current.filter((id) => id !== nodeId)
    : [...current, nodeId];
}

/**
 * The Font-family select's vocabulary (§2 row 3): `Inter` first, then the
 * curated library's families, then the document's brand-kit families.
 *
 * Inter leads because it is the shared inspector default (`DEFAULT_STATE`) and
 * a select whose value is absent from its own options renders as blank — so the
 * one guaranteed entry is also the one guaranteed fallback. Duplicates are
 * dropped keeping FIRST occurrence, so a kit family that the library also ships
 * appears once, in library order.
 *
 * Empty inputs (both fetches failed, or a document with no kit) collapse to
 * `["Inter"]` — never an empty list, which would strand the control.
 */
export function sceneFontOptions(
  libraryFamilies: readonly string[],
  kitFamilies: readonly string[],
): string[] {
  const options: string[] = [];
  for (const family of ["Inter", ...libraryFamilies, ...kitFamilies]) {
    if (family && !options.includes(family)) {
      options.push(family);
    }
  }
  return options;
}
