import type { Node, NodeId, Page, PageId, Scene, Slot } from "./contracts";

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
