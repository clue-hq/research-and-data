"use client";

import type {
  AutoLayoutNode,
  BrandTokenCatalog,
  LayoutAnchor,
  Node,
  Operation
} from "@/engine/contracts";
import {
  defaultLayoutProps,
  updateAutoLayoutAlignment,
  updateAutoLayoutNode,
  updateNodeLayout
} from "@/engine/operations";
import { NumberField, TokenSelect } from "./fields";

/** Container auto-layout controls (direction, wrap, gap, padding,
 * alignment) plus their spacing-token bindings. */
export function AutoLayoutSection({
  selectedNode,
  brandTokens,
  onOperation
}: {
  selectedNode: Node;
  brandTokens?: BrandTokenCatalog | null;
  onOperation: (operation: Operation) => void;
}) {
  const currentLayout = selectedNode.layout ?? defaultLayoutProps();
  return (
        <section className="inspector-section">
          <div className="section-heading">Auto Layout</div>
          <div className="field-grid two">
            {selectedNode.kind.kind === "auto_layout" ? (
              <>
                <label className="field">
                  <span>Direction</span>
                  <select
                    value={selectedNode.kind.direction}
                    disabled={selectedNode.locked}
                    onChange={(event) =>
                      onOperation(updateAutoLayoutNode(selectedNode, { direction: event.target.value as AutoLayoutNode["direction"] }))
                    }
                  >
                    <option value="row">Row</option>
                    <option value="column">Column</option>
                  </select>
                </label>
                <label className="field">
                  <span>Wrap</span>
                  <select
                    value={selectedNode.kind.wrap ? "true" : "false"}
                    disabled={selectedNode.locked}
                    onChange={(event) => onOperation(updateAutoLayoutNode(selectedNode, { wrap: event.target.value === "true" }))}
                  >
                    <option value="false">No wrap</option>
                    <option value="true">Wrap</option>
                  </select>
                </label>
              </>
            ) : null}
            <NumberField
              label="Gap"
              value={currentLayout.gap}
              min={0}
              disabled={selectedNode.locked}
              onCommit={(value) => {
                onOperation(updateNodeLayout(selectedNode, { ...currentLayout, gap: value }));
              }}
            />
            <NumberField
              label="Grow"
              value={currentLayout.grow}
              min={0}
              disabled={selectedNode.locked}
              onCommit={(value) => {
                onOperation(updateNodeLayout(selectedNode, { ...currentLayout, grow: value }));
              }}
            />
            {(["Pad T", "Pad R", "Pad B", "Pad L"] as const).map((label, index) => (
              <NumberField
                key={label}
                label={label}
                value={currentLayout.padding[index]}
                min={0}
                disabled={selectedNode.locked}
                onCommit={(value) =>
                  onOperation(updateNodeLayout(selectedNode, { ...currentLayout, padding: paddingWith(currentLayout.padding, index, value) }))
                }
              />
            ))}
            <label className="field">
              <span>Align X</span>
              <select
                value={currentLayout.align_x ?? "start"}
                disabled={selectedNode.locked}
                onChange={(event) => {
                  onOperation(updateAutoLayoutAlignment(selectedNode, event.target.value as LayoutAnchor, currentLayout.align_y ?? "start"));
                }}
              >
                {layoutAnchorOptions.map((anchor) => (
                  <option key={anchor} value={anchor}>
                    {anchorLabel(anchor)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Align Y</span>
              <select
                value={currentLayout.align_y ?? "start"}
                disabled={selectedNode.locked}
                onChange={(event) => {
                  onOperation(updateAutoLayoutAlignment(selectedNode, currentLayout.align_x ?? "start", event.target.value as LayoutAnchor));
                }}
              >
                {layoutAnchorOptions.map((anchor) => (
                  <option key={anchor} value={anchor}>
                    {anchorLabel(anchor)}
                  </option>
                ))}
              </select>
            </label>
            {brandTokens ? (
              <>
                <TokenSelect
                  label="Gap Token"
                  value={currentLayout.gap_token ?? ""}
                  tokens={brandTokens.spacing_tokens}
                  disabled={selectedNode.locked}
                  onChange={(token) => {
                    onOperation(updateNodeLayout(selectedNode, { ...currentLayout, gap_token: token || null }));
                  }}
                />
                <TokenSelect
                  label="Padding Token"
                  value={currentLayout.padding_token ?? ""}
                  tokens={brandTokens.spacing_tokens}
                  disabled={selectedNode.locked}
                  onChange={(token) => {
                    onOperation(updateNodeLayout(selectedNode, { ...currentLayout, padding_token: token || null }));
                  }}
                />
              </>
            ) : null}
          </div>
          <p className="muted contract-note">
            Container direction, wrap, gap, padding, alignment, and item grow map to core Taffy layout through AutoLayoutProps.
          </p>
        </section>
  );
}

const layoutAnchorOptions: LayoutAnchor[] = ["start", "center", "end", "space_between", "stretch"];


function anchorLabel(anchor: LayoutAnchor): string {
  switch (anchor) {
    case "space_between":
      return "Space between";
    case "start":
      return "Start";
    case "center":
      return "Center";
    case "end":
      return "End";
    case "stretch":
      return "Stretch";
  }
}

function paddingWith(padding: [number, number, number, number], index: number, value: number): [number, number, number, number] {
  const next: [number, number, number, number] = [...padding];
  next[index] = value;
  return next;
}
