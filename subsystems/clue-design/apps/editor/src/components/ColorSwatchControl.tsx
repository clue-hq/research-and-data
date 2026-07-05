"use client";

import { useState } from "react";
import type { BrandTokenCatalog, Fill, Node } from "@/engine/contracts";
import { colorToCss } from "@/engine/renderAdapter";
import { fillTokensForNode } from "./inspector/DesignTokensSection";
import { tokenFill, tokenFromFill } from "./inspector/fields";

/**
 * Token-first color swatch: click opens a popover of brand color tokens
 * (grouped text-first for text nodes, then surface, then remaining palette
 * tokens) plus a "Custom" native color input escape hatch. Both paths write
 * through `onEdit` as a plain fills operation — no policy lives here, and no
 * `style_token` field is ever authored; the engine owns clearing it on a
 * genuine raw recolor.
 *
 * Gradient-clobber guard: a node with more than one fill, or any fill paint
 * that isn't solid/token (a gradient), is never offered a destructive
 * replace. The swatch renders a mixed/gradient state and the popover shows
 * only the fill summary.
 */
export function ColorSwatchControl({
  node,
  brandTokens,
  onEdit,
  label = "Fill color"
}: {
  node: Node;
  brandTokens?: BrandTokenCatalog | null;
  onEdit: (fills: Fill[]) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const fill = node.fills[0];
  const guarded = isGradientGuarded(node.fills);
  const disabled = node.locked;

  const pickToken = (token: string) => {
    onEdit([tokenFill(node.id, "fill", token)]);
    setOpen(false);
  };

  const pickCustom = (hex: string) => {
    onEdit([solidHexFill(node.id, hex)]);
  };

  return (
    <div className="color-swatch-control">
      <button
        type="button"
        className={`color-swatch-trigger${guarded ? " mixed" : ""}`}
        aria-label={label}
        aria-haspopup="true"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        <ColorSwatchPreview node={node} guarded={guarded} />
      </button>
      {open ? (
        <div className="color-swatch-popover" role="dialog" aria-label={`${label} picker`}>
          {guarded ? (
            <GuardedSummary node={node} />
          ) : (
            <>
              <TokenGroups
                node={node}
                brandTokens={brandTokens}
                activeToken={tokenFromFill(fill)}
                onPick={pickToken}
              />
              <div className="color-swatch-custom-row">
                <span className="color-swatch-custom-label">Custom</span>
                <input
                  type="color"
                  aria-label="Custom color"
                  value={hexInputValue(fill)}
                  disabled={disabled}
                  onChange={(event) => pickCustom(event.target.value)}
                />
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function ColorSwatchPreview({ node, guarded }: { node: Node; guarded: boolean }) {
  const fill = node.fills[0];
  if (guarded) {
    return <span className="color-swatch-preview mixed" aria-hidden />;
  }
  if (!fill) {
    return <span className="color-swatch-preview empty" aria-hidden />;
  }
  if (fill.paint.kind === "token") {
    return (
      <span className="color-swatch-preview token" aria-hidden title={`$${fill.paint.token}`}>
        <span className="color-swatch-token-badge">{tokenBadgeText(fill.paint.token)}</span>
      </span>
    );
  }
  if (fill.paint.kind === "solid") {
    return <span className="color-swatch-preview" aria-hidden style={{ background: colorToCss(fill.paint.color) }} />;
  }
  return <span className="color-swatch-preview mixed" aria-hidden />;
}

function GuardedSummary({ node }: { node: Node }) {
  return (
    <div className="color-swatch-guard">
      <p className="color-swatch-guard-message">Gradient fill — edit in Appearance</p>
      <ul className="color-swatch-guard-list">
        {node.fills.map((fill) => (
          <li key={fill.id}>{fillSummaryLabel(fill)}</li>
        ))}
      </ul>
    </div>
  );
}

function TokenGroups({
  node,
  brandTokens,
  activeToken,
  onPick
}: {
  node: Node;
  brandTokens?: BrandTokenCatalog | null;
  activeToken: string;
  onPick: (token: string) => void;
}) {
  const groups = tokenGroupsForNode(node, brandTokens);
  if (groups.every((group) => group.tokens.length === 0)) {
    return <p className="color-swatch-empty-groups muted">No brand color tokens available.</p>;
  }
  return (
    <>
      {groups.map((group) =>
        group.tokens.length > 0 ? (
          <div className="color-swatch-group" key={group.label}>
            <span className="color-swatch-group-label">{group.label}</span>
            <div className="color-swatch-grid" role="listbox" aria-label={group.label}>
              {group.tokens.map((token) => (
                <button
                  key={token}
                  type="button"
                  role="option"
                  aria-selected={activeToken === token}
                  className={`color-swatch-chip${activeToken === token ? " active" : ""}`}
                  title={`$${token}`}
                  onClick={() => onPick(token)}
                >
                  <span className="color-swatch-token-badge">{tokenBadgeText(token)}</span>
                </button>
              ))}
            </div>
          </div>
        ) : null
      )}
    </>
  );
}

interface TokenGroup {
  label: string;
  tokens: string[];
}

/** Text tokens first for text nodes (via the same `fillTokensForNode` split
 * `DesignTokensSection` uses), then surface tokens, then any other catalog
 * buckets ("palette") not already shown — deduped, brand-catalog order
 * preserved within each bucket. */
function tokenGroupsForNode(node: Node, brandTokens?: BrandTokenCatalog | null): TokenGroup[] {
  if (!brandTokens) {
    return [];
  }
  const seen = new Set<string>();
  const dedupe = (tokens: string[] | undefined): string[] =>
    (tokens ?? []).filter((token) => {
      if (seen.has(token)) {
        return false;
      }
      seen.add(token);
      return true;
    });

  const groups: TokenGroup[] = [];
  const primaryLabel = node.kind.kind === "text" ? "Text" : "Surface";
  groups.push({ label: primaryLabel, tokens: dedupe(fillTokensForNode(node, brandTokens)) });
  if (node.kind.kind === "text") {
    groups.push({ label: "Surface", tokens: dedupe(brandTokens.surface_tokens) });
  }

  const shownKeys = new Set(["text_tokens", "surface_tokens"]);
  const paletteTokens = Object.entries(brandTokens)
    .filter(([key]) => !shownKeys.has(key))
    .flatMap(([, tokens]) => tokens ?? []);
  groups.push({ label: "Palette", tokens: dedupe(paletteTokens) });

  return groups;
}

function tokenBadgeText(token: string): string {
  const parts = token.split(".");
  return parts[parts.length - 1]?.slice(0, 2).toUpperCase() ?? token.slice(0, 2).toUpperCase();
}

function fillSummaryLabel(fill: Fill): string {
  switch (fill.paint.kind) {
    case "solid":
      return fill.paint.color.kind === "hex" ? fill.paint.color.value : colorToCss(fill.paint.color);
    case "token":
      return `$${fill.paint.token}`;
    case "linear_gradient":
      return `Linear gradient, ${fill.paint.stops.length} stops`;
    case "radial_gradient":
      return `Radial gradient, ${fill.paint.stops.length} stops`;
  }
}

/** True when a destructive single-swatch replace would clobber a fill the
 * control can't faithfully represent: more than one fill layer, or any
 * paint that isn't solid/token. */
export function isGradientGuarded(fills: Fill[]): boolean {
  if (fills.length > 1) {
    return true;
  }
  const paint = fills[0]?.paint;
  return paint ? paint.kind !== "solid" && paint.kind !== "token" : false;
}

function solidHexFill(ownerId: string, hex: string): Fill {
  return {
    id: `paint_${ownerId}_fill`,
    paint: {
      kind: "solid",
      color: {
        kind: "hex",
        value: normalizeHexInput(hex)
      }
    }
  };
}

function hexInputValue(fill: Fill | undefined): string {
  if (fill?.paint.kind === "solid" && fill.paint.color.kind === "hex") {
    return normalizeHexInput(fill.paint.color.value);
  }
  return "#000000";
}

function normalizeHexInput(value: string): string {
  const trimmed = value.trim();
  const sixDigit = /^#[0-9a-fA-F]{6}$/.test(trimmed) ? trimmed : null;
  const eightDigit = /^#[0-9a-fA-F]{8}$/.test(trimmed) ? trimmed.slice(0, 7) : null;
  return (sixDigit ?? eightDigit ?? "#000000").toLowerCase();
}
