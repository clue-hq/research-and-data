import type {
  InspectorPresentationState,
} from "@/features/chat-shell/hooks/use-inspector-controller";
import type { ChatShellInspectorSelection } from "@/features/chat-shell/model/chat-shell";
import { webClassFacets } from "../engine/webClassFacets";
import type { WebNode } from "../engine/webDocuments";

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
 * The radius facet (§1 row 14) is the ONE §8-authorized engine addition and
 * does not exist yet — radius hydration lands with W4.1, not here.
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

/** The dummy labels tokens capitalized ("White", "Primary"); token names pass
 * through with the same first-letter treatment. */
function tokenLabel(token: string): string {
  return token.charAt(0).toUpperCase() + token.slice(1);
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
  const flexWrap = webClassFacets.flexWrap.parse(classes);
  if (flexWrap !== null) {
    state.wrap = flexWrap !== "nowrap";
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

  const objectFit = webClassFacets.objectFit.parse(classes);
  if (objectFit !== null && objectFit in OBJECT_FIT_TO_FILL_MODE) {
    state.fillMode = OBJECT_FIT_TO_FILL_MODE[objectFit];
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

  return state;
}
