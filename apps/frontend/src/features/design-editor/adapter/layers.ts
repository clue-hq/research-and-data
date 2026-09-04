import type { WebNode } from "../engine/webDocuments";
import { displayNameForNode, type FragmentMetaMap } from "./node-names";

/**
 * W2.3: layer rows from the real document node hierarchy, replacing the
 * dummy's fixture trees. Displayed nesting is capped at depth 1 (ruling 41):
 * the page root's children are depth 0, their children depth 1, and nothing
 * deeper renders — so a depth-1 node with children is NOT expandable (its
 * subtree has no rows to reveal).
 *
 * Icons use the dummy's own vocabulary (`InspectorLayerRow`'s set):
 * section/container → div, text → type, button → rectangle, image → image,
 * icon → apple; anything else (embed/component/custom_component/unknown)
 * falls back to div, the generic block glyph.
 */
/** The dummy `InspectorLayerRow`'s icon vocabulary, mirrored (its prop type
 * is this exact union). */
export type WebLayerIcon =
  | "apple"
  | "div"
  | "ellipse"
  | "image"
  | "rectangle"
  | "type";

export interface WebLayerRow {
  nodeId: string;
  label: string;
  icon: WebLayerIcon;
  depth: 0 | 1;
  /** Depth-0 only and only when it has displayable children. */
  expandable: boolean;
  /** The depth-0 parent for collapse filtering; null on depth-0 rows. */
  parentId: string | null;
  active: boolean;
}

export interface WebLayerPage {
  page_root: string;
  nodes: Record<string, WebNode>;
}

const KIND_TO_ICON: Record<string, WebLayerIcon> = {
  button: "rectangle",
  container: "div",
  icon: "apple",
  image: "image",
  section: "div",
  text: "type",
};

function iconFor(node: WebNode): WebLayerIcon {
  return KIND_TO_ICON[node.kind] ?? "div";
}

export function buildWebLayerRows(
  page: WebLayerPage,
  activeNodeId: string | null,
  fragmentMeta?: FragmentMetaMap,
): WebLayerRow[] {
  const root = page.nodes[page.page_root];
  if (!root) return [];
  const rows: WebLayerRow[] = [];
  for (const topId of root.children ?? []) {
    const top = page.nodes[topId];
    if (!top) continue;
    const childIds = (top.children ?? []).filter((id) => page.nodes[id]);
    rows.push({
      active: top.id === activeNodeId,
      depth: 0,
      expandable: childIds.length > 0,
      icon: iconFor(top),
      label: displayNameForNode(top, page.nodes, fragmentMeta),
      nodeId: top.id,
      parentId: null,
    });
    for (const childId of childIds) {
      const child = page.nodes[childId];
      rows.push({
        active: child.id === activeNodeId,
        depth: 1,
        // Ruling 41: depth-1 subtrees never render, so nothing to expand.
        expandable: false,
        icon: iconFor(child),
        label: displayNameForNode(child, page.nodes, fragmentMeta),
        nodeId: child.id,
        parentId: top.id,
      });
    }
  }
  return rows;
}
