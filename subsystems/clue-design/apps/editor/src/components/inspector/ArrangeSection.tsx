"use client";

import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
  BringToFront,
  ChevronDown,
  ChevronUp,
  Group as GroupIcon,
  SendToBack,
  Ungroup as UngroupIcon
} from "lucide-react";
import { alignNodesOperations, distributeNodesOperations, type AlignMode, type DistributeAxis } from "@/engine/alignDistribute";
import type { Node, NodeId, Operation, Scene } from "@/engine/contracts";
import { canAlignNodes, canDistributeNodes, canGroupNodes, canUngroupNode, siblingArrangeInfo } from "@/engine/sceneQueries";
import {
  groupEdit,
  mintGroupId,
  moveAfterEdit,
  moveBeforeEdit,
  ungroupEdit,
  type StructuredEdit
} from "@/engine/structuredEdits";

/**
 * Arrange controls (Moda idiom): z-order (to front / forward / backward /
 * to back), group/ungroup, and align/distribute. Z-order needs no new engine
 * op — it emits `move_before`/`move_after` against computed sibling indices.
 * Group mints a fresh id client-side; the engine remains the authority on
 * every rejection (mixed parents, locked members, solver-managed stack
 * children). Align/distribute is pure editor-side geometry (Phase 4b-3): a
 * plain `UpdateNode` batch computed from each selected node's current
 * page-space box, committed through `onOperations` in one atomic batch — no
 * engine op, no StructuredEdit.
 */
export function ArrangeSection({
  scene,
  selectedNode,
  selectedNodeIds,
  onStructuredEdit,
  onOperations
}: {
  scene: Scene;
  selectedNode: Node;
  selectedNodeIds: NodeId[];
  onStructuredEdit: (edit: StructuredEdit) => void;
  onOperations?: (operations: Operation[]) => void;
}) {
  const arrangeInfo = siblingArrangeInfo(scene, selectedNode.id);
  const zOrderDisabled = selectedNode.locked || !arrangeInfo;
  const groupSelectionIds = selectedNodeIds.includes(selectedNode.id)
    ? selectedNodeIds
    : [selectedNode.id];
  const canGroup = canGroupNodes(scene, groupSelectionIds);
  const canUngroup = groupSelectionIds.length === 1 && canUngroupNode(scene, selectedNode.id);
  const canAlign = Boolean(onOperations) && canAlignNodes(scene, groupSelectionIds);
  const canDistribute = Boolean(onOperations) && canDistributeNodes(scene, groupSelectionIds);

  const emitZOrder = (edit: StructuredEdit) => onStructuredEdit(edit);

  const align = (mode: AlignMode) => {
    if (!canAlign || !onOperations) return;
    const ops = alignNodesOperations(scene, groupSelectionIds, mode);
    if (ops.length > 0) {
      onOperations(ops);
    }
  };
  const distribute = (axis: DistributeAxis) => {
    if (!canDistribute || !onOperations) return;
    const ops = distributeNodesOperations(scene, groupSelectionIds, axis);
    if (ops.length > 0) {
      onOperations(ops);
    }
  };

  const toBack = () => {
    if (!arrangeInfo || arrangeInfo.isBack) return;
    emitZOrder(moveBeforeEdit(selectedNode.id, arrangeInfo.siblings[0]));
  };
  const backward = () => {
    if (!arrangeInfo || arrangeInfo.isBack) return;
    emitZOrder(moveBeforeEdit(selectedNode.id, arrangeInfo.siblings[arrangeInfo.index - 1]));
  };
  const forward = () => {
    if (!arrangeInfo || arrangeInfo.isFront) return;
    emitZOrder(moveAfterEdit(selectedNode.id, arrangeInfo.siblings[arrangeInfo.index + 1]));
  };
  const toFront = () => {
    if (!arrangeInfo || arrangeInfo.isFront) return;
    emitZOrder(moveAfterEdit(selectedNode.id, arrangeInfo.siblings[arrangeInfo.siblings.length - 1]));
  };
  const group = () => {
    if (!canGroup) return;
    onStructuredEdit(groupEdit(groupSelectionIds, mintGroupId(scene), "Group"));
  };
  const ungroup = () => {
    if (!canUngroup) return;
    onStructuredEdit(ungroupEdit(selectedNode.id));
  };

  return (
    <section className="inspector-section">
      <div className="section-heading">Arrange</div>
      <div className="node-header-actions">
        <button
          type="button"
          disabled={zOrderDisabled || arrangeInfo?.isFront}
          title="Bring to front (⌥⌘])"
          onClick={toFront}
        >
          <BringToFront aria-hidden size={15} />
          To front
        </button>
        <button
          type="button"
          disabled={zOrderDisabled || arrangeInfo?.isFront}
          title="Bring forward (⌘])"
          onClick={forward}
        >
          <ChevronUp aria-hidden size={15} />
          Forward
        </button>
        <button
          type="button"
          disabled={zOrderDisabled || arrangeInfo?.isBack}
          title="Send backward (⌘[)"
          onClick={backward}
        >
          <ChevronDown aria-hidden size={15} />
          Backward
        </button>
        <button
          type="button"
          disabled={zOrderDisabled || arrangeInfo?.isBack}
          title="Send to back (⌥⌘[)"
          onClick={toBack}
        >
          <SendToBack aria-hidden size={15} />
          To back
        </button>
      </div>
      <div className="node-header-actions">
        <button
          type="button"
          disabled={!canGroup}
          title={
            canGroup
              ? "Group selection (⌘G)"
              : "Select 2+ unlocked siblings with the same parent (not solver-managed stack children) to group"
          }
          onClick={group}
        >
          <GroupIcon aria-hidden size={15} />
          Group
        </button>
        <button
          type="button"
          disabled={!canUngroup}
          title={
            canUngroup
              ? "Ungroup (⌘⇧G)"
              : "Select a single unlocked Frame, Group, or Auto Layout container to ungroup"
          }
          onClick={ungroup}
        >
          <UngroupIcon aria-hidden size={15} />
          Ungroup
        </button>
      </div>

      <div className="node-header-actions">
        <button
          type="button"
          className="icon-button"
          disabled={!canAlign}
          aria-label="Align left"
          title={canAlign ? "Align left" : "Select 2+ unlocked freehand nodes to align"}
          onClick={() => align("left")}
        >
          <AlignStartVertical aria-hidden size={15} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canAlign}
          aria-label="Align center horizontally"
          title={canAlign ? "Align center horizontally" : "Select 2+ unlocked freehand nodes to align"}
          onClick={() => align("center-h")}
        >
          <AlignCenterVertical aria-hidden size={15} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canAlign}
          aria-label="Align right"
          title={canAlign ? "Align right" : "Select 2+ unlocked freehand nodes to align"}
          onClick={() => align("right")}
        >
          <AlignEndVertical aria-hidden size={15} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canAlign}
          aria-label="Align top"
          title={canAlign ? "Align top" : "Select 2+ unlocked freehand nodes to align"}
          onClick={() => align("top")}
        >
          <AlignStartHorizontal aria-hidden size={15} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canAlign}
          aria-label="Align middle vertically"
          title={canAlign ? "Align middle vertically" : "Select 2+ unlocked freehand nodes to align"}
          onClick={() => align("middle-v")}
        >
          <AlignCenterHorizontal aria-hidden size={15} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canAlign}
          aria-label="Align bottom"
          title={canAlign ? "Align bottom" : "Select 2+ unlocked freehand nodes to align"}
          onClick={() => align("bottom")}
        >
          <AlignEndHorizontal aria-hidden size={15} />
        </button>
      </div>
      <div className="node-header-actions">
        <button
          type="button"
          className="icon-button"
          disabled={!canDistribute}
          aria-label="Distribute horizontally"
          title={canDistribute ? "Distribute horizontally" : "Select 3+ unlocked freehand nodes to distribute"}
          onClick={() => distribute("horizontal")}
        >
          <AlignHorizontalDistributeCenter aria-hidden size={15} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canDistribute}
          aria-label="Distribute vertically"
          title={canDistribute ? "Distribute vertically" : "Select 3+ unlocked freehand nodes to distribute"}
          onClick={() => distribute("vertical")}
        >
          <AlignVerticalDistributeCenter aria-hidden size={15} />
        </button>
      </div>
    </section>
  );
}
