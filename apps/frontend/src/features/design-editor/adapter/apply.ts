import {
  SPACING_STEPS,
  webClassFacets,
} from "../engine/webClassFacets";
import {
  buildWebButtonProps,
  setNodeClassesOp,
  setNodePropsOp,
  webNodeButtonAction,
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
 *
 * W4.2 (lane B) adds the image schema's writes: the Mode select (row 13), the
 * shared Link section (rows 11/15 — image props and the link form of a button,
 * ruling R-B4), and the five radius fields (row 14, ruling R-B1 + founder
 * ruling F2). A props write always resends the node's FULL props, because
 * `set_node_props` replaces them wholesale.
 *
 * W4.3 (lane B) adds the button schema's writes: the Style select (row 16 —
 * the `variant` prop, rebuilt through the engine's button-props builder so a
 * command button stays a command button) and the background color token
 * (row 17 — the `bgColor` facet, mirror of `tokenTextColor`).
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

/** §1 row 13 (W4.2): the Mode select's labels → the `objectFit` facet. "Tile"
 * is dropped from the options (§2 delta) and has no engine value, so it — like
 * any label outside this map — writes nothing. */
const FILL_MODE_TO_OBJECT_FIT: Record<string, string> = {
  Fit: "contain",
  Fill: "cover",
  Stretch: "fill",
};

/** §1 row 16 (W4.3): the button style select's labels → the engine `variant`
 * prop (inverse of hydrate's map). "Critical" is dropped from the options (§2
 * delta) and has no engine value, so it — like the engine's own `outline`/
 * `link` variants, which have no dummy slot — writes nothing. */
const BUTTON_STYLE_TO_VARIANT: Record<string, string> = {
  Primary: "primary",
  Secondary: "secondary",
  Transparent: "ghost",
};

/** §1 row 14 (W4.2): the five radius properties → their engine facet. Each
 * family owns only its own tokens, so a write here can never disturb another
 * corner, an unmodeled side utility (`rounded-t-*`) or any other token. */
const RADIUS_FACETS: Record<string, (typeof webClassFacets)["radius"]> = {
  "radius.all": webClassFacets.radius,
  "radius.bottomLeft": webClassFacets.radiusBottomLeft,
  "radius.bottomRight": webClassFacets.radiusBottomRight,
  "radius.topLeft": webClassFacets.radiusTopLeft,
  "radius.topRight": webClassFacets.radiusTopRight,
};

/** The four corner families, in the order the F2 chain clears them. */
const RADIUS_CORNER_FACETS = [
  webClassFacets.radiusTopLeft,
  webClassFacets.radiusTopRight,
  webClassFacets.radiusBottomLeft,
  webClassFacets.radiusBottomRight,
];

/** §1 row 14 / ruling R-B1: the radius field's commit vocabulary. A numeric
 * value authors the arbitrary pixel token (`12` → `rounded-[12px]`); an empty
 * field clears the family; ANYTHING else — the named scale values the field
 * displays verbatim (`lg`, `full`), a unit/decimal/negative form — is no write
 * at all, so a hydrated named radius survives an untouched blur. Only an
 * explicit `0` may ever author `rounded-[0px]`. */
type RadiusCommit =
  | { kind: "clear" }
  | { kind: "ignore" }
  | { kind: "set"; value: string };

const NUMERIC_RADIUS = /^\d+$/;

function radiusCommit(raw: string): RadiusCommit {
  const typed = raw.trim();
  if (typed === "") return { kind: "clear" };
  if (!NUMERIC_RADIUS.test(typed)) return { kind: "ignore" };
  return { kind: "set", value: `[${typed}px]` };
}

/**
 * §1 rows 11/15 + ruling R-B4: one link-field edit → the node's FULL props.
 * `set_node_props` replaces the props wholesale, so a partial write would
 * clobber the rest (§4's hard integrity guarantee — alt text (37) and the
 * asset binding round-trip unchanged); every unedited field is therefore
 * resent byte-identical from the current node, and a node missing the fields
 * that identify it is refused rather than written with invented values.
 *
 * A COMMAND-form button (`show_modal`/`close`) gets no write from either link
 * field: dialog actions are agent-only (§4 row 36) and the inspector edits
 * link mode only (row 15). Container `href` exists engine-side but has no
 * ruled UI, so every other kind is a no-op too.
 */
function linkPropsOperation(
  node: WebNode,
  pageId: string,
  edit: { href?: string | null; newTab?: boolean },
): WebOperation | null {
  const href =
    edit.href !== undefined
      ? edit.href
      : typeof node.href === "string"
        ? node.href
        : null;
  const newTab = edit.newTab !== undefined ? edit.newTab : node.new_tab === true;

  if (node.kind === "image") {
    if (typeof node.asset_id !== "string") return null;
    return setNodePropsOp(pageId, node.id, {
      alt: node.alt ?? "",
      asset_id: node.asset_id,
      href,
      kind: "image",
      new_tab: newTab,
    });
  }
  if (node.kind === "button") {
    if (webNodeButtonAction(node) !== "link") return null;
    if (typeof node.label !== "string" || typeof node.variant !== "string") {
      return null;
    }
    return setNodePropsOp(
      pageId,
      node.id,
      buildWebButtonProps({
        action: "link",
        command_target: "",
        href: href ?? "",
        label: node.label,
        new_tab: newTab,
        variant: node.variant,
      }),
    );
  }
  return null;
}

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
  const classes = node.classes ?? "";

  // Rows 11/15: the new-tab checkbox is the one control whose committed value
  // is a BOOLEAN, so it is decided before the string gate below (every other
  // mapped control commits a string and an unexpected type is no write).
  if (property === "openInNewTab") {
    if (typeof detail.value !== "boolean") return null;
    return linkPropsOperation(node, pageId, { newTab: detail.value });
  }

  const value = typeof detail.value === "string" ? detail.value : null;
  if (value === null) return null;

  if (property in RADIUS_FACETS) {
    // Row 14 (ruling R-B1 + founder ruling F2). No node-kind guard: only the
    // image schema renders the Shape section, but a radius write is a pure
    // class rewrite valid on any node that carries classes (the button's
    // `rounded-md` hydrates the same field).
    const commit = radiusCommit(value);
    if (commit.kind === "ignore") return null;
    if (property === "radius.all" && commit.kind === "set") {
      // F2 (founder, 2026-08-18, binding): the all-corners write CLEARS the
      // four per-corner overrides — chained on ONE classes string so it lands
      // as a single operation. Each facet removes only its own family, so the
      // unmodeled side utilities and every unrelated token survive verbatim.
      let next = classes;
      for (const corner of RADIUS_CORNER_FACETS) {
        next = corner.set(next, null);
      }
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.radius.set(next, commit.value),
      );
    }
    // Per corner, and the empty all-corners commit: clear/set exactly one
    // family (an empty `radius.all` leaves the separately-owned corner
    // overrides alone).
    return setNodeClassesOp(
      pageId,
      node.id,
      RADIUS_FACETS[property].set(
        classes,
        commit.kind === "clear" ? null : commit.value,
      ),
    );
  }

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
    case "tokenBackgroundColor": {
      // Row 17 (R2: tokens only) — the mirror of `tokenTextColor`. No node-kind
      // guard: a background-token write is a pure class rewrite valid on any
      // node carrying classes (the button schema renders the chip today; the
      // canvas/container schemas reuse the same property).
      const token = value.trim().toLowerCase();
      if (!token || token.startsWith("#")) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.bgColor.set(classes, token),
      );
    }
    case "buttonLabel": {
      // Row 16: button only. `set_node_props` replaces the props wholesale, so
      // the whole payload is rebuilt from the node through the engine builder —
      // which keeps a COMMAND button in command form (command/command_target)
      // and a link button in link form (href/new_tab), byte-identical apart
      // from the variant. A button missing its label is refused rather than
      // written with an invented one.
      if (node.kind !== "button") return null;
      const variant = BUTTON_STYLE_TO_VARIANT[value];
      if (!variant || typeof node.label !== "string") return null;
      return setNodePropsOp(
        pageId,
        node.id,
        buildWebButtonProps({
          action: webNodeButtonAction(node),
          command_target: node.command_target ?? "",
          href: node.href ?? "",
          label: node.label,
          new_tab: node.new_tab === true,
          variant,
        }),
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
    case "fillMode": {
      // Row 13: image only — the Mode select is the image schema's Fill
      // section, and no other kind has an object-fit meaning.
      if (node.kind !== "image") return null;
      const fit = FILL_MODE_TO_OBJECT_FIT[value];
      if (!fit) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.objectFit.set(classes, fit),
      );
    }
    case "url": {
      // Rows 11/15 (ruling R-B4): an empty/whitespace field is an honest
      // clear (href null), not an empty-string link.
      return linkPropsOperation(node, pageId, {
        href: value.trim() === "" ? null : value,
      });
    }
    default:
      // Everything else is inert (§3), theme-owned (R1 fonts), owned by a
      // later schema task (W4), or simply unmapped — no operation.
      return null;
  }
}
