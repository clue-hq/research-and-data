"use client";

import type {
  BrandTokenCatalog,
  CornerRadii,
  Fill,
  Node,
  Operation,
  Stroke
} from "@/engine/contracts";
import { clear, nodePatch, set, updateNodeFills, updateNodeStrokes } from "@/engine/operations";
import { colorToCss, tokenSwatchCss } from "@/engine/renderAdapter";
import { TokenSelect, roundForEditor, tokenFill, tokenFromFill } from "./fields";

/** BrandKit token bindings for the selected node, plus the token-vs-raw
 * style summary. */
export function DesignTokensSection({
  selectedNode,
  brandTokens,
  onOperation
}: {
  selectedNode: Node;
  brandTokens: BrandTokenCatalog;
  onOperation: (operation: Operation) => void;
}) {
  return (
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
  );
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

function tokenFromStroke(stroke: Stroke | undefined): string {
  return stroke?.paint.kind === "token" ? stroke.paint.token : "";
}

/** Which brand fill-token bucket applies to a node: text nodes get the
 * `text.*` role tokens, everything else gets `surface.*`. Shared with
 * `ColorSwatchControl`'s token-first popover so the two surfaces never
 * diverge on which tokens count as "this node's fill tokens." */
export function fillTokensForNode(node: Node, brandTokens: BrandTokenCatalog): string[] {
  if (node.kind.kind === "text") {
    return brandTokens.text_tokens ?? [];
  }
  return brandTokens.surface_tokens ?? [];
}

function strokeTokens(brandTokens: BrandTokenCatalog): string[] {
  return brandTokens.border_tokens ?? brandTokens.surface_tokens ?? [];
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
    return {
      ...tokenStyleItem(label, fill.paint.token, tokenUniverse(brandTokens)),
      swatch: tokenSwatchCss(fill.paint.token)
    };
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
    return {
      ...tokenStyleItem("Stroke", stroke.paint.token, tokenUniverse(brandTokens)),
      swatch: tokenSwatchCss(stroke.paint.token)
    };
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
