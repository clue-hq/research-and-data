import {
  SPACING_STEPS,
  webClassFacets,
} from "../engine/webClassFacets";
import {
  setNodeClassesOp,
  setNodePropsOp,
  type WebNode,
  type WebOperation,
} from "../engine/webDocuments";

/**
 * W3.2: the write adapter — one inspector change event → one engine
 * operation, or null when the change has no sanctioned write (inert/§3
 * controls, unmapped values, wrong node kind). The inverse of
 * `hydrate.ts`'s mappings, and like it, this file cites the contract rows it
 * implements. Facet rewrites go through the engine's real class facets, so
 * "rewrite only your own tokens" holds by construction.
 */

/** §1 row 5 + §6(5): the select label → ramp value (inverse of hydrate's). */
const FONT_SIZE_TO_RAMP: Record<string, string> = {
  "12": "xs",
  "14": "sm",
  "16": "base",
  "18": "lg",
  "20": "xl",
  "24": "2xl",
  "32": "3xl",
};

/** §1 row 6. */
const FONT_WEIGHT_TO_TOKEN: Record<string, string> = {
  Bold: "bold",
  Medium: "medium",
  Regular: "normal",
  "Semi Bold": "semibold",
};

/** §1 row 7. */
const ALIGNMENT_VALUES = new Set(["center", "left", "right"]);

/** Ruling 25: the style select labels → engine `TextVariant` values. */
const TEXT_STYLE_TO_VARIANT: Record<string, string> = {
  Body: "body",
  Display: "display",
  H1: "h1",
  H2: "h2",
  H3: "h3",
  H4: "h4",
  Overline: "overline",
  Small: "small",
};

/** Ruling 26: the line-spacing select IS the facet vocabulary. */
const LINE_SPACING_VALUES = new Set([
  "loose",
  "none",
  "normal",
  "relaxed",
  "snug",
  "tight",
]);

/** R3: a typed padding value snaps to the nearest engine spacing step. */
function nearestSpacingStep(raw: string): string | null {
  const value = Number(raw.trim());
  if (!Number.isFinite(value)) return null;
  let best: string = SPACING_STEPS[0];
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const step of SPACING_STEPS) {
    const distance = Math.abs(Number(step) - value);
    if (distance < bestDistance) {
      best = step;
      bestDistance = distance;
    }
  }
  return best;
}

// ══ W4.4 — container & section schemas ══════════════════════════════════════
// (Lanes B/C append their own schema blocks to this file; keeping each task's
// additions in one labeled block keeps those merges mechanical.)

/** Row 19 (+ row 1 for the page root, itself a container): the kinds whose
 * schema has a sanctioned background-token control in v1. A kind outside this
 * set has no background slot — §5 layout-only fallbacks (embed, unknown kinds)
 * and the 18b icon partition included — so its event is refused rather than
 * written. Row 17's button joins this set with lane B's W4.3. */
const TOKEN_BACKGROUND_KINDS = new Set(["container", "section"]);

export interface InspectorChangeDetail {
  property: string;
  selectionId: string;
  value: unknown;
}

export function inspectorChangeToOperation(
  detail: InspectorChangeDetail,
  node: WebNode,
  pageId: string,
): WebOperation | null {
  const { property } = detail;
  const value = typeof detail.value === "string" ? detail.value : null;
  if (value === null) return null;
  const classes = node.classes ?? "";

  switch (property) {
    case "fontSize": {
      const ramp = FONT_SIZE_TO_RAMP[value];
      if (!ramp) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.textSize.set(classes, ramp),
      );
    }
    case "fontWeight": {
      const token = FONT_WEIGHT_TO_TOKEN[value];
      if (!token) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.fontWeight.set(classes, token),
      );
    }
    case "tokenTextColor": {
      // R2: tokens only. The token label lowercases onto the theme token
      // (the facet excludes size/alignment keywords from the text- family).
      const token = value.trim().toLowerCase();
      if (!token || token.startsWith("#")) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.textColor.set(classes, token),
      );
    }
    // W4.4 (row 19, the row-17 popover pattern): the background token — the
    // `tokenTextColor` case above is its text-color twin and already serves
    // every schema whose Style section exposes one.
    case "tokenBackgroundColor": {
      if (!TOKEN_BACKGROUND_KINDS.has(node.kind)) return null;
      const token = value.trim().toLowerCase();
      if (!token || token.startsWith("#")) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.bgColor.set(classes, token),
      );
    }
    case "horizontalAlignment": {
      if (!ALIGNMENT_VALUES.has(value)) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.textAlign.set(classes, value),
      );
    }
    case "padding.x": {
      const step = nearestSpacingStep(value);
      if (step === null) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.paddingX.set(classes, step),
      );
    }
    case "padding.y": {
      const step = nearestSpacingStep(value);
      if (step === null) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.paddingY.set(classes, step),
      );
    }
    case "textStyle": {
      // Ruling 25: set_node_props replaces the whole text props, so the
      // current content rides along unchanged.
      if (node.kind !== "text") return null;
      const variant = TEXT_STYLE_TO_VARIANT[value];
      if (!variant || node.content === undefined) return null;
      return setNodePropsOp(pageId, node.id, {
        content: node.content,
        kind: "text",
        variant,
      });
    }
    case "lineSpacing": {
      if (!LINE_SPACING_VALUES.has(value)) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.lineHeight.set(classes, value),
      );
    }
    default:
      // Everything else is inert (§3), theme-owned (R1 fonts), owned by a
      // later schema task (W4), or simply unmapped — no operation.
      return null;
  }
}
