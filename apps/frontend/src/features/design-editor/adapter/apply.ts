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

// ══ W4.4 — container & section schemas ══════════════════════════════════════
// (Lanes B/C append their own schema blocks to this file; keeping each task's
// additions in one labeled block keeps those merges mechanical.)

/** Row 19 (+ row 1 for the page root, itself a container): the kinds whose
 * schema has a sanctioned background-token control in v1. A kind outside this
 * set has no background slot — §5 layout-only fallbacks (embed, unknown kinds)
 * and the 18b icon partition included — so its event is refused rather than
 * written. Row 17's button JOINED this set at the lane-B merge (2026-08-19).
 *
 * W4.5 (row 1) adds NO kind: the canvas schema is chosen by node ID
 * (`hydrate.ts::inspectorSelectionFor` returns "canvas" for `page.root`), and
 * `lumen-web` builds every page root as a Container
 * (`crates/lumen-web/src/doc.rs::WebDoc::new`) — so the page background rides
 * "container" here. `apply.test.ts` pins that dependency: narrowing this set
 * to sections would silently kill row 1. */
const TOKEN_BACKGROUND_KINDS = new Set(["button", "container", "section"]);

/** Row 20: the segmented labels → the display facet's values. The engine's
 * `block`/`inline-flex` have no dummy slot and are omitted per §6(5), never
 * invented. Row 40's visibility eye writes the same facet's `hidden`, so the
 * two controls compose instead of fighting over raw class strings. */
const LAYOUT_MODE_TO_DISPLAY: Record<string, string> = {
  Flex: "flex",
  Grid: "grid",
  Hide: "hidden",
};

/** Row 22: the segmented direction values → `flex-direction` (inverse of
 * hydrate's map). */
const DIRECTION_TO_FACET: Record<string, string> = {
  horizontal: "row",
  vertical: "col",
};

// ══ W4.9 — the header visibility eye ════════════════════════════════════════

/** Row 40: the kinds the inspector schemas serve. The eye sits in the header
 * of every one of them, so unlike the per-control guards above it names the
 * whole set rather than a single schema. Deliberately NOT included: the §5
 * layout-only fallback kinds (embed / component / custom_component / anything
 * unmapped), which borrow the container schema without being a schema — the
 * eye refuses them the way row 19's background refuses them, rather than
 * inventing a sanction. The page root needs no mention: the canvas header
 * renders no element actions at all (`elementActions={selection !== "canvas"}`
 * in `web-inspector.tsx`), and W4.5 established the root is unreachable as a
 * selection anyway. */
const VISIBILITY_KINDS = new Set([
  "button",
  "container",
  "icon",
  "image",
  "section",
  "text",
]);

/** Row 40: what the eye remembers between a hide and its un-hide — the
 * display value it displaced, and the node it belongs to. */
export interface VisibilityMemory {
  display: string;
  nodeId: string;
}

/**
 * Row 40: the eye's pre-hide capture, folded into one pure step so the
 * "never guess a display value" rule is unit-testable rather than buried in a
 * hook. Given the memory carried so far and the node the eye just toggled:
 *
 *   • hide → capture the node's REAL current display (nothing to capture when
 *     the node carries no display utility, or is already hidden — the value
 *     would be `hidden` itself);
 *   • un-hide → hand back the captured value ONLY when it belongs to this
 *     node, and clear the memory behind it. A `null` restore means "clear the
 *     display token" so the page's natural/stylesheet display stands; the
 *     adapter never substitutes a plausible-looking `flex`.
 *
 * The memory is a per-session, per-node fact: `useInspectorWrites` holds it in
 * a ref, so it lasts exactly as long as the editor is mounted and dies with a
 * reload — which is precisely the "captured in this session" scope.
 */
export function nextVisibilityMemory(
  memory: VisibilityMemory | null,
  node: WebNode,
  visible: boolean,
): { memory: VisibilityMemory | null; restoreDisplay: string | null } {
  if (!visible) {
    const display = webClassFacets.display.parse(node.classes ?? "");
    return {
      memory:
        display === null || display === "hidden"
          ? null
          : { display, nodeId: node.id },
      restoreDisplay: null,
    };
  }
  return {
    memory: null,
    restoreDisplay:
      memory !== null && memory.nodeId === node.id ? memory.display : null,
  };
}

export interface InspectorChangeDetail {
  property: string;
  selectionId: string;
  value: unknown;
  /** W4.9 (row 40): the display value the eye captured when it hid THIS node
   * in this session (`nextVisibilityMemory`). Absent or null → the un-hide
   * clears the display token instead of restoring an unobserved value. */
  restoreDisplay?: string | null;
}

export function inspectorChangeToOperation(
  detail: InspectorChangeDetail,
  node: WebNode,
  pageId: string,
): WebOperation | null {
  const { property } = detail;
  const classes = node.classes ?? "";

  // W4.4 (row 22): the Wrap segmented reports a BOOLEAN, so it resolves ahead
  // of the string coercion every other control shares.
  if (property === "wrap") {
    if (node.kind !== "section") return null;
    if (typeof detail.value !== "boolean") return null;
    return setNodeClassesOp(
      pageId,
      node.id,
      webClassFacets.flexWrap.set(classes, detail.value ? "wrap" : "nowrap"),
    );
  }

  // W4.9 (row 40): the header eye also reports a BOOLEAN, and writes the very
  // facet W4.4's container segmented writes — going through the facet (never a
  // raw class string) is what makes the two controls compose: a node hidden by
  // the eye hydrates the segmented as "Hide", and un-hiding from either side
  // agrees.
  if (property === "visible") {
    if (!VISIBILITY_KINDS.has(node.kind)) return null;
    if (typeof detail.value !== "boolean") return null;
    return setNodeClassesOp(
      pageId,
      node.id,
      webClassFacets.display.set(
        classes,
        detail.value ? (detail.restoreDisplay ?? null) : "hidden",
      ),
    );
  }

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
    // W4.4 (row 19) + W4.3 (row 17, merge resolution 2026-08-19): the
    // background token — the `tokenTextColor` case above is its text-color
    // twin. The kind guard stays (lane A's reviewed refusal posture: §5
    // layout-only kinds and the 18b icon have no background slot and are
    // refused, never silently written); lane B's button joined the sanctioned
    // set exactly as this guard's docstring anticipated.
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
    // W4.4 (row 20): the container's Flex/Grid/Hide segmented.
    case "layoutMode": {
      if (node.kind !== "container") return null;
      const display = LAYOUT_MODE_TO_DISPLAY[value];
      if (!display) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.display.set(classes, display),
      );
    }
    // W4.4 (row 22): the section's Direction / Gap / Wrap. The dummy gives
    // these three to the section schema alone — container-level direction/
    // gap/wrap is §7 item 1 (future work) with no UI slot decided, so a
    // container event is refused rather than quietly written.
    case "direction": {
      if (node.kind !== "section") return null;
      const facetValue = DIRECTION_TO_FACET[value];
      if (!facetValue) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.direction.set(classes, facetValue),
      );
    }
    case "gap": {
      if (node.kind !== "section") return null;
      // Row 22: gap is the same enumerated step scale the padding boxes use
      // (0,1,2,3,4,6,8,10,12,16,20,24), so a typed value snaps the same way.
      const step = nearestSpacingStep(value);
      if (step === null) return null;
      return setNodeClassesOp(
        pageId,
        node.id,
        webClassFacets.gap.set(classes, step),
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
