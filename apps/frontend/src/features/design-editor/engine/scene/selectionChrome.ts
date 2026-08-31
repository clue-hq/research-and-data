import type { AssetId, Diagnostic, Node, NodeId, PageId, Scene, Slot } from "./contracts";
import {
  canvasDirectEditNotice,
  containerSelectionGeometry,
  isCanvasDirectGeometryEditable,
  type SelectionRect
} from "./canvasSelection";
import {
  getNode,
  isNodeFreezableOnGesture,
  isNodeReorderableOnGesture,
  nodeDisplayName,
  pageIdForNode,
  slotsForNode
} from "./sceneQueries";
import type { Box } from "./transformerMath";

export type SelectedObjectKind =
  | "artboard"
  | "frame"
  | "group"
  | "auto_layout"
  | "text"
  | "image"
  | "shape"
  | "slot_bound"
  | "unknown";

export interface SlotBindingSummary {
  id: string;
  key: string;
  label: string;
  contentType: string;
}

export interface DiagnosticCounts {
  errors: number;
  warnings: number;
}

export interface SelectionChromeModel {
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  displayName: string | null;
  selectedObjectKind: SelectedObjectKind | null;
  baseObjectKind: Exclude<SelectedObjectKind, "slot_bound"> | null;
  isSlotBound: boolean;
  selectionBox: { box: Box; rotation: number; nodeId: NodeId } | null;
  hoverBox: { box: Box; rotation: number; nodeId: NodeId } | null;
  containerChildren: SelectionRect[];
  containerLabel: string | null;
  showHandles: boolean;
  /** Phase 4c-C: resize handles for a layout-managed-editing reorderable
   * Stack child (all 8, size-only commit) — true whenever `showHandles` is,
   * plus this one extra case. Equal to `showHandles` outside that case. */
  showResizeHandles: boolean;
  /** The rotate handle stays OFF for a managed Stack child even when its
   * resize handles are on (4c-C) — rotation isn't a solver-managed-size
   * concept. Equal to `showHandles` outside that case. */
  showRotateHandle: boolean;
  disabledReason: string | null;
  slotBindings: SlotBindingSummary[];
  slotKeys: string[];
  diagnosticCounts: DiagnosticCounts;
}

export interface SelectionChromeOptions {
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  hoverNodeId?: NodeId | null;
  diagnostics?: Diagnostic[];
  /** Phase 4c-C: advanced per-document opt-in (same flag CanvasKitCanvas
   * gates its freeze-on-first-gesture skip with). When true, a reorderable
   * managed Stack child gets resize handles (see `showResizeHandles`). */
  layoutManagedEditing?: boolean;
}

export function deriveSelectionChromeModel(scene: Scene, options: SelectionChromeOptions): SelectionChromeModel {
  const selectedNode = getNode(scene, options.selectedNodeId);
  const hoverNode = getNode(scene, options.hoverNodeId ?? null);
  const slotBindings = selectedNode ? slotBindingSummaries(slotsForNode(scene, selectedNode.id)) : [];
  const baseObjectKind = selectedNode ? selectedBaseObjectKind(selectedNode) : options.activePageId ? "artboard" : null;
  const selectedObjectKind = slotBindings.length > 0 ? "slot_bound" : baseObjectKind;
  const containerGeometry = selectedNode ? containerSelectionGeometry(scene, selectedNode.id) : null;
  const disabledReason = selectedNode ? canvasDirectEditNotice(scene, selectedNode.id) : null;
  const showHandles = selectedNode ? isCanvasDirectGeometryEditable(scene, selectedNode.id) : false;
  const managedResizable =
    Boolean(options.layoutManagedEditing) && selectedNode
      ? isNodeReorderableOnGesture(scene, selectedNode.id)
      : false;
  // Ruling C-9 (handoff-absolute freeze-on-grab): a node blocked ONLY by
  // solver ownership is grabbable — the press freezes the layout first. The
  // predicate is an explicit allow-list and already excludes locked nodes, so
  // a locked managed child stays refused end to end.
  const freezableOnGesture = selectedNode
    ? isNodeFreezableOnGesture(scene, selectedNode.id)
    : false;

  return {
    activePageId: options.activePageId,
    selectedNodeId: selectedNode?.id ?? null,
    displayName: selectedNode ? nodeDisplayName(selectedNode) : options.activePageId ? scene.pages[options.activePageId]?.name ?? null : null,
    selectedObjectKind,
    baseObjectKind,
    isSlotBound: slotBindings.length > 0,
    selectionBox: selectedNode ? selectionBoxForNode(selectedNode) : null,
    hoverBox: hoverNode ? selectionBoxForNode(hoverNode) : null,
    containerChildren: containerGeometry?.children ?? [],
    containerLabel: containerGeometry ? `${containerGeometry.label} · ${containerGeometry.children.length} inside` : null,
    showHandles,
    // The rotate handle never turns on beyond `showHandles`; resize handles
    // additionally turn on for a layout-managed-editing reorderable child, and
    // — ruling C-9 — for a node whose ONLY blocker is solver ownership. A
    // human dragging on this canvas is never refused by auto-layout: the first
    // grab freezes the document's layout (zero-motion, silent) and the same
    // press continues as a free drag, so the handles must be offered before
    // that freeze has happened. `showHandles` deliberately stays false — it is
    // "already directly editable", which this node is not yet.
    showResizeHandles: showHandles || managedResizable || freezableOnGesture,
    showRotateHandle: showHandles,
    disabledReason,
    slotBindings,
    slotKeys: slotBindings.map((slot) => slot.key),
    diagnosticCounts: selectedNode
      ? diagnosticCountsForSelectedNode(scene, selectedNode, options.diagnostics ?? [])
      : diagnosticCountsForActivePage(scene, options.activePageId, options.diagnostics ?? [])
  };
}

export function selectedBaseObjectKind(node: Node): Exclude<SelectedObjectKind, "slot_bound"> {
  switch (node.kind.kind) {
    case "frame":
      return "frame";
    case "group":
      return "group";
    case "auto_layout":
      return "auto_layout";
    case "text":
      return "text";
    case "image":
      return "image";
    case "rect":
    case "ellipse":
    case "line":
    case "vector":
      return "shape";
    case "instance":
      return "group";
    default:
      return "unknown";
  }
}

export function slotBindingSummaries(slots: Slot[]): SlotBindingSummary[] {
  return [...slots]
    .sort((a, b) => a.key.localeCompare(b.key) || a.id.localeCompare(b.id))
    .map((slot) => ({
      id: slot.id,
      key: slot.key,
      label: slot.label,
      contentType: slot.content_type
    }));
}

export function diagnosticCountsForSelectedNode(scene: Scene, node: Node, diagnostics: Diagnostic[]): DiagnosticCounts {
  const slotIds = new Set(slotsForNode(scene, node.id).map((slot) => slot.id));
  const assetIds = assetIdsForNode(node);
  return countDiagnostics(
    diagnostics.filter((diagnostic) => {
      const subject = diagnostic.subject;
      if (!subject) {
        return false;
      }
      switch (subject.kind) {
        case "node":
          return subject.id === node.id;
        case "slot":
          return slotIds.has(subject.id);
        case "asset":
          return assetIds.has(subject.id);
        case "page":
          return false;
        case "document":
          return false;
      }
    })
  );
}

export function diagnosticCountsForActivePage(
  scene: Scene,
  activePageId: PageId | null,
  diagnostics: Diagnostic[]
): DiagnosticCounts {
  if (!activePageId) {
    return { errors: 0, warnings: 0 };
  }
  return countDiagnostics(
    diagnostics.filter((diagnostic) => {
      const subject = diagnostic.subject;
      if (!subject) {
        return false;
      }
      switch (subject.kind) {
        case "page":
          return subject.id === activePageId;
        case "node":
          return pageIdForNode(scene, subject.id) === activePageId;
        case "slot": {
          const slot = scene.slots[subject.id];
          return Boolean(slot?.bound_nodes.some((nodeId) => pageIdForNode(scene, nodeId) === activePageId));
        }
        case "asset":
          return Object.values(scene.nodes).some(
            (node) => assetIdsForNode(node).has(subject.id) && pageIdForNode(scene, node.id) === activePageId
          );
        case "document":
          return false;
      }
    })
  );
}

function selectionBoxForNode(node: Node): { box: Box; rotation: number; nodeId: NodeId } | null {
  const bounds = node.computed?.layout_bounds ?? node.computed?.render_bounds ?? null;
  if (!bounds) {
    return null;
  }
  return {
    box: {
      x: bounds.x,
      y: bounds.y,
      width: bounds.width,
      height: bounds.height
    },
    rotation: node.transform.rotation,
    nodeId: node.id
  };
}

function countDiagnostics(diagnostics: Diagnostic[]): DiagnosticCounts {
  let errors = 0;
  let warnings = 0;
  for (const diagnostic of diagnostics) {
    if (diagnostic.severity === "error") {
      errors += 1;
    } else if (diagnostic.severity === "warning") {
      warnings += 1;
    }
  }
  return { errors, warnings };
}

function assetIdsForNode(node: Node): Set<AssetId> {
  const ids = new Set<AssetId>();
  if (node.source_asset_id) {
    ids.add(node.source_asset_id);
  }
  if (node.kind.kind === "image") {
    ids.add(node.kind.asset_id);
  }
  return ids;
}
