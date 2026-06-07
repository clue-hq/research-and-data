import type {
  FieldPatch,
  Node,
  NodePatch,
  Operation,
  OptionalFieldPatch,
  ParentRef,
  Scene
} from "./contracts";

export interface ApplyResult {
  scene: Scene;
  accepted: boolean;
  message?: string;
}

export interface EditorEnginePort {
  applyOperation(scene: Scene, operation: Operation): ApplyResult;
}

export const localEditorEngine: EditorEnginePort = {
  applyOperation(scene, operation) {
    const next = cloneScene(scene);
    try {
      applyLocalOperation(next, operation);
      return {
        scene: next,
        accepted: true
      };
    } catch (error) {
      return {
        scene,
        accepted: false,
        message: error instanceof Error ? error.message : String(error)
      };
    }
  }
};

function applyLocalOperation(scene: Scene, operation: Operation): void {
  if (scene.meta.status.kind === "finalized") {
    throw new Error("Cannot edit a finalized template revision from the editor");
  }

  switch (operation.kind) {
    case "update_node": {
      const node = getNode(scene, operation.node_id);
      if (node.locked && !isLockedOnlyPatch(operation.patch)) {
        throw new Error(`Node ${node.id} is locked`);
      }
      applyNodePatch(node, operation.patch);
      return;
    }
    case "move_node": {
      const node = getNode(scene, operation.node_id);
      if (node.locked) {
        throw new Error(`Node ${node.id} is locked`);
      }
      detachFromCurrentParent(scene, operation.node_id);
      insertIntoParent(scene, operation.new_parent, operation.node_id, operation.index);
      return;
    }
    case "upsert_slot": {
      scene.slots[operation.slot.id] = operation.slot;
      return;
    }
    case "remove_slot": {
      delete scene.slots[operation.slot_id];
      return;
    }
    case "bind_node_to_slot": {
      getNode(scene, operation.node_id);
      const slot = scene.slots[operation.slot_id];
      if (!slot) {
        throw new Error(`Missing slot ${operation.slot_id}`);
      }
      if (!slot.bound_nodes.includes(operation.node_id)) {
        slot.bound_nodes.push(operation.node_id);
      }
      return;
    }
    case "unbind_node_from_slot": {
      const slot = scene.slots[operation.slot_id];
      if (!slot) {
        throw new Error(`Missing slot ${operation.slot_id}`);
      }
      slot.bound_nodes = slot.bound_nodes.filter((nodeId) => nodeId !== operation.node_id);
      return;
    }
  }
}

function applyNodePatch(node: Node, patch: NodePatch): void {
  applyOptionalPatch(node, "name", patch.name);
  applyFieldPatch(node, "kind", patch.kind);
  applyFieldPatch(node, "transform", patch.transform);
  applyFieldPatch(node, "size", patch.size);
  applyFieldPatch(node, "fills", patch.fills);
  applyFieldPatch(node, "strokes", patch.strokes);
  applyFieldPatch(node, "corner", patch.corner);
  applyFieldPatch(node, "opacity", patch.opacity);
  applyFieldPatch(node, "clip", patch.clip);
  applyOptionalPatch(node, "layout", patch.layout);
  applyOptionalPatch(node, "computed", patch.computed);
  applyFieldPatch(node, "locked", patch.locked);
}

function applyFieldPatch<T extends object, K extends keyof T>(
  target: T,
  key: K,
  patch: FieldPatch<T[K]> | undefined
): void {
  if (!patch || patch.kind === "unchanged") {
    return;
  }
  target[key] = patch.value;
}

function applyOptionalPatch<T extends object, K extends keyof T>(
  target: T,
  key: K,
  patch: OptionalFieldPatch<NonNullable<T[K]>> | undefined
): void {
  if (!patch || patch.kind === "unchanged") {
    return;
  }
  target[key] = patch.kind === "clear" ? (null as T[K]) : (patch.value as T[K]);
}

function getNode(scene: Scene, nodeId: string): Node {
  const node = scene.nodes[nodeId];
  if (!node) {
    throw new Error(`Missing node ${nodeId}`);
  }
  return node;
}

function detachFromCurrentParent(scene: Scene, nodeId: string): void {
  for (const page of Object.values(scene.pages)) {
    page.children = page.children.filter((childId) => childId !== nodeId);
  }
  for (const node of Object.values(scene.nodes)) {
    node.children = node.children.filter((childId) => childId !== nodeId);
  }
}

function insertIntoParent(scene: Scene, parent: ParentRef, nodeId: string, index: number): void {
  const children =
    parent.kind === "page" ? scene.pages[parent.id]?.children : scene.nodes[parent.id]?.children;
  if (!children) {
    throw new Error(`Missing parent ${parent.id}`);
  }
  children.splice(Math.min(index, children.length), 0, nodeId);
}

function isLockedOnlyPatch(patch: NodePatch): boolean {
  return (
    patch.locked.kind === "set" &&
    patch.name.kind === "unchanged" &&
    patch.kind.kind === "unchanged" &&
    patch.transform.kind === "unchanged" &&
    patch.size.kind === "unchanged" &&
    patch.fills.kind === "unchanged" &&
    patch.strokes.kind === "unchanged" &&
    patch.corner.kind === "unchanged" &&
    patch.opacity.kind === "unchanged" &&
    patch.clip.kind === "unchanged" &&
    patch.layout.kind === "unchanged" &&
    patch.computed.kind === "unchanged"
  );
}

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}
