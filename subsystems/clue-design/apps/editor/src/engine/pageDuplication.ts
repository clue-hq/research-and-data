import type { Node, NodeId, Operation, Page, PageId, ParentRef, Scene } from "./contracts";
import { addPage, bindNodeToSlot, insertNode } from "./operations";

export function uniquePageId(
  scene: Scene,
  input: { name: string; width: number; height: number }
): PageId {
  const readable = input.name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const base = readable || `custom_${input.width}x${input.height}`;
  let candidate = `page_${base}`;
  let index = 2;
  while (scene.pages[candidate]) {
    candidate = `page_${base}_${index}`;
    index += 1;
  }
  return candidate;
}

/** The canonical-operation expansion of "duplicate this page": a new page plus
 * a full node-tree clone with fresh ids and re-bound slots. */
export function duplicatePageOperations(scene: Scene, page: Page): Operation[] {
  const pageName = `${page.name} Copy`;
  const pageId = uniquePageId(scene, {
    name: pageName,
    width: page.size.width,
    height: page.size.height
  });
  const usedNodeIds = new Set(Object.keys(scene.nodes));
  const nodeIdMap = new Map<NodeId, NodeId>();

  const assignNodeIds = (nodeId: NodeId) => {
    if (nodeIdMap.has(nodeId)) {
      return;
    }
    const clonedNodeId = uniqueClonedNodeId(usedNodeIds, nodeId, pageId);
    nodeIdMap.set(nodeId, clonedNodeId);
    const node = scene.nodes[nodeId];
    for (const childId of node?.children ?? []) {
      assignNodeIds(childId);
    }
  };

  for (const childId of page.children) {
    assignNodeIds(childId);
  }

  const duplicatedPage: Page = {
    ...cloneJson(page),
    id: pageId,
    name: pageName,
    children: []
  };
  const operations: Operation[] = [addPage(duplicatedPage)];

  const emitNodeTree = (sourceNodeId: NodeId, parent: ParentRef, index: number) => {
    const sourceNode = scene.nodes[sourceNodeId];
    const clonedNodeId = nodeIdMap.get(sourceNodeId);
    if (!sourceNode || !clonedNodeId) {
      return;
    }
    const clonedNode: Node = {
      ...cloneJson(sourceNode),
      id: clonedNodeId,
      children: [],
      computed: null
    };
    operations.push(insertNode(parent, index, clonedNode));

    for (const slot of Object.values(scene.slots)) {
      if (slot.bound_nodes.includes(sourceNodeId)) {
        operations.push(bindNodeToSlot(slot.id, clonedNodeId));
      }
    }

    sourceNode.children.forEach((childId, childIndex) =>
      emitNodeTree(childId, { kind: "node", id: clonedNodeId }, childIndex)
    );
  };

  page.children.forEach((childId, index) =>
    emitNodeTree(childId, { kind: "page", id: pageId }, index)
  );

  return operations;
}

function uniqueClonedNodeId(usedNodeIds: Set<NodeId>, sourceNodeId: NodeId, pageId: PageId): NodeId {
  const pageSuffix = pageId
    .replace(/^page_/, "")
    .replace(/[^a-zA-Z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const base = `${sourceNodeId}_${pageSuffix || "copy"}`;
  let candidate = base;
  let index = 2;
  while (usedNodeIds.has(candidate)) {
    candidate = `${base}_${index}`;
    index += 1;
  }
  usedNodeIds.add(candidate);
  return candidate;
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
