"use client";

import { Lock, Type, Unlock } from "lucide-react";
import type { Node, NodeId, Operation, Scene, TextAlign, Transform } from "@/engine/contracts";
import { nodePatch, set, updateNodeLocked, updateNodeSize, updateNodeTransform, updateTextNode } from "@/engine/operations";
import { dimensionToNumber, fixedSize } from "@/engine/renderAdapter";
import { nodeDisplayName } from "@/engine/sceneQueries";
import { SlotInspector } from "./SlotInspector";

interface InspectorPanelProps {
  scene: Scene;
  selectedNode: Node | null;
  selectedNodeId: NodeId | null;
  onOperation: (operation: Operation) => void;
}

export function InspectorPanel({ scene, selectedNode, selectedNodeId, onOperation }: InspectorPanelProps) {
  if (!selectedNode) {
    return (
      <section className="inspector-section">
        <p className="muted">Select a node on the canvas.</p>
      </section>
    );
  }

  const size = fixedSize(selectedNode.size);
  const emitTransform = (patch: Partial<Transform>) => {
    onOperation(updateNodeTransform(selectedNode, { ...selectedNode.transform, ...patch }));
  };

  return (
    <>
      <section className="inspector-section">
        <div className="node-header">
          <div>
            <span className="node-kind">{selectedNode.kind.kind}</span>
            <h2>{nodeDisplayName(selectedNode)}</h2>
            <code>{selectedNode.id}</code>
          </div>
          <button type="button" onClick={() => onOperation(updateNodeLocked(selectedNode, !selectedNode.locked))}>
            {selectedNode.locked ? <Lock aria-hidden size={15} /> : <Unlock aria-hidden size={15} />}
            {selectedNode.locked ? "Locked" : "Unlocked"}
          </button>
        </div>
        <div className="field-grid two">
          <NumberField label="X" value={selectedNode.transform.x} onCommit={(value) => emitTransform({ x: value })} />
          <NumberField label="Y" value={selectedNode.transform.y} onCommit={(value) => emitTransform({ y: value })} />
          <NumberField
            label="W"
            value={size.width}
            onCommit={(value) =>
              onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, width: { kind: "fixed", value } }))
            }
          />
          <NumberField
            label="H"
            value={size.height}
            onCommit={(value) =>
              onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, height: { kind: "fixed", value } }))
            }
          />
          <NumberField
            label="Rotate"
            value={selectedNode.transform.rotation}
            onCommit={(value) => emitTransform({ rotation: value })}
          />
          <NumberField
            label="Opacity"
            value={selectedNode.opacity}
            step={0.05}
            min={0}
            max={1}
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
          Dimensions use the active page unit. Non-fixed dimensions currently show as {dimensionToNumber(selectedNode.size.width)}.
        </p>
      </section>

      {selectedNode.kind.kind === "text" ? (
        <section className="inspector-section">
          <div className="section-heading">
            <Type aria-hidden size={15} />
            Text
          </div>
          <label className="field span">
            <span>Content</span>
            <textarea
              value={selectedNode.kind.content}
              rows={4}
              disabled={selectedNode.locked}
              onChange={(event) => onOperation(updateTextNode(selectedNode, { content: event.target.value }))}
            />
          </label>
          <div className="field-grid two">
            <label className="field">
              <span>Family</span>
              <input
                value={selectedNode.kind.font_family}
                disabled={selectedNode.locked}
                onChange={(event) => onOperation(updateTextNode(selectedNode, { font_family: event.target.value }))}
              />
            </label>
            <NumberField
              label="Size"
              value={selectedNode.kind.font_size}
              min={1}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { font_size: value }))}
            />
            <NumberField
              label="Weight"
              value={selectedNode.kind.font_weight}
              min={100}
              max={900}
              step={100}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { font_weight: Math.round(value) }))}
            />
            <label className="field">
              <span>Align</span>
              <select
                value={selectedNode.kind.align}
                disabled={selectedNode.locked}
                onChange={(event) =>
                  onOperation(
                    updateTextNode(selectedNode, {
                      align: event.target.value as TextAlign
                    })
                  )
                }
              >
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
                <option value="justify">Justify</option>
              </select>
            </label>
          </div>
        </section>
      ) : null}

      <SlotInspector scene={scene} selectedNode={selectedNode} selectedNodeId={selectedNodeId} onOperation={onOperation} />
    </>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onCommit
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onCommit: (value: number) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) {
            onCommit(next);
          }
        }}
      />
    </label>
  );
}
