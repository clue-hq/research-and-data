import type {
  InspectorPresentationState,
} from "@/features/chat-shell/hooks/use-inspector-controller";
import type { ChatShellInspectorSelection } from "@/features/chat-shell/model/chat-shell";
// The adapter may import data-layer constants (the presentation-component
// import ban stops at `features/**/components/**`); `data/design-bff.ts` is the
// single source of truth for the authenticated design mount.
import { DESIGN_API_BFF_PREFIX } from "../data/design-bff";
import { webClassFacets } from "../engine/webClassFacets";
import type { WebNode } from "../engine/webDocuments";
// W4.0: the capitalize-first token label is one shared rule — the picker's
// option labels use the same one, so hydrated state and options agree.
import { tokenLabel } from "./theme-options";

/**
 * W2.2: the pure hydration adapter — this file IS the frozen mapping
 * contract's §1 table (docs/specs/website-editor-integration/
 * web-inspector-mapping-contract.md), node → dummy inspector state.
 *
 * kind → schema: text→text, image→image, button→button, icon→icon
 * (layout-only, 18b), container→container, section→section, the page root→
 * canvas; embed/component/custom_component and any unknown kind → the §5
 * layout-only fallback (container schema, layout/padding sections only).
 *
 * Facet values come from the engine's real class facets (never re-parsed
 * here); only contract-mapped values hydrate — an unmapped value (e.g. a
 * `text-5xl` beyond the §6(5) size ramp, a `font-thin` outside the weight
 * select) is OMITTED so the dummy default stands rather than lying.
 *
 * Color tokens hydrate as token NAMES (`tokenTextColor`/`tokenBackgroundColor`
 * — §1 row 17's fields, capitalized like the dummy's labels). Resolving a
 * token to its hex needs the server-compiled web theme and lands with the
 * color write flow (W4); the hex fields stay untouched here.
 *
 * The radius facets (§1 row 14) are the ONE §8-authorized engine addition
 * (W4.1); W4.2 hydrates them here.
 */

/** §1 row 5 + §6(5): the size select's option set ends at 3xl/32 ("drop 13
 * only; 32 maps to 3xl"). Ramp values beyond it have no UI slot. */
const TEXT_SIZE_TO_FONT_SIZE: Record<string, string> = {
  xs: "12",
  sm: "14",
  base: "16",
  lg: "18",
  xl: "20",
  "2xl": "24",
  "3xl": "32",
};

/** §1 row 6. Engine values outside the select (thin/extralight/extrabold/
 * black) are omitted. */
const FONT_WEIGHT_TO_LABEL: Record<string, string> = {
  normal: "Regular",
  medium: "Medium",
  semibold: "Semi Bold",
  bold: "Bold",
};

/** §1 row 7 (justify/start/end unexposed). */
const TEXT_ALIGN_TO_ALIGNMENT: Record<
  string,
  InspectorPresentationState["horizontalAlignment"]
> = {
  left: "left",
  center: "center",
  right: "right",
};

/** §1 row 20 (block/inline-flex unexposed). */
const DISPLAY_TO_LAYOUT_MODE: Record<
  string,
  InspectorPresentationState["layoutMode"]
> = {
  flex: "Flex",
  grid: "Grid",
  hidden: "Hide",
};

/** §1 row 13 (Tile dropped; none/scale-down unexposed). */
const OBJECT_FIT_TO_FILL_MODE: Record<string, string> = {
  contain: "Fit",
  cover: "Fill",
  fill: "Stretch",
};

/** §1 row 16 (Critical dropped from options; no engine `critical` variant). */
const BUTTON_VARIANT_TO_STYLE: Record<string, string> = {
  primary: "Primary",
  secondary: "Secondary",
  ghost: "Transparent",
};

/** §1 row 22: `flex-col` is the vertical direction. */
const DIRECTION_TO_INSPECTOR: Record<
  string,
  InspectorPresentationState["direction"]
> = {
  row: "horizontal",
  col: "vertical",
};

/** Ruling 25 (W3.2 §2 addition): engine `TextVariant` → the style select's
 * labels (inverse of apply.ts's map). */
const VARIANT_TO_TEXT_STYLE: Record<string, string> = {
  body: "Body",
  display: "Display",
  h1: "H1",
  h2: "H2",
  h3: "H3",
  h4: "H4",
  overline: "Overline",
  small: "Small",
};

/** Ruling 26 (W3.2 §2 addition): the line-spacing select IS the facet
 * vocabulary. */
const LINE_SPACING_VALUES = new Set([
  "loose",
  "none",
  "normal",
  "relaxed",
  "snug",
  "tight",
]);

/** §1 row 14: an arbitrary pixel radius is authored `rounded-[8px]` and shown
 * as the bare number. Only this exact shape unwraps — `[50%]`, `[2rem]` and
 * the named scale display verbatim. */
const ARBITRARY_PIXEL_VALUE = /^\[(\d+)px\]$/;

/** §1 row 14 display vocabulary. An absent facet (parse null — including the
 * bare `rounded`, which the engine owns for removal but never reports) is the
 * designed empty string, NEVER "0": a "0" would read as an authored zero
 * radius and let an untouched field write `rounded-[0px]` on the next edit. */
function radiusDisplayValue(value: string | null): string {
  if (value === null) {
    return "";
  }
  const pixels = ARBITRARY_PIXEL_VALUE.exec(value);
  return pixels === null ? value : pixels[1];
}

export interface InspectorSchemaSelection {
  selection: ChatShellInspectorSelection;
  /** True → only the layout/padding sections are live (18b icons, §5
   * unknown-kind fallback). */
  layoutOnly: boolean;
}

/** kind → schema per the contract (see file header). `pageRootId` decides the
 * canvas case: the page root is the canvas selection regardless of its kind. */
export function inspectorSelectionFor(
  node: WebNode,
  pageRootId: string,
): InspectorSchemaSelection {
  if (node.id === pageRootId) {
    return { selection: "canvas", layoutOnly: false };
  }
  switch (node.kind) {
    case "text":
      return { selection: "text", layoutOnly: false };
    case "image":
      return { selection: "image", layoutOnly: false };
    case "button":
      return { selection: "button", layoutOnly: false };
    case "icon":
      return { selection: "icon", layoutOnly: true };
    case "container":
      return { selection: "container", layoutOnly: false };
    case "section":
      return { selection: "section", layoutOnly: false };
    default:
      // §5: embed, component, custom_component, and anything unmapped show
      // Layout(-padding) only; the container schema carries those sections.
      return { selection: "container", layoutOnly: true };
  }
}

/** Hydrate the dummy inspector's presentation state from a document node and
 * its authored classes. Only facts hydrate; anything absent or unmapped is
 * omitted so the caller's defaults stand. */
export function hydrateInspectorState(
  node: WebNode,
  classes: string,
): Partial<InspectorPresentationState> {
  const state: Partial<InspectorPresentationState> = {};

  const textColor = webClassFacets.textColor.parse(classes);
  if (textColor !== null) {
    state.tokenTextColor = tokenLabel(textColor);
  }
  const bgColor = webClassFacets.bgColor.parse(classes);
  if (bgColor !== null) {
    state.tokenBackgroundColor = tokenLabel(bgColor);
  }

  const textSize = webClassFacets.textSize.parse(classes);
  if (textSize !== null && textSize in TEXT_SIZE_TO_FONT_SIZE) {
    state.fontSize = TEXT_SIZE_TO_FONT_SIZE[textSize];
  }
  const fontWeight = webClassFacets.fontWeight.parse(classes);
  if (fontWeight !== null && fontWeight in FONT_WEIGHT_TO_LABEL) {
    state.fontWeight = FONT_WEIGHT_TO_LABEL[fontWeight];
  }
  const textAlign = webClassFacets.textAlign.parse(classes);
  if (textAlign !== null && textAlign in TEXT_ALIGN_TO_ALIGNMENT) {
    state.horizontalAlignment = TEXT_ALIGN_TO_ALIGNMENT[textAlign];
  }

  const display = webClassFacets.display.parse(classes);
  if (display !== null) {
    if (display in DISPLAY_TO_LAYOUT_MODE) {
      state.layoutMode = DISPLAY_TO_LAYOUT_MODE[display];
    }
    // Row 40: the visibility eye is the `hidden` display value.
    state.visible = display !== "hidden";
  }

  const direction = webClassFacets.direction.parse(classes);
  if (direction !== null && direction in DIRECTION_TO_INSPECTOR) {
    state.direction = DIRECTION_TO_INSPECTOR[direction];
  }
  const gap = webClassFacets.gap.parse(classes);
  if (gap !== null) {
    state.gap = gap;
  }
  // Row 22 + W4.4 (controller ruling, 2026-08-18): an ABSENT `flex-wrap`
  // utility is not an unknown value — CSS's own default is `nowrap`, so the
  // section's Wrap control states that truthfully as "No". This is R3's
  // truthful-value pattern (the padding boxes' truthful zeros), NOT §6(5)'s
  // omission rule (which is for values the dummy has no slot for, e.g. an
  // off-ramp font size, where the dummy default rightly stands). Leaving the
  // dummy's `wrap: true` default in place would misstate the page.
  // Scoped to the section schema because it alone ships a Wrap control —
  // container-level wrap is §7 item 1 (future work) with no UI slot.
  const flexWrap = webClassFacets.flexWrap.parse(classes);
  if (flexWrap !== null) {
    state.wrap = flexWrap !== "nowrap";
  } else if (node.kind === "section") {
    state.wrap = false;
  }

  // R3: two axis boxes. A present axis with the other absent means the other
  // axis is truthfully zero (no utility = no padding), never the dummy's
  // fixture default.
  const paddingX = webClassFacets.paddingX.parse(classes);
  const paddingY = webClassFacets.paddingY.parse(classes);
  if (paddingX !== null || paddingY !== null) {
    const x = paddingX ?? "0";
    const y = paddingY ?? "0";
    state.padding = { bottom: y, left: x, right: x, top: y };
  }

  // §1 row 14 (ruling R-B1): the whole 5-field record hydrates for EVERY node,
  // not just the image schema that renders the Shape section. The dummy's
  // default ({ all: "0", corners: "4" }) is a fixture that lies about real
  // nodes, so a partial record would leave invented corners on screen.
  state.radius = {
    all: radiusDisplayValue(webClassFacets.radius.parse(classes)),
    bottomLeft: radiusDisplayValue(webClassFacets.radiusBottomLeft.parse(classes)),
    bottomRight: radiusDisplayValue(
      webClassFacets.radiusBottomRight.parse(classes),
    ),
    topLeft: radiusDisplayValue(webClassFacets.radiusTopLeft.parse(classes)),
    topRight: radiusDisplayValue(webClassFacets.radiusTopRight.parse(classes)),
  };

  const objectFit = webClassFacets.objectFit.parse(classes);
  if (objectFit !== null && objectFit in OBJECT_FIT_TO_FILL_MODE) {
    state.fillMode = OBJECT_FIT_TO_FILL_MODE[objectFit];
  }

  // W3.2 §2 additions: line spacing (ruling 26) and, below with the node
  // props, the text style select (ruling 25).
  const lineHeight = webClassFacets.lineHeight.parse(classes);
  if (lineHeight !== null && LINE_SPACING_VALUES.has(lineHeight)) {
    state.lineSpacing = lineHeight;
  }
  if (node.kind === "text" && typeof node.variant === "string") {
    const label = VARIANT_TO_TEXT_STYLE[node.variant];
    if (label) state.textStyle = label;
  }

  // Node props: the button style select (row 16) and the link fields
  // (rows 11/15 — image and button share the href/new_tab pair).
  if (node.kind === "button" && typeof node.variant === "string") {
    if (node.variant in BUTTON_VARIANT_TO_STYLE) {
      state.buttonLabel = BUTTON_VARIANT_TO_STYLE[node.variant];
    }
  }
  if (node.kind === "button" || node.kind === "image") {
    if (typeof node.href === "string") {
      state.url = node.href;
      state.openInNewTab = node.new_tab === true;
    }
  }

  // §1 row 12 (ruling R-B5): the Fill section's preview shows THIS node's
  // asset, not the dummy's stock png. The bytes route is authenticated, so the
  // src is the BFF mount (never a design-API origin); an image without an
  // asset keeps the dummy default rather than pointing at a 404.
  if (node.kind === "image" && typeof node.asset_id === "string" && node.asset_id) {
    state.imagePreviewSrc = `${DESIGN_API_BFF_PREFIX}/assets/${encodeURIComponent(node.asset_id)}/bytes`;
  }

  return state;
}
