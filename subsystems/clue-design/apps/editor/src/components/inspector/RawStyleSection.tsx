"use client";

import type { BrandTokenCatalog, CornerRadii, Node, Operation, Stroke } from "@/engine/contracts";
import { nodePatch, set, updateNodeFills, updateNodeStrokes } from "@/engine/operations";
import { ColorSwatchControl } from "../ColorSwatchControl";
import { NumberField, roundForEditor } from "./fields";

/** Raw (non-token) fills, strokes, and corner radii for the selected node. */
export function RawStyleSection({
  selectedNode,
  brandTokens,
  onOperation
}: {
  selectedNode: Node;
  brandTokens?: BrandTokenCatalog | null;
  onOperation: (operation: Operation) => void;
}) {
  return (
      <section className="inspector-section">
        <div className="section-heading">Raw Style</div>
        <div className="field-grid two">
          <label className="field">
            <span>Fill Color</span>
            <ColorSwatchControl
              node={selectedNode}
              brandTokens={brandTokens}
              label="Fill color"
              onEdit={(fills) => onOperation(updateNodeFills(selectedNode, fills))}
            />
          </label>
          <label className="field">
            <span>Stroke Color</span>
            <input
              type="color"
              value={hexInputValueFromStroke(selectedNode)}
              disabled={selectedNode.locked}
              onChange={(event) =>
                onOperation(updateNodeStrokes(selectedNode, [solidStroke(selectedNode, event.target.value, selectedNode.strokes[0]?.width ?? 1)]))
              }
            />
          </label>
          <NumberField
            label="Stroke Width"
            value={selectedNode.strokes[0]?.width ?? 0}
            min={0}
            disabled={selectedNode.locked}
            onCommit={(value) =>
              onOperation(
                updateNodeStrokes(
                  selectedNode,
                  value > 0 ? [solidStroke(selectedNode, hexInputValueFromStroke(selectedNode), value)] : []
                )
              )
            }
          />
          <NumberField
            label="Radius All"
            value={uniformCornerRadius(selectedNode.corner)}
            min={0}
            disabled={selectedNode.locked}
            onCommit={(value) =>
              onOperation({
                kind: "update_node",
                node_id: selectedNode.id,
                patch: nodePatch({
                  corner: set(cornerWithAll(selectedNode.corner, value))
                })
              })
            }
          />
          <NumberField
            label="Radius TL"
            value={selectedNode.corner.top_left}
            min={0}
            disabled={selectedNode.locked}
            onCommit={(value) =>
              onOperation({
                kind: "update_node",
                node_id: selectedNode.id,
                patch: nodePatch({
                  corner: set(cornerWith(selectedNode.corner, { top_left: value }))
                })
              })
            }
          />
          <NumberField
            label="Radius TR"
            value={selectedNode.corner.top_right}
            min={0}
            disabled={selectedNode.locked}
            onCommit={(value) =>
              onOperation({
                kind: "update_node",
                node_id: selectedNode.id,
                patch: nodePatch({
                  corner: set(cornerWith(selectedNode.corner, { top_right: value }))
                })
              })
            }
          />
          <NumberField
            label="Radius BR"
            value={selectedNode.corner.bottom_right}
            min={0}
            disabled={selectedNode.locked}
            onCommit={(value) =>
              onOperation({
                kind: "update_node",
                node_id: selectedNode.id,
                patch: nodePatch({
                  corner: set(cornerWith(selectedNode.corner, { bottom_right: value }))
                })
              })
            }
          />
          <NumberField
            label="Radius BL"
            value={selectedNode.corner.bottom_left}
            min={0}
            disabled={selectedNode.locked}
            onCommit={(value) =>
              onOperation({
                kind: "update_node",
                node_id: selectedNode.id,
                patch: nodePatch({
                  corner: set(cornerWith(selectedNode.corner, { bottom_left: value }))
                })
              })
            }
          />
        </div>
        <p className="muted contract-note">
          Raw colors and radii are stored directly in the scene. Use tokens when the field should stay BrandKit-resolved.
        </p>
      </section>
  );
}

function solidStroke(node: Node, hex: string, width: number): Stroke {
  const existing = node.strokes[0];
  return {
    id: existing?.id ?? `paint_${node.id}_stroke`,
    paint: {
      kind: "solid",
      color: {
        kind: "hex",
        value: normalizeHexInput(hex)
      }
    },
    width: roundForEditor(Math.max(0, width)),
    width_token: null
  };
}

function cornerWithAll(corner: CornerRadii, value: number): CornerRadii {
  const radius = normalizeCornerRadius(value);
  return {
    top_left: radius,
    top_right: radius,
    bottom_right: radius,
    bottom_left: radius,
    token: null
  };
}

function cornerWith(corner: CornerRadii, patch: Partial<Omit<CornerRadii, "token">>): CornerRadii {
  return {
    top_left: normalizeCornerRadius(patch.top_left ?? corner.top_left),
    top_right: normalizeCornerRadius(patch.top_right ?? corner.top_right),
    bottom_right: normalizeCornerRadius(patch.bottom_right ?? corner.bottom_right),
    bottom_left: normalizeCornerRadius(patch.bottom_left ?? corner.bottom_left),
    token: null
  };
}

function uniformCornerRadius(corner: CornerRadii): number {
  const values = [corner.top_left, corner.top_right, corner.bottom_right, corner.bottom_left];
  return values.every((value) => value === values[0]) ? values[0] : 0;
}

function normalizeCornerRadius(value: number): number {
  return roundForEditor(Number.isFinite(value) ? Math.max(0, value) : 0);
}

function hexInputValueFromStroke(node: Node): string {
  const stroke = node.strokes[0];
  if (stroke?.paint.kind === "solid" && stroke.paint.color.kind === "hex") {
    return normalizeHexInput(stroke.paint.color.value);
  }
  return "#256c70";
}

function normalizeHexInput(value: string): string {
  const trimmed = value.trim();
  const sixDigit = /^#[0-9a-fA-F]{6}$/.test(trimmed) ? trimmed : null;
  const eightDigit = /^#[0-9a-fA-F]{8}$/.test(trimmed) ? trimmed.slice(0, 7) : null;
  return (sixDigit ?? eightDigit ?? "#000000").toLowerCase();
}
