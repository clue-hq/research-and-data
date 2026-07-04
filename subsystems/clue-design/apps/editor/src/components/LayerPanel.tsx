"use client";

import { useEffect, useRef } from "react";
import { ArrowDown, ArrowUp, Layers3 } from "lucide-react";
import type { Node, NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import { moveNodeToParent } from "@/engine/operations";
import { nodeDisplayName, parentInfoForNode } from "@/engine/sceneQueries";

interface LayerPanelProps {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  /** Full multi-selection set (shift/Cmd+click); highlights every member. */
  selectedNodeIds?: NodeId[];
  onSelectNode: (nodeId: NodeId, additive?: boolean) => void;
  onOperation: (operation: Operation) => void;
}

export function LayerPanel({
  scene,
  activePageId,
  selectedNodeId,
  selectedNodeIds,
  onSelectNode,
  onOperation
}: LayerPanelProps) {
  const selectedSet = selectedNodeIds ?? (selectedNodeId ? [selectedNodeId] : []);
  const page = activePageId ? scene.pages[activePageId] : null;
  return (
    <section className="layer-panel" aria-label="Layers">
      <div className="panel-title">
        <Layers3 aria-hidden size={16} />
        Layers
      </div>
      {!page ? (
        <p className="muted">Select a page to inspect layers.</p>
      ) : page.children.length === 0 ? (
        <p className="muted">This page has no nodes.</p>
      ) : (
        <div className="layer-list">
          {page.children.map((nodeId) => (
            <LayerRow
              key={nodeId}
              scene={scene}
              nodeId={nodeId}
              depth={0}
              selectedNodeId={selectedNodeId}
              selectedSet={selectedSet}
              onSelectNode={onSelectNode}
              onOperation={onOperation}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function LayerRow({
  scene,
  nodeId,
  depth,
  selectedNodeId,
  selectedSet,
  onSelectNode,
  onOperation
}: {
  scene: Scene;
  nodeId: NodeId;
  depth: number;
  selectedNodeId: NodeId | null;
  selectedSet: NodeId[];
  onSelectNode: (nodeId: NodeId, additive?: boolean) => void;
  onOperation: (operation: Operation) => void;
}) {
  const node = scene.nodes[nodeId];
  if (!node) {
    return null;
  }

  const parentInfo = parentInfoForNode(scene, node.id);
  const parentNode = parentInfo?.parent.kind === "node" ? scene.nodes[parentInfo.parent.id] ?? null : null;
  const reorderBlocked = node.locked || Boolean(parentNode?.locked);
  const canMoveUp = parentInfo && !reorderBlocked ? parentInfo.index > 0 : false;
  const canMoveDown = parentInfo && !reorderBlocked ? parentInfo.index < parentInfo.siblings.length - 1 : false;
  const name = nodeDisplayName(node);
  const detail = layerDetailLabel(node, parentNode);
  // Every selected node (primary or secondary) shows the active row highlight;
  // scroll-into-view still tracks the primary only.
  const selected = selectedSet.includes(node.id);
  const isPrimary = selectedNodeId === node.id;
  const rowRef = useRef<HTMLDivElement | null>(null);
  // Canvas→panel sync: when selection lands on this (possibly deeply nested)
  // row — e.g. the user clicked the node on the canvas — scroll it into view
  // so the highlighted layer is never hidden below the fold. Guarded for
  // jsdom, where scrollIntoView is not implemented.
  useEffect(() => {
    if (isPrimary) {
      rowRef.current?.scrollIntoView?.({ block: "nearest" });
    }
  }, [isPrimary]);
  return (
    <div className="layer-row-group">
      <div
        ref={rowRef}
        className={selected ? "layer-row active" : "layer-row"}
        style={{ paddingLeft: 8 + depth * 12 }}
      >
        <button
          type="button"
          className="layer-select"
          aria-label={`Select layer ${name}`}
          onClick={(event) =>
            onSelectNode(node.id, event.shiftKey || event.metaKey || event.ctrlKey)
          }
        >
          <span>{name}</span>
          <small>{detail}</small>
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canMoveUp}
          aria-label={reorderBlocked ? `${name} cannot move up` : `Move ${name} up`}
          title={reorderBlocked ? reorderBlockedReason(node, parentNode) : `Move ${name} up`}
          onClick={() => {
            if (parentInfo && !reorderBlocked) {
              onOperation(moveNodeToParent(node.id, parentInfo.parent, parentInfo.index - 1));
            }
          }}
        >
          <ArrowUp aria-hidden size={13} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!canMoveDown}
          aria-label={reorderBlocked ? `${name} cannot move down` : `Move ${name} down`}
          title={reorderBlocked ? reorderBlockedReason(node, parentNode) : `Move ${name} down`}
          onClick={() => {
            if (parentInfo && !reorderBlocked) {
              onOperation(moveNodeToParent(node.id, parentInfo.parent, parentInfo.index + 1));
            }
          }}
        >
          <ArrowDown aria-hidden size={13} />
        </button>
      </div>
      {node.children.map((childId) => (
        <LayerRow
          key={childId}
          scene={scene}
          nodeId={childId}
          depth={depth + 1}
          selectedNodeId={selectedNodeId}
          selectedSet={selectedSet}
          onSelectNode={onSelectNode}
          onOperation={onOperation}
        />
      ))}
    </div>
  );
}

function layerDetailLabel(node: Node, parentNode: Node | null): string {
  const tags = [layerKindLabel(node)];
  if (parentNode?.kind.kind === "auto_layout") {
    tags.push("layout order");
  }
  if (node.locked) {
    tags.push("locked");
  } else if (parentNode?.locked) {
    tags.push("parent locked");
  }
  return tags.join(" · ");
}

function layerKindLabel(node: Node): string {
  return node.kind.kind === "auto_layout" ? "auto layout" : node.kind.kind;
}

function reorderBlockedReason(node: Node, parentNode: Node | null): string {
  if (node.locked) {
    return "Unlock this layer before reordering it.";
  }
  if (parentNode?.locked) {
    return "Unlock the parent layer before reordering its children.";
  }
  return "This layer cannot be reordered.";
}
