import type {
  AutoLayoutNode,
  AutoLayoutProps,
  BrandKitRef,
  DocumentPatch,
  ExportProfile,
  Fill,
  LayoutAnchor,
  Medium,
  Node,
  NodeId,
  NodePatch,
  Operation,
  OverflowPolicy,
  Page,
  PageId,
  PagePatch,
  Rect,
  PageSize,
  ParentRef,
  SizeSpec,
  Slot,
  SlotId,
  SlotKey,
  Stroke,
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
    ...(patch.explicit_text_tokens !== undefined
      ? { explicit_text_tokens: patch.explicit_text_tokens }
      : {}),
    transform: patch.transform ?? unchanged(),
    size: patch.size ?? unchanged(),
    fills: patch.fills ?? unchanged(),
    strokes: patch.strokes ?? unchanged(),
    // The Rust core skips `effects` entirely when unchanged, so the wire
    // format only carries it when set (keeps pinned parity fixtures stable).
    ...(patch.effects ? { effects: patch.effects } : {}),
    corner: patch.corner ?? unchanged(),
    opacity: patch.opacity ?? unchanged(),
    opacity_token: patch.opacity_token ?? unchanged(),
    source_asset_id: patch.source_asset_id ?? unchanged(),
    asset_placement: patch.asset_placement ?? unchanged(),
    clip: patch.clip ?? unchanged(),
    layout: patch.layout ?? unchanged(),
    // Canonical edit semantics (lumen-core `build_node_modify` /
    // `node_patch_affects_render`): a render-affecting patch clears stale
    // computed geometry explicitly in the operation itself. The raw
    // operation layer applies patches verbatim — engine and server both —
    // so the builder is where invalidation belongs.
    computed: patch.computed ?? (nodePatchAffectsRender(patch) ? clear() : unchanged()),
    locked: patch.locked ?? unchanged(),
    // Phase 1 freehand: like `effects`, the Rust core skips these when
    // unchanged, so the wire format only carries them when set.
    ...(patch.position_mode ? { position_mode: patch.position_mode } : {}),
    ...(patch.absolute_box ? { absolute_box: patch.absolute_box } : {}),
    ...(patch.base_anchor ? { base_anchor: patch.base_anchor } : {})
  };
}

/** Mirror of lumen-core editing.rs `node_patch_affects_render`, pinned by
 * the gesture-conformance fixture and the cross-binding parity tests. */
function nodePatchAffectsRender(patch: Partial<NodePatch>): boolean {
  const changed = (field?: { kind: string }) =>
    field !== undefined && field.kind !== "unchanged";
  return (
    changed(patch.kind) ||
    changed(patch.transform) ||
    changed(patch.size) ||
    changed(patch.fills) ||
    changed(patch.strokes) ||
    changed(patch.effects) ||
    changed(patch.corner) ||
    changed(patch.opacity) ||
    changed(patch.opacity_token) ||
    changed(patch.source_asset_id) ||
    changed(patch.asset_placement) ||
    changed(patch.clip) ||
    changed(patch.layout) ||
    // Phase 1 freehand: pinning/unpinning or moving an absolute box moves
    // pixels (mirrors the Rust arm added in 1a).
    changed(patch.position_mode) ||
    changed(patch.absolute_box) ||
    changed(patch.base_anchor)
  );
}

/** Phase 1d freehand: move/resize a pinned node by rewriting its page-space
 * `absolute_box` — the solver treats the box as authoritative for both
 * position and size, so this IS the drag/resize commit for pinned nodes.
 * Resizes also bake the Fixed size in the same patch, keeping the
 * size-spec ↔ box invariant from detach (what a later re-attach keeps). */
export function updateNodeAbsoluteBox(node: Node, box: Rect): Operation {
  const resized =
    node.absolute_box?.width !== box.width || node.absolute_box?.height !== box.height;
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      absolute_box: set(box),
      ...(resized
        ? {
            size: set({
              width: { kind: "fixed", value: box.width },
              height: { kind: "fixed", value: box.height }
            } as SizeSpec)
          }
        : {})
    })
  };
}

/** Pinned rotate rides the transform (rotation is render-only for pinned
 * nodes; the solver ignores transform x/y while the box is authoritative). */
export function updateNodeAbsoluteBoxAndRotation(
  node: Node,
  box: Rect,
  rotation: number
): Operation {
  const base = updateNodeAbsoluteBox(node, box);
  if (base.kind !== "update_node" || node.transform.rotation === rotation) {
    return base;
  }
  return {
    ...base,
    patch: {
      ...base.patch,
      transform: set({ ...node.transform, rotation })
    }
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

export function documentPatch(patch: Partial<DocumentPatch>): DocumentPatch {
  return {
    title: patch.title ?? unchanged(),
    artifact_type: patch.artifact_type ?? unchanged(),
    medium: patch.medium ?? unchanged(),
    brand_kit: patch.brand_kit ?? unchanged()
  };
}

export function updateDocumentBrand(brandKit: BrandKitRef, medium?: Medium | null): Operation {
  return {
    kind: "update_document",
    patch: documentPatch({
      brand_kit: set(brandKit),
      medium: medium ? set(medium) : unchanged()
    })
  };
}

export function updateDocumentMedium(medium: Medium): Operation {
  return {
    kind: "update_document",
    patch: documentPatch({
      medium: set(medium)
    })
  };
}

export function updateDocumentTitle(title: string): Operation {
  return {
    kind: "update_document",
    patch: documentPatch({
      title: set(title.trim() || "Untitled design")
    })
  };
}

export function updateDocumentArtifactType(artifactType: string): Operation {
  const trimmed = artifactType.trim();
  return {
    kind: "update_document",
    patch: documentPatch({
      artifact_type: trimmed ? set(trimmed) : clear()
    })
  };
}

export function addPage(page: Page): Operation {
  return {
    kind: "add_page",
    page
  };
}

export function removePage(pageId: PageId): Operation {
  return {
    kind: "remove_page",
    page_id: pageId
  };
}

export function insertNode(parent: ParentRef, index: number, node: Node): Operation {
  return {
    kind: "insert_node",
    parent,
    index,
    node
  };
}

export function upsertExportProfile(profile: ExportProfile): Operation {
  return {
    kind: "upsert_export_profile",
    profile
  };
}

export function removeExportProfile(name: string): Operation {
  return {
    kind: "remove_export_profile",
    name
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

export function updatePageName(page: Page, name: string): Operation {
  return {
    kind: "update_page",
    page_id: page.id,
    patch: pagePatch({
      name: set(name.trim() || page.id)
    })
  };
}

export function updatePageBackground(page: Page, background: Fill[]): Operation {
  return {
    kind: "update_page",
    page_id: page.id,
    patch: pagePatch({
      background: set(background)
    })
  };
}

export function updatePageBleed(page: Page, bleed: Rect | null): Operation {
  return {
    kind: "update_page",
    page_id: page.id,
    patch: pagePatch({
      bleed: bleed ? set(bleed) : clear()
    })
  };
}

export function updatePageSafeArea(page: Page, safeArea: Rect | null): Operation {
  return {
    kind: "update_page",
    page_id: page.id,
    patch: pagePatch({
      safe_area: safeArea ? set(safeArea) : clear()
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

export function updateNodeName(node: Node, name: string): Operation {
  const trimmedName = name.trim();
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      name: trimmedName ? set(trimmedName) : clear()
    })
  };
}

export function removeNode(nodeId: NodeId): Operation {
  return {
    kind: "remove_node",
    node_id: nodeId
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

export function updateNodeFills(node: Node, fills: Fill[]): Operation {
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      fills: set(fills)
    })
  };
}

export function updateNodeStrokes(node: Node, strokes: Stroke[]): Operation {
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      strokes: set(strokes)
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

export function updateAutoLayoutNode(node: Node, patch: Partial<AutoLayoutNode>): Operation {
  if (node.kind.kind !== "auto_layout") {
    throw new Error(`Cannot update auto-layout fields on non-auto-layout node ${node.id}`);
  }
  return {
    kind: "update_node",
    node_id: node.id,
    patch: nodePatch({
      kind: set({
        ...node.kind,
        ...patch
      })
    })
  };
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
  return `slot_${stableSlotSlug(slotKey)}_${stableHash64Hex(slotKey)}`;
}

function stableSlotSlug(source: string): string {
  const slug = [...source].map((character) => (/[a-zA-Z0-9]/.test(character) ? character : "_")).join("");
  return slug || "slot";
}

function stableHash64Hex(source: string): string {
  const fnvOffset = 0xcbf29ce484222325n;
  const fnvPrime = 0x100000001b3n;
  const mask64 = 0xffffffffffffffffn;
  let hash = fnvOffset;
  for (const byte of new TextEncoder().encode(source)) {
    hash ^= BigInt(byte);
    hash = (hash * fnvPrime) & mask64;
  }
  return hash.toString(16).padStart(16, "0");
}
