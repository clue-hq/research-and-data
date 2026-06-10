"use client";

import { Lock, Type, Unlock } from "lucide-react";
import type {
  BrandTokenCatalog,
  LayoutAnchor,
  Node,
  NodeId,
  Operation,
  Page,
  Scene,
  TextAlign,
  TextDirection,
  TextWrap,
  Transform
} from "@/engine/contracts";
import {
  clear,
  defaultLayoutProps,
  nodePatch,
  set,
  updateAutoLayoutAlignment,
  updateNodeLayout,
  updateNodeLocked,
  updateNodeSize,
  updateNodeTransform,
  updatePageSize,
  updateTextNode
} from "@/engine/operations";
import { dimensionToNumber, fixedSize } from "@/engine/renderAdapter";
import { nodeDisplayName } from "@/engine/sceneQueries";
import { SlotInspector } from "./SlotInspector";

interface InspectorPanelProps {
  scene: Scene;
  activePage: Page | null;
  selectedNode: Node | null;
  selectedNodeId: NodeId | null;
  brandTokens?: BrandTokenCatalog | null;
  onOperation: (operation: Operation) => void;
}

export function InspectorPanel({
  scene,
  activePage,
  selectedNode,
  selectedNodeId,
  brandTokens,
  onOperation
}: InspectorPanelProps) {
  if (!selectedNode) {
    return (
      <section className="inspector-section">
        {activePage ? (
          <>
            <div className="section-heading">Page</div>
            <label className="field">
              <span>Name</span>
              <input value={activePage.name} readOnly />
            </label>
            <div className="field-grid two">
              <NumberField
                label="W"
                value={activePage.size.width}
                min={1}
                onCommit={(value) => onOperation(updatePageSize(activePage, customPageSize(activePage, { width: value })))}
              />
              <NumberField
                label="H"
                value={activePage.size.height}
                min={1}
                onCommit={(value) => onOperation(updatePageSize(activePage, customPageSize(activePage, { height: value })))}
              />
            </div>
            <p className="muted contract-note">
              Page dimensions are canonical scene data. Presets are shortcuts only; custom sizes export exactly as authored.
            </p>
          </>
        ) : (
          <p className="muted">Select a page or node on the canvas.</p>
        )}
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

      {brandTokens ? (
        <section className="inspector-section">
          <div className="section-heading">Design Tokens</div>
          <div className="field-grid two">
            <TokenSelect
              label="Radius"
              value={selectedNode.corner.token ?? ""}
              tokens={brandTokens.radius_tokens}
              onChange={(token) =>
                onOperation({
                  kind: "update_node",
                  node_id: selectedNode.id,
                  patch: nodePatch({
                    corner: set({
                      ...selectedNode.corner,
                      token: token || null
                    })
                  })
                })
              }
            />
            <TokenSelect
              label="Opacity"
              value={selectedNode.opacity_token ?? ""}
              tokens={brandTokens.opacity_tokens}
              onChange={(token) =>
                onOperation({
                  kind: "update_node",
                  node_id: selectedNode.id,
                  patch: nodePatch({
                    opacity_token: token ? set(token) : clear()
                  })
                })
              }
            />
          </div>
          <p className="muted contract-note">Token choices are stored on the scene and resolved by preflight.</p>
        </section>
      ) : null}

      {selectedNode.kind.kind === "auto_layout" || selectedNode.layout ? (
        <section className="inspector-section">
          <div className="section-heading">Auto Layout</div>
          <div className="field-grid two">
            <NumberField
              label="Gap"
              value={(selectedNode.layout ?? defaultLayoutProps()).gap}
              min={0}
              onCommit={(value) => {
                const layout = selectedNode.layout ?? defaultLayoutProps();
                onOperation(updateNodeLayout(selectedNode, { ...layout, gap: value }));
              }}
            />
            <NumberField
              label="Padding"
              value={(selectedNode.layout ?? defaultLayoutProps()).padding[0]}
              min={0}
              onCommit={(value) => {
                const layout = selectedNode.layout ?? defaultLayoutProps();
                onOperation(updateNodeLayout(selectedNode, { ...layout, padding: [value, value, value, value] }));
              }}
            />
            <label className="field">
              <span>X</span>
              <select
                value={(selectedNode.layout ?? defaultLayoutProps()).align_x ?? "start"}
                disabled={selectedNode.locked}
                onChange={(event) => {
                  const layout = selectedNode.layout ?? defaultLayoutProps();
                  onOperation(updateAutoLayoutAlignment(selectedNode, event.target.value as LayoutAnchor, layout.align_y ?? "start"));
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
              <span>Y</span>
              <select
                value={(selectedNode.layout ?? defaultLayoutProps()).align_y ?? "start"}
                disabled={selectedNode.locked}
                onChange={(event) => {
                  const layout = selectedNode.layout ?? defaultLayoutProps();
                  onOperation(updateAutoLayoutAlignment(selectedNode, layout.align_x ?? "start", event.target.value as LayoutAnchor));
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
                  value={(selectedNode.layout ?? defaultLayoutProps()).gap_token ?? ""}
                  tokens={brandTokens.spacing_tokens}
                  onChange={(token) => {
                    const layout = selectedNode.layout ?? defaultLayoutProps();
                    onOperation(updateNodeLayout(selectedNode, { ...layout, gap_token: token || null }));
                  }}
                />
                <TokenSelect
                  label="Padding Token"
                  value={(selectedNode.layout ?? defaultLayoutProps()).padding_token ?? ""}
                  tokens={brandTokens.spacing_tokens}
                  onChange={(token) => {
                    const layout = selectedNode.layout ?? defaultLayoutProps();
                    onOperation(updateNodeLayout(selectedNode, { ...layout, padding_token: token || null }));
                  }}
                />
              </>
            ) : null}
          </div>
          <p className="muted contract-note">Alignment maps to core Taffy layout through AutoLayoutProps.</p>
        </section>
      ) : null}

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
            <NumberField
              label="Line Height"
              value={selectedNode.kind.line_height ?? 1.2}
              min={0.1}
              step={0.05}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { line_height: value }))}
            />
            <NumberField
              label="Letter Spacing"
              value={selectedNode.kind.letter_spacing ?? 0}
              step={0.25}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { letter_spacing: value }))}
            />
            <NumberField
              label="Max Lines"
              value={selectedNode.kind.max_lines ?? 0}
              min={0}
              step={1}
              onCommit={(value) =>
                onOperation(updateTextNode(selectedNode, { max_lines: value > 0 ? Math.round(value) : null }))
              }
            />
            <label className="field">
              <span>Wrap</span>
              <select
                value={selectedNode.kind.wrap ?? "wrap"}
                disabled={selectedNode.locked}
                onChange={(event) => onOperation(updateTextNode(selectedNode, { wrap: event.target.value as TextWrap }))}
              >
                <option value="wrap">Wrap</option>
                <option value="no_wrap">No wrap</option>
              </select>
            </label>
            <label className="field">
              <span>Direction</span>
              <select
                value={selectedNode.kind.direction ?? "ltr"}
                disabled={selectedNode.locked}
                onChange={(event) =>
                  onOperation(updateTextNode(selectedNode, { direction: event.target.value as TextDirection }))
                }
              >
                <option value="ltr">LTR</option>
                <option value="rtl">RTL</option>
                <option value="auto">Auto</option>
              </select>
            </label>
            {brandTokens ? (
              <TokenSelect
                label="Style Token"
                value={selectedNode.kind.style_token ?? ""}
                tokens={brandTokens.typography_tokens}
                onChange={(token) => onOperation(updateTextNode(selectedNode, { style_token: token || null }))}
              />
            ) : null}
          </div>
        </section>
      ) : null}

      <SlotInspector scene={scene} selectedNode={selectedNode} selectedNodeId={selectedNodeId} onOperation={onOperation} />
    </>
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

function customPageSize(page: Page, patch: Partial<Pick<Page["size"], "width" | "height">>): Page["size"] {
  const width = patch.width ?? page.size.width;
  const height = patch.height ?? page.size.height;
  return {
    ...page.size,
    width,
    height,
    preset: "custom",
    orientation: width >= height ? "landscape" : "portrait"
  };
}

function TokenSelect({
  label,
  value,
  tokens,
  onChange
}: {
  label: string;
  value: string;
  tokens?: string[];
  onChange: (token: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} disabled={!tokens?.length} onChange={(event) => onChange(event.target.value)}>
        <option value="">Concrete value</option>
        {(tokens ?? []).map((token) => (
          <option key={token} value={token}>
            ${token}
          </option>
        ))}
      </select>
    </label>
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
