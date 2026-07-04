"use client";

import { Lock, Pin, PinOff, Trash2, Unlock } from "lucide-react";
import type {
  Diagnostic,
  DiagnosticSubject,
  Node,
  NodeId,
  Operation,
  Page,
  Scene,
  Transform
} from "@/engine/contracts";
import {
  defaultLayoutProps,
  nodePatch,
  removeNode,
  set,
  updateNodeAbsoluteBox,
  updateNodeLocked,
  updateNodeName,
  updateNodeSize,
  updateNodeTransform
} from "@/engine/operations";
import { dimensionToNumber, fixedSize } from "@/engine/renderAdapter";
import {
  isNodeDirectGeometryEditable,
  isNodeLayoutManaged,
  isNodePinned,
  isNodeReorderableOnGesture,
  nodeDisplayName
} from "@/engine/sceneQueries";
import { deriveSelectionChromeModel } from "@/engine/selectionChrome";
import {
  detachToFreehandEdit,
  reattachToLayoutEdit,
  type StructuredEdit
} from "@/engine/structuredEdits";
import { InspectorDiagnosticsSection, inspectorDiagnosticsForNode } from "./diagnostics";
import { NumberField } from "./fields";
import { SelectedObjectSummary } from "./summaries";

/** The selected object's header (lock / detach / delete), summary, name,
 * scoped issues, and direct geometry fields. */
export function ObjectSection({
  scene,
  activePage,
  selectedNode,
  selectedNodeId,
  diagnostics,
  renderDiagnostics,
  onOperation,
  onStructuredEdit,
  onSelectSubject,
  layoutManagedEditing = false
}: {
  scene: Scene;
  activePage: Page | null;
  selectedNode: Node;
  selectedNodeId: NodeId | null;
  diagnostics: Diagnostic[];
  renderDiagnostics: Diagnostic[];
  onOperation: (operation: Operation) => void;
  onStructuredEdit?: (edit: StructuredEdit) => void;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
  /** Advanced per-document opt-in (4c-C): when true, a reorderable managed
   * Stack child's hint mentions the canvas drag-to-reorder/resize gestures
   * that become available instead of only pointing at Detach. */
  layoutManagedEditing?: boolean;
}) {
  const size = fixedSize(selectedNode.size);
  const layoutManaged = isNodeLayoutManaged(scene, selectedNode.id);
  const directGeometryEditable = isNodeDirectGeometryEditable(scene, selectedNode.id);
  const reorderableInManagedMode =
    layoutManagedEditing && isNodeReorderableOnGesture(scene, selectedNode.id);
  // Phase 1d freehand: a pinned node's geometry is its page-space
  // absolute_box — shown and edited directly (the solver treats the box as
  // authoritative), while transform stays the flow input for managed nodes.
  const pinned = isNodePinned(scene, selectedNode.id);
  const pinnedBox = pinned
    ? selectedNode.absolute_box ?? selectedNode.computed?.layout_bounds ?? null
    : null;
  const currentLayout = selectedNode.layout ?? defaultLayoutProps();
  const selectedDiagnostics = inspectorDiagnosticsForNode(scene, selectedNode, [...diagnostics, ...renderDiagnostics]);
  const selectionChrome = deriveSelectionChromeModel(scene, {
    activePageId: activePage?.id ?? null,
    selectedNodeId,
    diagnostics: [...diagnostics, ...renderDiagnostics]
  });
  const emitTransform = (patch: Partial<Transform>) => {
    onOperation(updateNodeTransform(selectedNode, { ...selectedNode.transform, ...patch }));
  };
  const emitPosition = (patch: { x?: number; y?: number }) => {
    if (pinnedBox) {
      onOperation(updateNodeAbsoluteBox(selectedNode, { ...pinnedBox, ...patch }));
      return;
    }
    emitTransform(patch);
  };
  const emitExtent = (patch: { width?: number; height?: number }) => {
    if (pinnedBox) {
      onOperation(updateNodeAbsoluteBox(selectedNode, { ...pinnedBox, ...patch }));
      return;
    }
    const next = { ...selectedNode.size };
    if (patch.width !== undefined) next.width = { kind: "fixed", value: patch.width };
    if (patch.height !== undefined) next.height = { kind: "fixed", value: patch.height };
    onOperation(updateNodeSize(selectedNode, next));
  };

  return (
      <section className="inspector-section">
        <div className="node-header">
          <div>
            <span className="node-kind">{selectedNode.kind.kind}</span>
            <h2>{nodeDisplayName(selectedNode)}</h2>
            <code>{selectedNode.id}</code>
          </div>
          <div className="node-header-actions">
            <button type="button" onClick={() => onOperation(updateNodeLocked(selectedNode, !selectedNode.locked))}>
              {selectedNode.locked ? <Lock aria-hidden size={15} /> : <Unlock aria-hidden size={15} />}
              {selectedNode.locked ? "Locked" : "Unlocked"}
            </button>
            {onStructuredEdit && (pinned || layoutManaged) ? (
              <button
                type="button"
                disabled={selectedNode.locked}
                onClick={() =>
                  onStructuredEdit(
                    pinned
                      ? reattachToLayoutEdit(selectedNode.id)
                      : detachToFreehandEdit(selectedNode.id)
                  )
                }
              >
                {pinned ? <PinOff aria-hidden size={15} /> : <Pin aria-hidden size={15} />}
                {pinned ? "Re-attach" : "Detach"}
              </button>
            ) : null}
            <button
              type="button"
              className="danger-button"
              disabled={selectedNode.locked}
              onClick={() => onOperation(removeNode(selectedNode.id))}
            >
              <Trash2 aria-hidden size={15} />
              Delete
            </button>
          </div>
        </div>
        <SelectedObjectSummary model={selectionChrome} locked={selectedNode.locked} layoutManaged={layoutManaged} pinned={pinned} />
        <label className="field span">
          <span>Name</span>
          <input
            value={selectedNode.name ?? ""}
            placeholder={`${selectedNode.kind.kind} ${selectedNode.id}`}
            disabled={selectedNode.locked}
            onChange={(event) => onOperation(updateNodeName(selectedNode, event.target.value))}
          />
        </label>
        <InspectorDiagnosticsSection
          title="Selected Issues"
          diagnostics={selectedDiagnostics}
          onSelectSubject={onSelectSubject}
        />
        <div className="field-grid two">
          <NumberField
            label="X"
            value={pinnedBox ? pinnedBox.x : selectedNode.transform.x}
            disabled={!directGeometryEditable}
            onCommit={(value) => emitPosition({ x: value })}
          />
          <NumberField
            label="Y"
            value={pinnedBox ? pinnedBox.y : selectedNode.transform.y}
            disabled={!directGeometryEditable}
            onCommit={(value) => emitPosition({ y: value })}
          />
          <NumberField
            label="W"
            value={pinnedBox ? pinnedBox.width : size.width}
            disabled={!directGeometryEditable}
            onCommit={(value) => emitExtent({ width: value })}
          />
          <NumberField
            label="H"
            value={pinnedBox ? pinnedBox.height : size.height}
            disabled={!directGeometryEditable}
            onCommit={(value) => emitExtent({ height: value })}
          />
          <NumberField
            label="Rotate"
            value={selectedNode.transform.rotation}
            disabled={!directGeometryEditable}
            onCommit={(value) => emitTransform({ rotation: value })}
          />
          <NumberField
            label="Opacity"
            value={selectedNode.opacity}
            step={0.05}
            min={0}
            max={1}
            disabled={selectedNode.locked}
            onCommit={(value) =>
              onOperation({
                kind: "update_node",
                node_id: selectedNode.id,
                patch: nodePatch({
                  opacity: set(value)
                })
              })
            }
          />
        </div>
        <p className="muted contract-note">
          {pinned
            ? "Pinned (freehand): this node keeps its page-space box across relayouts. Re-attach to hand it back to the layout."
            : layoutManaged
            ? reorderableInManagedMode
              ? "This node is managed by an auto-layout parent. Detach it to freehand, or use layout controls / layer reorder — in layout-managed mode you can also drag it on the canvas to reorder it and resize it directly."
              : "This node is managed by an auto-layout parent. Detach it to freehand, or use layout controls / layer reorder."
            : selectedNode.locked
              ? "This node is locked. Unlock it before moving, resizing, or rotating it."
            : `Dimensions use the active page unit. Non-fixed dimensions currently show as ${dimensionToNumber(selectedNode.size.width)}.`}
        </p>
      </section>
  );
}
