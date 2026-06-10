import type {
  AutoLayoutProps,
  LayoutAnchor,
  Node,
  NodeId,
  NodePatch,
  Operation,
  OverflowPolicy,
  Page,
  PagePatch,
  PageSize,
  ParentRef,
  SizeSpec,
  Slot,
  SlotId,
  SlotKey,
  TextNode,
  Transform
} from "./contracts";

export function set<T>(value: T) {
  return { kind: "set" as const, value };
}

export function unchanged() {
  return { kind: "unchanged" as const };
}

export function clear() {
  return { kind: "clear" as const };
}

export function nodePatch(patch: Partial<NodePatch>): NodePatch {
  return {
    name: patch.name ?? unchanged(),
    kind: patch.kind ?? unchanged(),
    transform: patch.transform ?? unchanged(),
    size: patch.size ?? unchanged(),
    fills: patch.fills ?? unchanged(),
    strokes: patch.strokes ?? unchanged(),
    corner: patch.corner ?? unchanged(),
    opacity: patch.opacity ?? unchanged(),
    opacity_token: patch.opacity_token ?? unchanged(),
    source_asset_id: patch.source_asset_id ?? unchanged(),
    asset_placement: patch.asset_placement ?? unchanged(),
    clip: patch.clip ?? unchanged(),
    layout: patch.layout ?? unchanged(),
    computed: patch.computed ?? unchanged(),
    locked: patch.locked ?? unchanged()
  };
}

export function pagePatch(patch: Partial<PagePatch>): PagePatch {
  return {
    name: patch.name ?? unchanged(),
    size: patch.size ?? unchanged(),
    bleed: patch.bleed ?? unchanged(),
    safe_area: patch.safe_area ?? unchanged(),
    background: patch.background ?? unchanged()
  };
}

export function updatePageSize(page: Page, size: PageSize): Operation {
  return {
    kind: "update_page",
    page_id: page.id,
    patch: pagePatch({
      size: set(size)
    })
  };
}

export function updateNodeTransform(node: Node, transform: Transform): Operation {
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      transform: set(transform)
    })
  };
}

export function updateNodeSize(node: Node, size: SizeSpec): Operation {
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      size: set(size)
    })
  };
}

export function updateNodeTransformAndSize(node: Node, transform: Transform, size: SizeSpec): Operation {
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      transform: set(transform),
      size: set(size)
    })
  };
}

export function updateNodeLayout(node: Node, layout: AutoLayoutProps | null): Operation {
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      layout: layout ? set(layout) : clear()
    })
  };
}

export function updateAutoLayoutAlignment(node: Node, alignX: LayoutAnchor, alignY: LayoutAnchor): Operation {
  const layout = node.layout ?? defaultLayoutProps();
  return updateNodeLayout(node, {
    ...layout,
    align_x: alignX,
    align_y: alignY
  });
}

export function updateTextNode(node: Node, text: Partial<TextNode>): Operation {
  if (node.kind.kind !== "text") {
    throw new Error(`Cannot update text fields on non-text node ${node.id}`);
  }
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      kind: set({
        ...node.kind,
        ...text
      })
    })
  };
}

export function moveNodeToParent(nodeId: NodeId, newParent: ParentRef, index: number): Operation {
  return {
    kind: "move_node",
    node_id: nodeId,
    new_parent: newParent,
    index
  };
}

export function updateNodeLocked(node: Node, locked: boolean): Operation {
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      locked: set(locked)
    })
  };
}

export function fixedSize(width: number, height: number): SizeSpec {
  return {
    width: {
      kind: "fixed",
      value: width
    },
    height: {
      kind: "fixed",
      value: height
    }
  };
}

export function defaultLayoutProps(): AutoLayoutProps {
  return {
    gap: 0,
    padding: [0, 0, 0, 0],
    grow: 0,
    align_x: "start",
    align_y: "start"
  };
}

export function defaultTextSlot(
  nodeId: NodeId,
  slotKey: SlotKey,
  label: string,
  placeholder: string | null,
  overflow: OverflowPolicy = {
    kind: "error"
  }
): Slot {
  return {
    id: slotIdFromKey(slotKey),
    key: slotKey,
    label,
    content_type: "text_short",
    scope: {
      kind: "document"
    },
    bound_nodes: [nodeId],
    required: true,
    placeholder,
    overflow,
    formatting: {
      max_length: null,
      allowed_pattern: null,
      preserve_case: true
    },
    cardinality: {
      min_items: 1,
      max_items: 1
    },
    conditional: null,
    repeater: null,
    validation: {
      samples: [],
      worst_case: null,
      max_length: null
    },
    image_policy: null,
    editability: "template_and_instance",
    binding_hints: [
      {
        source_path: slotKey,
        confidence: 1
      }
    ]
  };
}

export function upsertSlot(slot: Slot): Operation {
  return {
    kind: "upsert_slot",
    slot
  };
}

export function bindNodeToSlot(slotId: SlotId, nodeId: NodeId): Operation {
  return {
    kind: "bind_node_to_slot",
    slot_id: slotId,
    node_id: nodeId
  };
}

export function unbindNodeFromSlot(slotId: SlotId, nodeId: NodeId): Operation {
  return {
    kind: "unbind_node_from_slot",
    slot_id: slotId,
    node_id: nodeId
  };
}

export function removeSlot(slotId: SlotId): Operation {
  return {
    kind: "remove_slot",
    slot_id: slotId
  };
}

export function slotIdFromKey(slotKey: SlotKey): SlotId {
  return `slot_${slotKey.replaceAll(".", "_").replaceAll("-", "_")}`;
}
