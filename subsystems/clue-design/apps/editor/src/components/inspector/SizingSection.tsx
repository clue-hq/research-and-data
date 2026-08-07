"use client";

import type { Node, Operation } from "@/engine/contracts";
import { updateNodeSize } from "@/engine/operations";
import { DimensionModeSelect, NumberField } from "./fields";

/** Canonical sizing modes (fixed / hug / fill) for the selected node. */
export function SizingSection({
  selectedNode,
  onOperation
}: {
  selectedNode: Node;
  onOperation: (operation: Operation) => void;
}) {
  return (
      <section className="inspector-section">
        <div className="section-heading">Sizing</div>
        <div className="field-grid">
          <DimensionModeSelect
            label="Width mode"
            inline
            dimension={selectedNode.size.width}
            disabled={selectedNode.locked}
            onChange={(dimension) => onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, width: dimension }))}
          />
          <DimensionModeSelect
            label="Height mode"
            inline
            dimension={selectedNode.size.height}
            disabled={selectedNode.locked}
            onChange={(dimension) => onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, height: dimension }))}
          />
          {selectedNode.size.width.kind === "fixed" ? (
            <NumberField
              label="Width fixed"
              inline
              value={selectedNode.size.width.value}
              min={1}
              disabled={selectedNode.locked}
              onCommit={(value) =>
                onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, width: { kind: "fixed", value } }))
              }
            />
          ) : null}
          {selectedNode.size.height.kind === "fixed" ? (
            <NumberField
              label="Height fixed"
              inline
              value={selectedNode.size.height.value}
              min={1}
              disabled={selectedNode.locked}
              onCommit={(value) =>
                onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, height: { kind: "fixed", value } }))
              }
            />
          ) : null}
          {selectedNode.size.width.kind === "fill" ? (
            <NumberField
              label="Width fill weight"
              inline
              value={selectedNode.size.width.value.weight}
              min={0.1}
              step={0.1}
              disabled={selectedNode.locked}
              onCommit={(weight) =>
                onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, width: { kind: "fill", value: { weight } } }))
              }
            />
          ) : null}
          {selectedNode.size.height.kind === "fill" ? (
            <NumberField
              label="Height fill weight"
              inline
              value={selectedNode.size.height.value.weight}
              min={0.1}
              step={0.1}
              disabled={selectedNode.locked}
              onCommit={(weight) =>
                onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, height: { kind: "fill", value: { weight } } }))
              }
            />
          ) : null}
        </div>
        <p className="muted contract-note">
          Sizing modes are canonical layout inputs. Use fixed for explicit dimensions, hug for content-sized nodes, and fill for
          auto-layout distribution; layout-managed children can change sizing mode even when their direct X/Y geometry is locked.
        </p>
      </section>
  );
}
