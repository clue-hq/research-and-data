import type {
  AssetPlacement,
  AssetKind,
  ContentType,
  DocumentPatch,
  FieldPatch,
  Node,
  NodePatch,
  Operation,
  OptionalFieldPatch,
  PagePatch,
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
    case "add_page": {
      if (scene.pages[operation.page.id]) {
        throw new Error(`Page ${operation.page.id} already exists`);
      }
      scene.pages[operation.page.id] = operation.page;
      return;
    }
    case "remove_page": {
      const page = scene.pages[operation.page_id];
      if (!page) {
        throw new Error(`Missing page ${operation.page_id}`);
      }
      delete scene.pages[operation.page_id];
      for (const nodeId of page.children) {
        removeNodeRecursive(scene, nodeId);
      }
      return;
    }
    case "update_document": {
      applyDocumentPatch(scene, operation.patch);
      if (documentPatchInvalidatesComputed(operation.patch)) {
        clearAllComputed(scene);
      }
      return;
    }
    case "update_page": {
      const page = scene.pages[operation.page_id];
      if (!page) {
        throw new Error(`Missing page ${operation.page_id}`);
      }
      applyPagePatch(page, operation.patch);
      if (pagePatchInvalidatesComputed(operation.patch)) {
        clearComputedForPage(scene, operation.page_id);
      }
      return;
    }
    case "insert_node": {
      if (scene.nodes[operation.node.id]) {
        throw new Error(`Node ${operation.node.id} already exists`);
      }
      if (operation.node.children.length > 0) {
        throw new Error(`Inserted node ${operation.node.id} must not carry pre-attached children`);
      }
      validateInsertDestination(scene, operation.parent, operation.index);
      scene.nodes[operation.node.id] = operation.node;
      insertIntoParent(scene, operation.parent, operation.node.id, operation.index);
      clearAllComputed(scene);
      return;
    }
    case "update_node": {
      const node = getNode(scene, operation.node_id);
      if (node.locked && !isLockedOnlyPatch(operation.patch)) {
        throw new Error(`Node ${node.id} is locked`);
      }
      const invalidateComputed = nodePatchInvalidatesComputed(operation.patch);
      applyNodePatch(node, operation.patch);
      if (invalidateComputed) {
        clearComputedForNodePage(scene, node.id);
      }
      return;
    }
    case "remove_node": {
      getNode(scene, operation.node_id);
      detachFromCurrentParent(scene, operation.node_id);
      removeNodeRecursive(scene, operation.node_id);
      return;
    }
    case "move_node": {
      const node = getNode(scene, operation.node_id);
      if (node.locked) {
        throw new Error(`Node ${node.id} is locked`);
      }
      validateMoveDestination(scene, operation.node_id, operation.new_parent, operation.index);
      detachFromCurrentParent(scene, operation.node_id);
      insertIntoParent(scene, operation.new_parent, operation.node_id, operation.index);
      clearAllComputed(scene);
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
    case "upsert_asset": {
      assetRegistry(scene)[operation.asset.id] = operation.asset;
      return;
    }
    case "remove_asset": {
      const reference = assetReference(scene, operation.asset_id);
      if (reference) {
        throw new Error(`Cannot remove asset ${operation.asset_id} while referenced by ${reference}`);
      }
      delete assetRegistry(scene)[operation.asset_id];
      return;
    }
    case "place_asset_in_node": {
      placeAssetInNode(scene, operation.node_id, operation.asset_id, operation.placement);
      clearComputedForNodePage(scene, operation.node_id);
      return;
    }
    case "place_asset_in_slot": {
      const slot = scene.slots[operation.slot_id];
      if (!slot) {
        throw new Error(`Missing slot ${operation.slot_id}`);
      }
      const asset = assetRegistry(scene)[operation.asset_id];
      if (!asset) {
        throw new Error(`Missing asset ${operation.asset_id}`);
      }
      if (!slotAcceptsAssetKind(slot.content_type, asset.kind)) {
        throw new Error(
          `Asset ${operation.asset_id} with kind ${asset.kind} is not compatible with ${slot.content_type} slot ${slot.key}`
        );
      }
      if (slot.content_type === "logo" && !isLogoCompatible(asset.kind)) {
        throw new Error(`Asset ${operation.asset_id} is not compatible with logo slot ${slot.key}`);
      }
      if (slot.bound_nodes.length === 0) {
        throw new Error(`Slot ${operation.slot_id} has no bound nodes`);
      }
      for (const nodeId of slot.bound_nodes) {
        placeAssetInNode(scene, nodeId, operation.asset_id, operation.placement);
        clearComputedForNodePage(scene, nodeId);
      }
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
    case "upsert_export_profile": {
      const index = scene.export_profiles.findIndex((profile) => profile.name === operation.profile.name);
      if (index >= 0) {
        scene.export_profiles[index] = operation.profile;
      } else {
        scene.export_profiles.push(operation.profile);
      }
      return;
    }
    case "remove_export_profile": {
      scene.export_profiles = scene.export_profiles.filter((profile) => profile.name !== operation.name);
      return;
    }
  }
}

function applyDocumentPatch(scene: Scene, patch: DocumentPatch): void {
  applyFieldPatch(scene.meta, "title", patch.title);
  applyOptionalPatch(scene.meta, "artifact_type", patch.artifact_type);
  applyOptionalPatch(scene.meta, "medium", patch.medium);
  applyOptionalPatch(scene.meta, "brand_kit", patch.brand_kit);
}

function applyPagePatch(page: Scene["pages"][string], patch: PagePatch): void {
  applyFieldPatch(page, "name", patch.name);
  applyFieldPatch(page, "size", patch.size);
  applyOptionalPatch(page, "bleed", patch.bleed);
  applyOptionalPatch(page, "safe_area", patch.safe_area);
  applyFieldPatch(page, "background", patch.background);
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
  applyOptionalPatch(node, "opacity_token", patch.opacity_token);
  applyOptionalPatch(node, "source_asset_id", patch.source_asset_id);
  applyOptionalPatch(node, "asset_placement", patch.asset_placement);
  applyFieldPatch(node, "clip", patch.clip);
  applyOptionalPatch(node, "layout", patch.layout);
  applyOptionalPatch(node, "computed", patch.computed);
  applyFieldPatch(node, "locked", patch.locked);
}

function assetRegistry(scene: Scene): Scene["assets"] {
  scene.assets ??= {};
  return scene.assets;
}

function placeAssetInNode(
  scene: Scene,
  nodeId: string,
  assetId: string,
  placement: AssetPlacement
): void {
  const asset = assetRegistry(scene)[assetId];
  if (!asset) {
    throw new Error(`Missing asset ${assetId}`);
  }
  const node = getNode(scene, nodeId);

  if (asset.kind === "font") {
    if (node.kind.kind !== "text") {
      throw new Error(`Font asset ${assetId} can only be placed into text nodes`);
    }
    node.source_asset_id = assetId;
    node.asset_placement = placement;
    return;
  }

  if (asset.kind !== "raster_image" && asset.kind !== "logo" && asset.kind !== "vector") {
    throw new Error(`Asset ${assetId} cannot be placed into a scene node`);
  }
  if (node.children.length > 0) {
    throw new Error(`Node ${node.id} cannot become an asset leaf while it still has children`);
  }

  if (asset.kind === "vector" && asset.vector?.path_data) {
    node.kind = {
      kind: "vector",
      path_data: asset.vector.path_data
    };
  } else {
    node.kind = {
      kind: "image",
      asset_id: assetId,
      alt: placement.alt_text ?? asset.label
    };
  }
  node.source_asset_id = assetId;
  node.asset_placement = placement;
}

function assetReference(scene: Scene, assetId: string): string | null {
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind === "image" && node.kind.asset_id === assetId) {
      return `image node ${node.id}`;
    }
    if (node.source_asset_id === assetId) {
      return `node ${node.id} source_asset_id`;
    }
  }
  return null;
}

function slotAcceptsAssetKind(contentType: ContentType, assetKind: AssetKind): boolean {
  switch (contentType) {
    case "image":
    case "logo":
      return assetKind === "raster_image" || assetKind === "vector" || assetKind === "logo";
    case "text_short":
    case "text_long":
    case "rich_text_limited":
      return assetKind === "font";
    default:
      return false;
  }
}

function isLogoCompatible(assetKind: AssetKind): boolean {
  return assetKind === "logo" || assetKind === "vector" || assetKind === "raster_image";
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

function validateMoveDestination(scene: Scene, nodeId: string, parent: ParentRef, index: number): void {
  if (!Number.isInteger(index) || index < 0) {
    throw new Error(`Invalid insertion index ${index}`);
  }

  const targetChildren = parent.kind === "page" ? scene.pages[parent.id]?.children : scene.nodes[parent.id]?.children;
  if (!targetChildren) {
    throw new Error(`Missing parent ${parent.id}`);
  }
  if (index > targetChildren.length) {
    throw new Error(`Insertion index ${index} is out of bounds for parent ${parent.id}`);
  }

  if (parent.kind === "page") {
    return;
  }

  const parentNode = getNode(scene, parent.id);
  if (parentNode.locked) {
    throw new Error(`Parent node ${parentNode.id} is locked`);
  }
  if (parent.id === nodeId || nodeContainsNode(scene, nodeId, parent.id, new Set())) {
    throw new Error(`Cannot move node ${nodeId} into itself or its descendant ${parent.id}`);
  }
  if (!canNodeHaveChildren(parentNode)) {
    throw new Error(`Node ${parentNode.id} cannot contain children`);
  }
}

function validateInsertDestination(scene: Scene, parent: ParentRef, index: number): void {
  if (!Number.isInteger(index) || index < 0) {
    throw new Error(`Invalid insertion index ${index}`);
  }

  const targetChildren = parent.kind === "page" ? scene.pages[parent.id]?.children : scene.nodes[parent.id]?.children;
  if (!targetChildren) {
    throw new Error(`Missing parent ${parent.id}`);
  }
  if (index > targetChildren.length) {
    throw new Error(`Insertion index ${index} is out of bounds for parent ${parent.id}`);
  }

  if (parent.kind === "page") {
    return;
  }

  const parentNode = getNode(scene, parent.id);
  if (parentNode.locked) {
    throw new Error(`Parent node ${parentNode.id} is locked`);
  }
  if (!canNodeHaveChildren(parentNode)) {
    throw new Error(`Node ${parentNode.id} cannot contain children`);
  }
}

function canNodeHaveChildren(node: Node): boolean {
  return node.kind.kind === "frame" || node.kind.kind === "group" || node.kind.kind === "auto_layout";
}

function nodeContainsNode(scene: Scene, rootNodeId: string, targetNodeId: string, seen: Set<string>): boolean {
  if (seen.has(rootNodeId)) {
    return false;
  }
  seen.add(rootNodeId);
  const root = scene.nodes[rootNodeId];
  if (!root) {
    return false;
  }
  for (const childId of root.children) {
    if (childId === targetNodeId || nodeContainsNode(scene, childId, targetNodeId, seen)) {
      return true;
    }
  }
  return false;
}

function removeNodeRecursive(scene: Scene, nodeId: string): void {
  const node = scene.nodes[nodeId];
  if (!node) {
    return;
  }
  delete scene.nodes[nodeId];
  for (const childId of node.children) {
    removeNodeRecursive(scene, childId);
  }
  for (const slot of Object.values(scene.slots)) {
    slot.bound_nodes = slot.bound_nodes.filter((boundNodeId) => boundNodeId !== nodeId);
  }
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
    patch.opacity_token.kind === "unchanged" &&
    patch.source_asset_id.kind === "unchanged" &&
    patch.asset_placement.kind === "unchanged" &&
    patch.clip.kind === "unchanged" &&
    patch.layout.kind === "unchanged" &&
    patch.computed.kind === "unchanged"
  );
}

function documentPatchInvalidatesComputed(patch: DocumentPatch): boolean {
  return patch.brand_kit.kind !== "unchanged";
}

function pagePatchInvalidatesComputed(patch: PagePatch): boolean {
  return patch.size.kind !== "unchanged";
}

function nodePatchInvalidatesComputed(patch: NodePatch): boolean {
  if (patch.computed.kind !== "unchanged") {
    return false;
  }
  return (
    patch.kind.kind !== "unchanged" ||
    patch.transform.kind !== "unchanged" ||
    patch.size.kind !== "unchanged" ||
    patch.strokes.kind !== "unchanged" ||
    patch.layout.kind !== "unchanged"
  );
}

function clearComputedForNodePage(scene: Scene, nodeId: string): void {
  const pageId = pageIdContainingNode(scene, nodeId);
  if (pageId) {
    clearComputedForPage(scene, pageId);
    return;
  }
  clearComputedForNodeSubtree(scene, nodeId);
}

function clearComputedForPage(scene: Scene, pageId: string): void {
  const page = scene.pages[pageId];
  if (!page) {
    return;
  }
  for (const nodeId of page.children) {
    clearComputedForNodeSubtree(scene, nodeId);
  }
}

function clearComputedForNodeSubtree(scene: Scene, nodeId: string): void {
  const node = scene.nodes[nodeId];
  if (!node) {
    return;
  }
  node.computed = null;
  for (const childId of node.children) {
    clearComputedForNodeSubtree(scene, childId);
  }
}

function clearAllComputed(scene: Scene): void {
  for (const node of Object.values(scene.nodes)) {
    node.computed = null;
  }
}

function pageIdContainingNode(scene: Scene, nodeId: string): string | null {
  for (const page of Object.values(scene.pages)) {
    if (pageContainsNode(scene, page.children, nodeId, new Set())) {
      return page.id;
    }
  }
  return null;
}

function pageContainsNode(scene: Scene, children: string[], targetNodeId: string, seen: Set<string>): boolean {
  for (const childId of children) {
    if (childId === targetNodeId) {
      return true;
    }
    if (seen.has(childId)) {
      continue;
    }
    seen.add(childId);
    const child = scene.nodes[childId];
    if (child && pageContainsNode(scene, child.children, targetNodeId, seen)) {
      return true;
    }
  }
  return false;
}

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}
