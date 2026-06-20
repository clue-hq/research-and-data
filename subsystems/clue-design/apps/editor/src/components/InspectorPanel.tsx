"use client";

import { Lock, Trash2, Type, Unlock } from "lucide-react";
import type {
  AutoLayoutNode,
  BrandTokenCatalog,
  CornerRadii,
  Diagnostic,
  DiagnosticSubject,
  Dimension,
  Fill,
  LayoutAnchor,
  Node,
  NodeId,
  Operation,
  Page,
  Rect,
  Unit,
  Scene,
  Stroke,
  TextAlign,
  TextDirection,
  TextWrap,
  Transform
} from "@/engine/contracts";
import {
  clear,
  defaultLayoutProps,
  nodePatch,
  removeNode,
  set,
  updateAutoLayoutAlignment,
  updateAutoLayoutNode,
  updateDocumentArtifactType,
  updateDocumentTitle,
  updateNodeLayout,
  updateNodeLocked,
  updateNodeFills,
  updateNodeSize,
  updateNodeName,
  updateNodeStrokes,
  updateNodeTransform,
  updatePageBackground,
  updatePageBleed,
  updatePageName,
  updatePageSafeArea,
  updatePageSize,
  updateTextNode
} from "@/engine/operations";
import { colorToCss, dimensionToNumber, fixedSize } from "@/engine/renderAdapter";
import { normalizePageSize } from "@/engine/pageGeometry";
import { flattenPageNodeIds, isNodeDirectGeometryEditable, isNodeLayoutManaged, nodeDisplayName } from "@/engine/sceneQueries";
import { deriveSelectionChromeModel, type SelectionChromeModel } from "@/engine/selectionChrome";
import { SlotInspector, SlotOverview } from "./SlotInspector";
import { ImageInspectorSection } from "./ImageInspectorSection";

interface InspectorPanelProps {
  scene: Scene;
  activePage: Page | null;
  selectedNode: Node | null;
  selectedNodeId: NodeId | null;
  brandTokens?: BrandTokenCatalog | null;
  diagnostics?: Diagnostic[];
  renderDiagnostics?: Diagnostic[];
  apiBaseUrl?: string;
  onOperation: (operation: Operation) => void;
  onOperations?: (operations: Operation[]) => void;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}

export function InspectorPanel({
  scene,
  activePage,
  selectedNode,
  selectedNodeId,
  brandTokens,
  diagnostics = [],
  renderDiagnostics = [],
  apiBaseUrl,
  onOperation,
  onOperations,
  onSelectSubject
}: InspectorPanelProps) {
  const emitOperations =
    onOperations ?? ((operations: Operation[]) => operations.forEach(onOperation));
  if (!selectedNode) {
    const pageDiagnostics = activePage
      ? inspectorDiagnosticsForPage(scene, activePage.id, [...diagnostics, ...renderDiagnostics])
      : [];
    return (
      <section className="inspector-section">
        <div className="section-heading">Document</div>
        <label className="field">
          <span>Document Title</span>
          <input value={scene.meta.title} onChange={(event) => onOperation(updateDocumentTitle(event.target.value))} />
        </label>
        <label className="field">
          <span>Artifact Type</span>
          <input
            value={scene.meta.artifact_type ?? ""}
            placeholder="ad, report, email, mailer"
            onChange={(event) => onOperation(updateDocumentArtifactType(event.target.value))}
          />
        </label>
        {activePage ? (
          <>
            <div className="section-heading">Page</div>
            <SelectedArtboardSummary activePage={activePage} diagnostics={pageDiagnostics} />
            <label className="field">
              <span>Name</span>
              <input value={activePage.name} onChange={(event) => onOperation(updatePageName(activePage, event.target.value))} />
            </label>
            <div className="field-grid two">
              <label className="field">
                <span>Preset</span>
                <input value={activePage.size.preset ?? "custom"} readOnly />
              </label>
              <label className="field">
                <span>Orientation</span>
                <input value={orientationLabel(activePage.size.width, activePage.size.height)} readOnly />
              </label>
            </div>
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
              <label className="field">
                <span>Unit</span>
                <select
                  value={activePage.size.unit}
                  onChange={(event) =>
                    onOperation(updatePageSize(activePage, customPageSize(activePage, { unit: event.target.value as Unit })))
                  }
                >
                  <option value="pt">pt</option>
                  <option value="px">px</option>
                  <option value="mm">mm</option>
                  <option value="in">in</option>
                </select>
              </label>
            </div>
            <div className="section-heading nested-heading">Print guides</div>
            <div className="field-grid two">
              <NumberField
                label="Safe Margin"
                value={safeAreaMargin(activePage)}
                min={0}
                onCommit={(value) => onOperation(updatePageSafeArea(activePage, safeAreaFromMargin(activePage, value)))}
              />
              <NumberField
                label="Bleed"
                value={bleedMargin(activePage)}
                min={0}
                onCommit={(value) => onOperation(updatePageBleed(activePage, bleedFromMargin(activePage, value)))}
              />
            </div>
            {brandTokens ? (
              <>
                <div className="section-heading nested-heading">Brand style</div>
                <div className="field-grid two">
                  <TokenSelect
                    label="Page Fill Token"
                    value={tokenFromFill(activePage.background[0])}
                    tokens={brandTokens.surface_tokens}
                    onChange={(token) => onOperation(updatePageBackground(activePage, token ? [tokenFill(activePage.id, "background", token)] : []))}
                  />
                </div>
              </>
            ) : null}
            <InspectorDiagnosticsSection
              title="Page Issues"
              diagnostics={pageDiagnostics}
              onSelectSubject={onSelectSubject}
            />
            <SlotOverview scene={scene} activePageId={activePage.id} />
            <p className="muted contract-note">
              Page/artboard dimensions are canonical scene data. Presets are shortcuts only; custom sizes export exactly as authored.
              Safe area and bleed are canonical page guides for print/export readiness.
            </p>
          </>
        ) : (
          <p className="muted">Select a page or node on the canvas.</p>
        )}
      </section>
    );
  }

  const size = fixedSize(selectedNode.size);
  const layoutManaged = isNodeLayoutManaged(scene, selectedNode.id);
  const directGeometryEditable = isNodeDirectGeometryEditable(scene, selectedNode.id);
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

  return (
    <>
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
        <SelectedObjectSummary model={selectionChrome} locked={selectedNode.locked} layoutManaged={layoutManaged} />
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
            value={selectedNode.transform.x}
            disabled={!directGeometryEditable}
            onCommit={(value) => emitTransform({ x: value })}
          />
          <NumberField
            label="Y"
            value={selectedNode.transform.y}
            disabled={!directGeometryEditable}
            onCommit={(value) => emitTransform({ y: value })}
          />
          <NumberField
            label="W"
            value={size.width}
            disabled={!directGeometryEditable}
            onCommit={(value) =>
              onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, width: { kind: "fixed", value } }))
            }
          />
          <NumberField
            label="H"
            value={size.height}
            disabled={!directGeometryEditable}
            onCommit={(value) =>
              onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, height: { kind: "fixed", value } }))
            }
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
          {layoutManaged
            ? "This node is managed by an auto-layout parent. Use layout controls or reorder the layer instead of direct geometry edits."
            : selectedNode.locked
              ? "This node is locked. Unlock it before moving, resizing, or rotating it."
            : `Dimensions use the active page unit. Non-fixed dimensions currently show as ${dimensionToNumber(selectedNode.size.width)}.`}
        </p>
      </section>

      {selectedNode.kind.kind === "image" ? (
        <ImageInspectorSection
          node={selectedNode}
          asset={scene.assets[selectedNode.kind.asset_id] ?? null}
          apiBaseUrl={apiBaseUrl ?? "http://localhost:8000"}
          disabled={selectedNode.locked}
          onOperations={emitOperations}
        />
      ) : null}

      <section className="inspector-section">
        <div className="section-heading">Sizing</div>
        <div className="field-grid two">
          <DimensionModeSelect
            label="Width mode"
            dimension={selectedNode.size.width}
            disabled={selectedNode.locked}
            onChange={(dimension) => onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, width: dimension }))}
          />
          <DimensionModeSelect
            label="Height mode"
            dimension={selectedNode.size.height}
            disabled={selectedNode.locked}
            onChange={(dimension) => onOperation(updateNodeSize(selectedNode, { ...selectedNode.size, height: dimension }))}
          />
          {selectedNode.size.width.kind === "fixed" ? (
            <NumberField
              label="Width fixed"
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

      <section className="inspector-section">
        <div className="section-heading">Raw Style</div>
        <div className="field-grid two">
          <label className="field">
            <span>Fill Color</span>
            <input
              type="color"
              value={hexInputValueFromFill(selectedNode)}
              disabled={selectedNode.locked}
              onChange={(event) => onOperation(updateNodeFills(selectedNode, [solidFill(selectedNode.id, "fill", event.target.value)]))}
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

      {brandTokens ? (
        <section className="inspector-section">
          <div className="section-heading">Design Tokens</div>
          <div className="field-grid two">
            <TokenSelect
              label="Fill Token"
              value={tokenFromFill(selectedNode.fills[0])}
              tokens={fillTokensForNode(selectedNode, brandTokens)}
              disabled={selectedNode.locked}
              onChange={(token) => onOperation(updateNodeFills(selectedNode, token ? [tokenFill(selectedNode.id, "fill", token)] : []))}
            />
            <TokenSelect
              label="Stroke Token"
              value={tokenFromStroke(selectedNode.strokes[0])}
              tokens={strokeTokens(brandTokens)}
              disabled={selectedNode.locked}
              onChange={(token) =>
                onOperation(
                  updateNodeStrokes(
                    selectedNode,
                    token ? [tokenStroke(selectedNode, token, selectedNode.strokes[0]?.width_token ?? null)] : []
                  )
                )
              }
            />
            <TokenSelect
              label="Stroke Width Token"
              value={selectedNode.strokes[0]?.width_token ?? ""}
              tokens={brandTokens.stroke_width_tokens}
              disabled={selectedNode.locked || selectedNode.strokes.length === 0}
              onChange={(token) =>
                onOperation(
                  updateNodeStrokes(
                    selectedNode,
                    selectedNode.strokes.length > 0
                      ? [
                          {
                            ...selectedNode.strokes[0],
                            width_token: token || null
                          },
                          ...selectedNode.strokes.slice(1)
                        ]
                      : []
                  )
                )
              }
            />
            <TokenSelect
              label="Radius"
              value={selectedNode.corner.token ?? ""}
              tokens={brandTokens.radius_tokens}
              disabled={selectedNode.locked}
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
              label="Opacity Token"
              value={selectedNode.opacity_token ?? ""}
              tokens={brandTokens.opacity_tokens}
              disabled={selectedNode.locked}
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
          <StyleSummary node={selectedNode} brandTokens={brandTokens} />
          <p className="muted contract-note">Token choices are stored on the scene and resolved by preflight.</p>
        </section>
      ) : null}

      {selectedNode.kind.kind === "auto_layout" || selectedNode.layout || layoutManaged ? (
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
              disabled={selectedNode.locked}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { font_size: value }))}
            />
            <NumberField
              label="Weight"
              value={selectedNode.kind.font_weight}
              min={100}
              max={900}
              step={100}
              disabled={selectedNode.locked}
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
              disabled={selectedNode.locked}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { line_height: value }))}
            />
            <NumberField
              label="Letter Spacing"
              value={selectedNode.kind.letter_spacing ?? 0}
              step={0.25}
              disabled={selectedNode.locked}
              onCommit={(value) => onOperation(updateTextNode(selectedNode, { letter_spacing: value }))}
            />
            <NumberField
              label="Max Lines"
              value={selectedNode.kind.max_lines ?? 0}
              min={0}
              step={1}
              disabled={selectedNode.locked}
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
                disabled={selectedNode.locked}
                onChange={(token) => onOperation(updateTextNode(selectedNode, { style_token: token || null }))}
              />
            ) : null}
          </div>
        </section>
      ) : null}

      <SlotInspector
        scene={scene}
        selectedNode={selectedNode}
        selectedNodeId={selectedNodeId}
        onOperation={onOperation}
        onOperations={onOperations}
      />
    </>
  );
}

const layoutAnchorOptions: LayoutAnchor[] = ["start", "center", "end", "space_between", "stretch"];

type EditableDimensionMode = Exclude<Dimension["kind"], "token">;

function DimensionModeSelect({
  label,
  dimension,
  disabled,
  onChange
}: {
  label: string;
  dimension: Dimension;
  disabled: boolean;
  onChange: (dimension: Dimension) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select
        value={dimension.kind}
        disabled={disabled}
        onChange={(event) => {
          const mode = event.target.value as Dimension["kind"];
          if (mode === "token") {
            return;
          }
          onChange(dimensionForMode(mode, dimension));
        }}
      >
        <option value="fixed">Fixed</option>
        <option value="hug">Hug</option>
        <option value="fill">Fill</option>
        {dimension.kind === "token" ? <option value="token">Token</option> : null}
      </select>
    </label>
  );
}

function dimensionForMode(mode: EditableDimensionMode, current: Dimension): Dimension {
  switch (mode) {
    case "fixed":
      return {
        kind: "fixed",
        value: fixedDimensionValue(current)
      };
    case "hug":
      return {
        kind: "hug"
      };
    case "fill":
      return {
        kind: "fill",
        value: {
          weight: current.kind === "fill" ? current.value.weight : 1
        }
      };
  }
}

function fixedDimensionValue(dimension: Dimension): number {
  if (dimension.kind === "fixed") {
    return normalizePositiveDimension(dimension.value);
  }
  return 120;
}

function SelectedArtboardSummary({ activePage, diagnostics }: { activePage: Page; diagnostics: Diagnostic[] }) {
  const counts = countDiagnostics(diagnostics);
  return (
    <div className="selection-summary" aria-label="Selected artboard summary">
      <div>
        <span>Artboard</span>
        <strong>{activePage.name}</strong>
      </div>
      <div>
        <span>Size</span>
        <strong>
          {formatDimension(activePage.size.width)} x {formatDimension(activePage.size.height)} {activePage.size.unit}
        </strong>
      </div>
      <div>
        <span>Issues</span>
        <strong>{diagnosticCountLabel(counts)}</strong>
      </div>
    </div>
  );
}

function SelectedObjectSummary({
  model,
  locked,
  layoutManaged
}: {
  model: SelectionChromeModel;
  locked: boolean;
  layoutManaged: boolean;
}) {
  const objectKind =
    model.isSlotBound && model.baseObjectKind
      ? `slot-bound ${objectKindLabel(model.baseObjectKind)}`
      : model.baseObjectKind
        ? objectKindLabel(model.baseObjectKind)
        : "unknown";
  return (
    <div className="selection-summary" aria-label="Selected object summary">
      <div>
        <span>Object</span>
        <strong>{objectKind}</strong>
      </div>
      <div>
        <span>Canvas handles</span>
        <strong>{model.showHandles ? "Enabled" : "Disabled"}</strong>
      </div>
      <div>
        <span>State</span>
        <strong>{selectionStateLabel({ locked, layoutManaged, isSlotBound: model.isSlotBound })}</strong>
      </div>
      <div>
        <span>Slots</span>
        <strong>{model.slotKeys.length > 0 ? model.slotKeys.join(", ") : "Static"}</strong>
      </div>
      <div>
        <span>Issues</span>
        <strong>{diagnosticCountLabel(model.diagnosticCounts)}</strong>
      </div>
    </div>
  );
}

function countDiagnostics(diagnostics: Diagnostic[]): { errors: number; warnings: number } {
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

function diagnosticCountLabel(counts: { errors: number; warnings: number }): string {
  if (counts.errors === 0 && counts.warnings === 0) {
    return "None";
  }
  const parts: string[] = [];
  if (counts.errors > 0) {
    parts.push(`${counts.errors} error${counts.errors === 1 ? "" : "s"}`);
  }
  if (counts.warnings > 0) {
    parts.push(`${counts.warnings} warning${counts.warnings === 1 ? "" : "s"}`);
  }
  return parts.join(" / ");
}

function selectionStateLabel({
  locked,
  layoutManaged,
  isSlotBound
}: {
  locked: boolean;
  layoutManaged: boolean;
  isSlotBound: boolean;
}): string {
  const states = [
    locked ? "Locked" : null,
    layoutManaged ? "Layout-managed child" : null,
    isSlotBound ? "Slot-bound" : null
  ].filter((state): state is string => Boolean(state));
  return states.length > 0 ? states.join(" / ") : "Editable";
}

function objectKindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

function formatDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}

interface StyleSummaryItem {
  label: string;
  detail: string;
  status: "token" | "raw" | "missing";
  swatch?: string | null;
}

function StyleSummary({ node, brandTokens }: { node: Node; brandTokens: BrandTokenCatalog }) {
  const items = styleSummaryItems(node, brandTokens);
  return (
    <div className="style-summary" aria-label="Selected style summary">
      {items.map((item) => (
        <div key={item.label} className={`style-summary-item ${item.status}`}>
          <span className="style-summary-label">{item.label}</span>
          <div className="style-summary-value">
            {item.swatch ? <span className="style-swatch" aria-hidden style={{ background: item.swatch }} /> : null}
            <span>{item.detail}</span>
          </div>
          <strong>{statusLabel(item.status)}</strong>
        </div>
      ))}
    </div>
  );
}

function styleSummaryItems(node: Node, brandTokens: BrandTokenCatalog): StyleSummaryItem[] {
  const items: StyleSummaryItem[] = [
    paintStyleItem("Fill", node.fills[0], brandTokens),
    strokeStyleItem(node.strokes[0], brandTokens),
    tokenOrRawItem("Radius", node.corner.token ?? null, radiusRawLabel(node), brandTokens.radius_tokens),
    tokenOrRawItem("Opacity", node.opacity_token ?? null, `${roundForEditor(node.opacity)}`, brandTokens.opacity_tokens)
  ];

  if (node.kind.kind === "text") {
    items.push(
      tokenOrRawItem(
        "Text Style",
        node.kind.style_token ?? null,
        `${node.kind.font_family} ${node.kind.font_size}/${node.kind.line_height ?? 1.2} ${node.kind.font_weight}`,
        brandTokens.typography_tokens
      )
    );
  }

  if (node.layout) {
    items.push(
      tokenOrRawItem("Gap", node.layout.gap_token ?? null, `${node.layout.gap}`, brandTokens.spacing_tokens),
      tokenOrRawItem("Padding", node.layout.padding_token ?? null, node.layout.padding.join(", "), brandTokens.spacing_tokens)
    );
  }

  return items;
}

function paintStyleItem(label: string, fill: Fill | undefined, brandTokens: BrandTokenCatalog): StyleSummaryItem {
  if (!fill) {
    return rawStyleItem(label, "none");
  }
  if (fill.paint.kind === "token") {
    return tokenStyleItem(label, fill.paint.token, tokenUniverse(brandTokens));
  }
  if (fill.paint.kind === "solid") {
    return {
      ...rawStyleItem(label, paintLabel(fill)),
      swatch: colorToCss(fill.paint.color)
    };
  }
  return rawStyleItem(label, fill.paint.kind === "linear_gradient" ? "linear gradient" : "radial gradient");
}

function strokeStyleItem(stroke: Stroke | undefined, brandTokens: BrandTokenCatalog): StyleSummaryItem {
  if (!stroke) {
    return rawStyleItem("Stroke", "none");
  }
  if (stroke.paint.kind === "token") {
    return tokenStyleItem("Stroke", stroke.paint.token, tokenUniverse(brandTokens));
  }
  if (stroke.paint.kind === "solid") {
    return {
      ...rawStyleItem("Stroke", `${paintLabel({ id: stroke.id, paint: stroke.paint })} / ${stroke.width}`),
      swatch: colorToCss(stroke.paint.color)
    };
  }
  return rawStyleItem("Stroke", `${stroke.paint.kind === "linear_gradient" ? "linear gradient" : "radial gradient"} / ${stroke.width}`);
}

function tokenOrRawItem(label: string, token: string | null, rawLabel: string, knownTokens?: string[]): StyleSummaryItem {
  return token ? tokenStyleItem(label, token, knownTokens) : rawStyleItem(label, rawLabel);
}

function tokenStyleItem(label: string, token: string, knownTokens?: string[]): StyleSummaryItem {
  const known = !knownTokens || knownTokens.length === 0 || knownTokens.includes(token);
  return {
    label,
    detail: `$${token}${known ? "" : " (not in current Brand Kit)"}`,
    status: known ? "token" : "missing"
  };
}

function rawStyleItem(label: string, detail: string): StyleSummaryItem {
  return {
    label,
    detail,
    status: "raw"
  };
}

function statusLabel(status: StyleSummaryItem["status"]): string {
  switch (status) {
    case "token":
      return "Token";
    case "missing":
      return "Missing token";
    case "raw":
      return "Raw";
  }
}

function paintLabel(fill: Fill): string {
  switch (fill.paint.kind) {
    case "token":
      return `$${fill.paint.token}`;
    case "solid":
      switch (fill.paint.color.kind) {
        case "hex":
          return fill.paint.color.value;
        case "oklch":
          return `oklch(${fill.paint.color.l} ${fill.paint.color.c} ${fill.paint.color.h})`;
        case "token":
          return `$${fill.paint.color.token}`;
      }
    case "linear_gradient":
      return "linear gradient";
    case "radial_gradient":
      return "radial gradient";
  }
}

function radiusRawLabel(node: Node): string {
  return [
    node.corner.top_left,
    node.corner.top_right,
    node.corner.bottom_right,
    node.corner.bottom_left
  ].join(", ");
}

function tokenUniverse(brandTokens: BrandTokenCatalog): string[] {
  return Object.values(brandTokens).flatMap((tokens) => tokens ?? []);
}

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

function customPageSize(page: Page, patch: Partial<Pick<Page["size"], "width" | "height" | "unit">>): Page["size"] {
  const source = page.size.source;
  const width = normalizePositiveDimension(patch.width ?? source?.width ?? page.size.width);
  const height = normalizePositiveDimension(patch.height ?? source?.height ?? page.size.height);
  return normalizePageSize({
    width,
    height,
    unit: patch.unit ?? "pt",
    preset: "custom"
  });
}

function safeAreaFromMargin(page: Page, rawMargin: number): Rect | null {
  const margin = normalizeGuideMargin(rawMargin, page);
  if (margin === 0) {
    return null;
  }
  return {
    x: margin,
    y: margin,
    width: Math.max(1, page.size.width - margin * 2),
    height: Math.max(1, page.size.height - margin * 2)
  };
}

function bleedFromMargin(page: Page, rawMargin: number): Rect | null {
  const margin = normalizeGuideMargin(rawMargin, page);
  if (margin === 0) {
    return null;
  }
  return {
    x: -margin,
    y: -margin,
    width: page.size.width + margin * 2,
    height: page.size.height + margin * 2
  };
}

function safeAreaMargin(page: Page): number {
  if (!page.safe_area) {
    return 0;
  }
  return roundForEditor(
    Math.max(
      0,
      Math.min(
        page.safe_area.x,
        page.safe_area.y,
        page.size.width - page.safe_area.x - page.safe_area.width,
        page.size.height - page.safe_area.y - page.safe_area.height
      )
    )
  );
}

function bleedMargin(page: Page): number {
  if (!page.bleed) {
    return 0;
  }
  return roundForEditor(Math.max(0, Math.min(-page.bleed.x, -page.bleed.y)));
}

function normalizeGuideMargin(value: number, page: Page): number {
  if (!Number.isFinite(value) || value <= 0) {
    return 0;
  }
  return roundForEditor(Math.min(value, Math.max(0, Math.min(page.size.width, page.size.height) / 2 - 1)));
}

function roundForEditor(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function solidFill(ownerId: string, role: string, hex: string): Fill {
  return {
    id: `paint_${ownerId}_${role}`,
    paint: {
      kind: "solid",
      color: {
        kind: "hex",
        value: normalizeHexInput(hex)
      }
    }
  };
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

function hexInputValueFromFill(node: Node): string {
  const fill = node.fills[0];
  if (fill?.paint.kind === "solid" && fill.paint.color.kind === "hex") {
    return normalizeHexInput(fill.paint.color.value);
  }
  if (node.kind.kind === "text" || node.kind.kind === "line") {
    return "#27231d";
  }
  if (node.kind.kind === "image") {
    return "#ddd7cc";
  }
  return "#f5f1e9";
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

function tokenFill(ownerId: string, role: string, token: string): Fill {
  return {
    id: `paint_${ownerId}_${role}`,
    paint: {
      kind: "token",
      token
    }
  };
}

function tokenStroke(node: Node, token: string, widthToken: string | null): Stroke {
  const existing = node.strokes[0];
  return {
    id: existing?.id ?? `paint_${node.id}_stroke`,
    paint: {
      kind: "token",
      token
    },
    width: existing?.width ?? 1,
    width_token: widthToken
  };
}

function tokenFromFill(fill: Fill | undefined): string {
  return fill?.paint.kind === "token" ? fill.paint.token : "";
}

function tokenFromStroke(stroke: Stroke | undefined): string {
  return stroke?.paint.kind === "token" ? stroke.paint.token : "";
}

function fillTokensForNode(node: Node, brandTokens: BrandTokenCatalog): string[] {
  if (node.kind.kind === "text") {
    return brandTokens.text_tokens ?? [];
  }
  return brandTokens.surface_tokens ?? [];
}

function strokeTokens(brandTokens: BrandTokenCatalog): string[] {
  return brandTokens.border_tokens ?? brandTokens.surface_tokens ?? [];
}

function paddingWith(padding: [number, number, number, number], index: number, value: number): [number, number, number, number] {
  const next: [number, number, number, number] = [...padding];
  next[index] = value;
  return next;
}

function InspectorDiagnosticsSection({
  title,
  diagnostics,
  onSelectSubject
}: {
  title: string;
  diagnostics: Diagnostic[];
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  if (diagnostics.length === 0) {
    return null;
  }
  return (
    <div className="inspector-diagnostics" aria-label={title}>
      <div className="section-heading nested-heading">{title}</div>
      <ul className="diagnostic-list compact">
        {diagnostics.map((diagnostic) => (
          <InspectorDiagnosticItem
            key={diagnosticKey(diagnostic)}
            diagnostic={diagnostic}
            onSelectSubject={onSelectSubject}
          />
        ))}
      </ul>
    </div>
  );
}

function InspectorDiagnosticItem({
  diagnostic,
  onSelectSubject
}: {
  diagnostic: Diagnostic;
  onSelectSubject?: (subject: DiagnosticSubject) => void;
}) {
  const canSelect = Boolean(onSelectSubject && diagnostic.subject && diagnostic.subject.kind !== "document");
  return (
    <li className={diagnostic.severity}>
      <strong>{diagnostic.code}</strong>
      <span>{diagnostic.message}</span>
      {diagnostic.subject ? (
        <button
          type="button"
          className="diagnostic-subject-button"
          disabled={!canSelect}
          onClick={() => diagnostic.subject && onSelectSubject?.(diagnostic.subject)}
        >
          {canSelect ? `Show ${diagnosticSubjectLabel(diagnostic.subject)}` : diagnosticSubjectLabel(diagnostic.subject)}
        </button>
      ) : null}
    </li>
  );
}

function inspectorDiagnosticsForNode(scene: Scene, node: Node, diagnostics: Diagnostic[]): Diagnostic[] {
  const scopedNodeIds = nodeScopeIds(scene, node.id);
  return dedupeDiagnostics(
    diagnostics.filter((diagnostic) => diagnostic.subject && diagnosticSubjectMatchesNodeScope(scene, diagnostic.subject, scopedNodeIds))
  );
}

function inspectorDiagnosticsForPage(scene: Scene, pageId: Page["id"], diagnostics: Diagnostic[]): Diagnostic[] {
  const pageNodeIds = new Set(flattenPageNodeIds(scene, pageId));
  return dedupeDiagnostics(
    diagnostics.filter((diagnostic) => diagnostic.subject && diagnosticSubjectMatchesPageScope(scene, diagnostic.subject, pageId, pageNodeIds))
  );
}

function diagnosticSubjectMatchesNodeScope(
  scene: Scene,
  subject: DiagnosticSubject,
  scopedNodeIds: Set<NodeId>
): boolean {
  switch (subject.kind) {
    case "document":
    case "page":
      return false;
    case "node":
      return scopedNodeIds.has(subject.id);
    case "slot": {
      const slot = scene.slots[subject.id] ?? null;
      return Boolean(slot?.bound_nodes.some((nodeId) => scopedNodeIds.has(nodeId)));
    }
    case "asset":
      return [...scopedNodeIds].some((nodeId) => nodeUsesAsset(scene.nodes[nodeId], subject.id));
  }
}

function diagnosticSubjectMatchesPageScope(
  scene: Scene,
  subject: DiagnosticSubject,
  pageId: Page["id"],
  pageNodeIds: Set<NodeId>
): boolean {
  switch (subject.kind) {
    case "document":
      return false;
    case "page":
      return subject.id === pageId;
    case "node":
      return pageNodeIds.has(subject.id);
    case "slot": {
      const slot = scene.slots[subject.id] ?? null;
      return Boolean(slot?.bound_nodes.some((nodeId) => pageNodeIds.has(nodeId)));
    }
    case "asset":
      return [...pageNodeIds].some((nodeId) => nodeUsesAsset(scene.nodes[nodeId], subject.id));
  }
}

function nodeScopeIds(scene: Scene, nodeId: NodeId): Set<NodeId> {
  const ids = new Set<NodeId>();
  const visit = (currentId: NodeId) => {
    if (ids.has(currentId)) {
      return;
    }
    const node = scene.nodes[currentId];
    if (!node) {
      return;
    }
    ids.add(currentId);
    for (const childId of node.children) {
      visit(childId);
    }
  };
  visit(nodeId);
  return ids;
}

function nodeUsesAsset(node: Node | undefined, assetId: string): boolean {
  return Boolean(node && (node.source_asset_id === assetId || (node.kind.kind === "image" && node.kind.asset_id === assetId)));
}

function dedupeDiagnostics(diagnostics: Diagnostic[]): Diagnostic[] {
  const seen = new Set<string>();
  return diagnostics.filter((diagnostic) => {
    const key = diagnosticKey(diagnostic);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function diagnosticKey(diagnostic: Diagnostic): string {
  return `${diagnostic.severity}:${diagnostic.phase}:${diagnostic.code}:${diagnostic.message}:${diagnostic.subject ? diagnosticSubjectLabel(diagnostic.subject) : "none"}`;
}

function diagnosticSubjectLabel(subject: DiagnosticSubject): string {
  switch (subject.kind) {
    case "document":
      return "document";
    case "page":
      return `artboard ${subject.id}`;
    case "node":
      return `node ${subject.id}`;
    case "slot":
      return `slot ${subject.id}`;
    case "asset":
      return `asset ${subject.id}`;
  }
}

function normalizePositiveDimension(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 1;
}

function orientationForDimensions(width: number, height: number): Page["size"]["orientation"] {
  return width >= height ? "landscape" : "portrait";
}

function orientationLabel(width: number, height: number): string {
  return orientationForDimensions(width, height);
}

function TokenSelect({
  label,
  value,
  tokens,
  disabled = false,
  onChange
}: {
  label: string;
  value: string;
  tokens?: string[];
  disabled?: boolean;
  onChange: (token: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} disabled={disabled || !tokens?.length} onChange={(event) => onChange(event.target.value)}>
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
  disabled = false,
  onCommit
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
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
        disabled={disabled}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) {
            onCommit(clampNumber(next, min, max));
          }
        }}
      />
    </label>
  );
}

function clampNumber(value: number, min?: number, max?: number): number {
  if (min !== undefined && value < min) {
    return min;
  }
  if (max !== undefined && value > max) {
    return max;
  }
  return value;
}
