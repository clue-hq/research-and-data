import type {
  InspectorBackgroundFill,
  InspectorPresentationState,
} from "@/features/chat-shell/hooks/use-inspector-controller";
import type { ChatShellInspectorSelection } from "@/features/chat-shell/model/chat-shell";
import type {
  Color,
  Dimension,
  ImageFitMode,
  LayoutAnchor,
  Node,
  NodeId,
  Page,
  PageId,
  Paint,
  Scene,
} from "../engine/scene/contracts";
import { isNodePinned } from "../engine/scene/sceneQueries";
import { oklchToHexCss } from "../engine/scene/tokenColors";
import { paletteHex, type ScenePalette } from "./scene-palette";

/**
 * AD2.4: the pure hydration adapter for the SCENE (ad) lane — this file IS the
 * ad-inspector mapping contract's §1 table (docs/specs/ad-editor-integration/
 * ad-inspector-mapping-contract.md), scene node → dummy inspector state. It is
 * the twin of the website lane's `adapter/hydrate.ts`.
 *
 * kind → schema (§1.4 + OQ-1/OQ-6, §5): text→text, image→image,
 * auto_layout→auto-layout, a plain frame→auto-layout with its Auto Layout
 * section suppressed, rect→rectangle, ellipse→ellipse, group→group, the page's
 * ROOT frame→canvas, and line/vector/instance→`null` (§5: they have no schema;
 * a canvas hit resolves to the nearest representable ancestor — AD2.5 — and a
 * layer-row click on one is a no-op).
 *
 * Two facts about the stored bytes drive the value mapping (AD2.2's harvest
 * header states both, and both are easy to get wrong from memory):
 *   • `computed` is null on EVERY stored node — the engine solves layout in the
 *     renderer and never persists geometry back. Position X/Y therefore read
 *     `transform` (a PINNED node reads its page-space `absolute_box`, mirroring
 *     the design editor's own `ObjectSection` `pinnedBox` rule), never a stored
 *     computed box.
 *   • `CornerRadii`'s field order is TL, TR, **BR, BL** while the serialized
 *     key order is TL, TR, BL, BR — the radius mapping reads fields by name.
 *
 * Only facts hydrate. A value the dummy has no slot for is omitted so the
 * caller's default stands; a value the node truthfully lacks (no stroke, no
 * fill) hydrates as the honest none/0 rather than leaving a fixture default
 * that would MISSTATE the node (the website lane's R3 truthful-value rule).
 */

/** The ColorControl's `none` state, spelled the way the shared inspector
 * default already spells it (`DEFAULT_STATE.strokeColor === "none"`). */
export const COLOR_NONE = "none";

/**
 * RULING A9 (2026-08-21): the stroke a colour or a width commit MINTS on a
 * node that has none — upstream's own two defaults. The WRITE is where the
 * ruling is stated in full (`scene-apply.ts`, with both upstream citations);
 * the pair lives HERE because the panel needs the identical numbers.
 *
 * A9 makes the Stroke row's two fields move TOGETHER: a colour on a strokeless
 * node gives the document a 1px stroke, and a width on one gives it a teal
 * paint. A successful write does not remount the inspector (§4 / the AD3.2
 * keying rule), so nothing else would re-read them — the row would go on
 * saying "none / 0" over a node that now visibly has a stroke, which is the
 * "a field may not display a value the document does not have" rule this
 * lane's reviews have already applied twice. `mintedStrokeDisplay` is the one
 * decision both halves re-seed from.
 */
export const MINTED_STROKE_WIDTH = 1;
export const MINTED_STROKE_HEX = "#256c70";

/**
 * A typed field's number, or `null`. The ad inspector's numeric fields are
 * free-text `InspectorInput`s firing per KEYSTROKE, so "", "-" and "1e" are
 * ordinary intermediate events, not commits: an empty field is mid-edit, never
 * a request to write 0 (JS's `Number("") === 0` would say otherwise).
 * Upstream's `NumberField` does not need this — it is an `<input
 * type="number">` and never sees the intermediate text.
 *
 * It lives beside `numberText` (its inverse) rather than in `scene-apply.ts`,
 * which is where it was written: A9 gave the panel a second caller, and
 * scene-apply already imports this file, so importing back would close a
 * cycle. The function itself is unchanged.
 */
export function finiteNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/**
 * A9: the WIDTH the Stroke row must read once a colour has landed on it —
 * `"1"` when the row was showing no stroke at all, `null` when it was not (the
 * node already has a stroke, so the write keeps that width).
 *
 * The condition is the ROW's displayed colour, which is exactly the write's
 * condition seen from the panel: hydration states `none` for a node with no
 * stroke and the paint's own colour for one with any stroke, including a
 * stored zero-width stroke — which the write CLEARS rather than mints, and
 * whose colour is therefore correctly not `none`. The width box's own text is
 * deliberately not consulted: the write does not consult it either.
 */
export function mintedStrokeWidth(color: string): string | null {
  return color === COLOR_NONE ? numberText(MINTED_STROKE_WIDTH) : null;
}

/**
 * A9, the mirror: the COLOUR the Stroke row must read once a width has landed
 * on it — upstream's default when the row was showing no stroke and the typed
 * width really mints one, `null` otherwise.
 *
 * The width IS consulted here, because this direction's write depends on it: a
 * `0` clears and an unparseable one is refused, and neither mints a colour.
 */
export function mintedStrokeColor(color: string, width: string): string | null {
  const typed = finiteNumber(width);
  return color === COLOR_NONE && typed !== null && typed > 0
    ? MINTED_STROKE_HEX
    : null;
}

/**
 * Ruling 14 (2026-08-20): `InspectorPresentationState` has no fields for the
 * co-founder's new ad schemas — the AD0.1 delta shipped them as static
 * scaffolding and never touched `use-inspector-controller.ts`. These are the
 * hydrated values that have a designed control but no state field yet; AD2.7 /
 * AD4.B decide their final home when the controller is bound. Every field is
 * optional, following the same only-facts-hydrate discipline as the
 * `Partial<InspectorPresentationState>` half.
 *
 * The ruling enumerated six (`opacity`, `widthMode`, `heightMode`,
 * `widthFixed`, `heightFixed`, `valignDisabled`). Implementing the brief's
 * value-mapping rows surfaced six more with the same gap — `grow`, `alignX`,
 * `alignY` (§1.4's Auto Layout section), `title` (§1.0's header) and
 * `customWidth`/`customHeight` (§1.1's Custom preset) — recorded in the AD2.4
 * report as an extension of the same ruling, not a new decision.
 *
 * AD4.0 step 1 settles the first two of those: binding §1.1's Custom W/H
 * inputs to the controller gave `customWidth`/`customHeight` a real state
 * field, so they now live in `InspectorPresentationState` beside their
 * siblings — the "final home" the ruling deferred — and have left this list.
 * The rest are still AD4.B's to place.
 */
export interface SceneInspectorExtraState {
  /** §1.4's Align X label (Start|Center|End|Space between|Stretch). */
  alignX?: string;
  /** §1.4's Align Y label. */
  alignY?: string;
  /** §1.4's Grow input. */
  grow?: string;
  /** §1.4/OQ-2: Fixed | Hug | Fill. */
  heightMode?: SceneSizeMode;
  /** §1.4/OQ-2: the "Height fixed" input — empty unless the mode is Fixed. */
  heightFixed?: string;
  /** §1.4/OQ-3: opacity as the displayed percent (engine 0–1 × 100). */
  opacity?: string;
  /** §1.0: the header title — the real node's display name. */
  title?: string;
  /** §1.2: the V-alignment toggles are disabled while the height mode is hug. */
  valignDisabled?: boolean;
  /** §1.4/OQ-2: Fixed | Hug | Fill. */
  widthMode?: SceneSizeMode;
  /** §1.4/OQ-2: the "Width fixed" input — empty unless the mode is Fixed. */
  widthFixed?: string;
}

export type SceneSizeMode = "Fill" | "Fixed" | "Hug";

/** What one selected scene node hydrates into: the dummy's own state plus the
 * ruling-14 fields it does not carry yet. */
export type SceneInspectorState = Partial<InspectorPresentationState> &
  SceneInspectorExtraState;

export interface SceneSchemaSelection {
  selection: ChatShellInspectorSelection;
  /** OQ-1: plain Frame renders the auto-layout schema with its Auto Layout
   * section suppressed. */
  suppressAutoLayoutSection: boolean;
}

/** §1.1: the page's root frame — the node whose fill the canvas schema's
 * Background edits (founder ruling; the page-background property is NOT the
 * edit target). Null when the page is unknown or its children open on
 * something other than a frame, in which case the Background is the
 * ColorControl none state and its writes are no-ops.
 *
 * Also the AD4.0 WRITE half's answer to "which node do I write?"
 * (`scene-apply.ts::backgroundTarget` calls this rather than restating it):
 * the write must land on the very node the panel read. */
export function rootFrameId(scene: Scene, pageId: PageId): NodeId | null {
  const page = scene.pages[pageId];
  if (!page) {
    return null;
  }
  for (const childId of page.children) {
    if (scene.nodes[childId]?.kind.kind === "frame") {
      return childId;
    }
  }
  return null;
}

/**
 * §1.4 kind → schema (see the file header). `rootFrameId` decides the canvas
 * case: the artboard's own frame IS the canvas selection, so a plain (nested)
 * frame is the only frame that reaches OQ-1's suppressed auto-layout schema.
 *
 * Returns `null` for §5's unrepresented kinds (line / vector / instance) —
 * there is no schema to show, and callers resolve to a representable ancestor
 * instead of inventing one.
 */
export function sceneSelectionFor(
  node: Node,
  rootFrameId: NodeId | null,
): SceneSchemaSelection | null {
  if (rootFrameId !== null && node.id === rootFrameId) {
    return { selection: "canvas", suppressAutoLayoutSection: false };
  }
  switch (node.kind.kind) {
    case "text":
      return { selection: "text", suppressAutoLayoutSection: false };
    case "image":
      return { selection: "image", suppressAutoLayoutSection: false };
    case "auto_layout":
      return { selection: "auto-layout", suppressAutoLayoutSection: false };
    case "frame":
      // OQ-1: Shape + Stroke + Layout + Arrange + Layers, no Auto Layout.
      return { selection: "auto-layout", suppressAutoLayoutSection: true };
    case "rect":
      return { selection: "rectangle", suppressAutoLayoutSection: false };
    case "ellipse":
      return { selection: "ellipse", suppressAutoLayoutSection: false };
    case "group":
      // OQ-6: the group schema already omits Shape/Stroke.
      return { selection: "group", suppressAutoLayoutSection: false };
    default:
      // §5: line / vector / instance have no v1 schema.
      return null;
  }
}

/** §2 row 2: the nine named weights, exactly as the ad text schema lists them
 * (`components/image-inspector.tsx` `FONT_WEIGHT_OPTIONS`). A weight outside
 * the ramp has no option to select, so it is omitted rather than invented. */
const FONT_WEIGHT_LABELS: Record<number, string> = {
  100: "100 Thin",
  200: "200 Extra Light",
  300: "300 Light",
  400: "400 Regular",
  500: "500 Medium",
  600: "600 Semi Bold",
  700: "700 Bold",
  800: "800 Extra Bold",
  900: "900 Black",
};

/** §2 row 4: dummy labels on engine behaviours. */
const IMAGE_FIT_LABELS = {
  contain: "Fit",
  cover: "Fill",
  crop: "Crop",
} satisfies Record<ImageFitMode, string>;

/** §1.4: the Align X/Y select vocabulary. */
const LAYOUT_ANCHOR_LABELS = {
  center: "Center",
  end: "End",
  space_between: "Space between",
  start: "Start",
  stretch: "Stretch",
} satisfies Record<LayoutAnchor, string>;

/** §1.2 row 6: the engine's `VerticalAlign` in the dummy's vocabulary. */
const VALIGN_LABELS = {
  bottom: "bottom",
  center: "middle",
  top: "top",
} satisfies Record<"bottom" | "center" | "top", InspectorPresentationState["verticalAlignment"]>;

/** §2 row 1: the three ratified presets with their corrected sizes, matched on
 * SIZE NUMBERS (the labels mirror `image-inspector.tsx` `SIZE_PRESETS`). The
 * engine's own `PagePreset::LinkedinAd` is the 1200×627 banner, so a page's
 * stored `preset` field cannot answer this question — the numbers do.
 *
 * Exported for the AD4.0 WRITE half (`scene-apply.ts`), which reads the table
 * the other way (label → numbers). One table, not two: a relabel that orphaned
 * the write while hydration kept matching is exactly the drift this file's
 * "hydrate is the authority on every vocabulary" rule exists to prevent. */
export const SIZE_PRESETS = [
  { height: 1200, label: "Linkedin square (1:1) - 1200x1200", width: 1200 },
  { height: 1350, label: "Instagram portrait (4:5) - 1080x1350", width: 1080 },
  { height: 1920, label: "Story (9:16) - 1080x1920", width: 1080 },
] as const;

/** The select's fourth option — the one that names no size and reveals the W/H
 * inputs instead. Exported for the vocabulary guard that cross-checks this
 * table against the dummy's own option list. */
export const CUSTOM_SIZE_PRESET = "Custom";

/** Engine numbers are floats (`1056.0`); the inputs are strings. A non-finite
 * value has nothing truthful to show, so it shows nothing. */
function numberText(value: number): string {
  return Number.isFinite(value) ? String(value) : "";
}

/**
 * §1.1: what the Custom W/H boxes must READ once the size SELECT beside them
 * has committed `label` — the same fact `hydrateSceneCanvasState` states for a
 * loaded page, asked of a preset the user just picked instead.
 *
 * It exists because a successful write deliberately does not remount the
 * inspector (§4 / the AD3.2 keying rule), so nothing re-hydrates those two
 * boxes when their SIBLING control resizes the page: they would keep their
 * mount-time seed and display a size the document no longer has (proven in the
 * browser — a page taken from Custom 1100x1600 to the LinkedIn square still
 * offered 1100/1600 when Custom was re-opened). Round 1's finding 2 rule
 * applies unchanged: a field may not display a number the document does not
 * have.
 *
 * `null` for "Custom" and for any label the select does not offer — those name
 * no size and resize nothing, so there is nothing to re-seed. That is exactly
 * the write adapter's own null contract for the same input, read off the same
 * table.
 */
export function customSizeForPreset(
  label: string,
): { height: string; width: string } | null {
  const preset = SIZE_PRESETS.find((candidate) => candidate.label === label);
  if (!preset) {
    return null;
  }
  return { height: numberText(preset.height), width: numberText(preset.width) };
}

/** Ruling A15.2: ONE commit the Background section makes — the property and
 * the value, exactly as `useInspectorController.setValue` takes them. */
export type BackgroundCommit =
  | { property: "backgroundColor"; value: string }
  | { property: "backgroundFill"; value: InspectorBackgroundFill };

/**
 * §1.1 row 2 / Ruling A15.2: what ONE change of the Background fill control
 * commits — the whole handler's decision, pure, so the component holds none of
 * it (the `customSizeForPreset` precedent from AD4.0 step 1, which likewise
 * dispatches AND keeps a sibling control honest inside one handler).
 *
 * Two browser-proven defects live here, and they are one bug: the fill OBJECT
 * in controller state is seeded once at mount and does not track the writes
 * that follow, so a mode switch commits a stale seed.
 *
 *   • SOLID → GRADIENT discarded the colour the user had just set (green
 *     reverted to the pre-edit navy) because the object's stops still carried
 *     the mount-time colour. Fixed by re-seeding every stop from `solidColor`
 *     — which IS what the swatch is showing — when leaving solid. Hydrate's
 *     own `solidFill` seeds stops from the solid colour for exactly this
 *     reason; this keeps that true after the first edit, not only at mount.
 *   • GRADIENT → SOLID wrote nothing at all, leaving the select saying
 *     "Solid", the swatch saying something else, and the artboard still
 *     rendering the gradient. Fixed by committing `backgroundColor` with the
 *     OUTGOING paint's first stop — a colour the document really has — which
 *     is the row that carries a colour (the fill object does not; see
 *     `scene-apply.ts`'s `backgroundPaint` `solid` case).
 *
 * EXACTLY ONE DOCUMENT VERSION per switch, which is the property that matters:
 * the two commits the gradient→solid case returns are one no-op and one write.
 * `backgroundFill` with `type: "solid"` maps to NO operation by contract (it
 * carries no colour), so the pair collapses to a single write in the adapter —
 * proven by a test that runs both commits through it and counts operations.
 * Stop positions, counts and the angle ride through untouched.
 *
 * ── R3b (AD4.0 step 3): the swatch value may not be a COLOUR ──────────────
 * Both re-seeds above read a value off the panel and commit it as a colour,
 * and after step 2 that value is only *sometimes* a hex: a token paint states
 * its `$name` (truthfully — `paintState`), and a fill-less frame states `none`.
 * Committing those produced the review's stuck state — the select flipped to
 * the new mode while the write adapter correctly refused stops of
 * `$text.inverse`, leaving the panel claiming a gradient over a still-token-
 * filled artboard, with no way back short of a remount.
 *
 * So each re-seed now goes through `paletteHex`: a hex verbatim, a brand token
 * resolved through the document's kit, and `null` for anything else — and
 * `null` returns NO COMMITS AT ALL, which refuses the mode switch itself
 * (the select is driven by `state.backgroundFill`, so committing nothing
 * leaves it where it was). Refusing beats fabricating, and beats flipping a
 * control whose write cannot land.
 *
 * The switch a resolved token DOES allow detaches that token — a gradient is
 * not a token binding — which is the same informed §1.6 trade a raw hex makes.
 */
export function backgroundFillCommits(
  current: InspectorBackgroundFill,
  next: InspectorBackgroundFill,
  solidColor: string,
  /** R3b: the document's brand vocabulary, for resolving a token swatch to the
   * colour it paints. Absent — no kit, a fetch that failed — simply means a
   * token cannot be resolved, and a switch that needs one is refused. */
  palette?: ScenePalette | null,
): BackgroundCommit[] {
  if (next.type === current.type) {
    // A stop colour, a stop position, the angle — not a mode switch.
    return [{ property: "backgroundFill", value: next }];
  }
  if (next.type === "solid") {
    // The outgoing gradient's first stop. A stopless gradient cannot come from
    // this control (2–6 stops); if one ever arrives, the swatch's own value is
    // the only other thing on screen, so nothing is invented.
    const hex = paletteHex(palette, current.stops[0]?.color ?? solidColor);
    if (hex === null) {
      return [];
    }
    return [
      { property: "backgroundFill", value: next },
      { property: "backgroundColor", value: hex },
    ];
  }
  if (current.type === "solid") {
    const hex = paletteHex(palette, solidColor);
    if (hex === null) {
      return [];
    }
    return [
      {
        property: "backgroundFill",
        // Positions and count survive; only the colours are re-stated, because
        // while solid there is exactly one colour on screen.
        value: {
          ...next,
          stops: next.stops.map((stop) => ({ ...stop, color: hex })),
        },
      },
    ];
  }
  // linear ↔ radial: both are gradients, so the stops are already the ones on
  // screen and nothing needs re-seeding.
  return [{ property: "backgroundFill", value: next }];
}

/**
 * A `Color` as the picker's swatch value: hex verbatim (upper-cased, the
 * casing `ColorControl` itself commits), oklch converted through the engine's
 * own converter, and a color TOKEN kept as its `$name` — resolving that needs
 * the brand kit, which the scene carries only as a `{id, version}` ref (same
 * posture as the website lane's token fields).
 */
function colorText(color: Color): string {
  switch (color.kind) {
    case "hex":
      return color.value.toUpperCase();
    case "oklch":
      return oklchToHexCss(color.l, color.c, color.h, color.alpha);
    case "token":
      return color.token;
  }
}

/** The solid state of the Background/Fill control. `type` is the load-bearing
 * part — it selects the solid tab, whose swatch reads the sibling color field.
 * The stops are inert while solid; they are seeded from the same color so that
 * switching to a gradient starts from what is on screen (and never from an
 * empty list, which the control's add/remove-stop maths assumes cannot
 * happen). */
function solidFill(hex: string): InspectorBackgroundFill {
  return {
    angle: 0,
    stops: [
      { color: hex, position: 0 },
      { color: hex, position: 100 },
    ],
    type: "solid",
  };
}

const NONE_FILL: InspectorBackgroundFill = solidFill("#000000");

interface PaintState {
  fill: InspectorBackgroundFill;
  /**
   * Rulings A15.1 / A16 (2026-08-21): what a SINGLE swatch must display for
   * this paint — always a fact the document carries, never a fixture.
   *
   * There used to be a `color` field stated only for a paint that IS a solid
   * hex, which left every swatch beside a gradient or a token showing the
   * shared `DEFAULT_STATE` seed (`#00F59B`). Browser-proven: with a radial
   * gradient on the frame, picking "Solid" showed the select saying "Solid",
   * the swatch saying a colour from two edits earlier, and the artboard
   * rendering the gradient — three answers at once. A gradient's FIRST STOP is
   * the truthful answer (and the exact inverse of `solidFill` below, which
   * already seeds a gradient's stops from the solid colour so a mode switch
   * "starts from what is on screen"); a token paint states its `$name`, which
   * is what the stroke row already did.
   *
   * A16 pointed every single-swatch row here — background, text and stroke —
   * so `color` had no readers left and is gone. `token` stays: it feeds the
   * separate `tokenTextColor`/`tokenBackgroundColor` fields, which are a
   * different question from what the swatch displays.
   */
  swatch: string;
  /** The token NAME, when the paint is token-bound. */
  token?: string;
}

/** §1.6: one `Paint` → the ColorControl/BackgroundFillControl state. Gradient
 * stop positions are the engine's 0–1 as the control's 0–100 percent. */
function paintState(paint: Paint | undefined): PaintState {
  if (!paint) {
    return { fill: NONE_FILL, swatch: COLOR_NONE };
  }
  switch (paint.kind) {
    case "solid": {
      const hex = colorText(paint.color);
      return { fill: solidFill(hex), swatch: hex };
    }
    case "token":
      return { fill: NONE_FILL, swatch: paint.token, token: paint.token };
    case "linear_gradient":
    case "radial_gradient": {
      const stops = paint.stops.map((stop) => ({
        color: colorText(stop.color),
        position: Math.round(stop.position * 100),
      }));
      return {
        fill: {
          angle: paint.kind === "linear_gradient" ? paint.angle : 0,
          stops,
          type:
            paint.kind === "linear_gradient" ? "linear-gradient" : "radial-gradient",
        },
        // A stopless gradient (storable, unreachable from this control) has no
        // colour to state, so it states none rather than inventing one.
        swatch: stops[0]?.color ?? COLOR_NONE,
      };
    }
  }
}

/** §1.4/OQ-2: `Dimension` → the mode select + the "fixed" input, which the
 * schema shows only in Fixed mode (hence the empty string everywhere else). */
function dimensionState(
  dimension: Dimension,
  computed: number | null,
): { fixed: string; mode: SceneSizeMode } {
  switch (dimension.kind) {
    case "fixed":
      return { fixed: numberText(dimension.value), mode: "Fixed" };
    case "hug":
      return { fixed: "", mode: "Hug" };
    case "fill":
      // §5: fill WEIGHTS have no v1 input, so only the mode hydrates.
      return { fixed: "", mode: "Fill" };
    case "token":
      // UNCOVERED (AD2.2 §fixtures): no harvested node carries a token
      // Dimension — a real ad had no plausible one, and AD2.2's law forbids
      // hand-writing a shape to manufacture coverage. The documented §5
      // compromise stands: token sizing has no dummy slot, so it displays as
      // Fixed at the solved size. `computed` is null on every stored node, so
      // in practice that reads as an empty input until the renderer's solved
      // geometry is threaded in.
      return {
        fixed: computed === null ? "" : numberText(computed),
        mode: "Fixed",
      };
  }
}

/**
 * Hydrate the dummy ad inspector's state from one selected scene node.
 *
 * Every schema's values are hydrated for every node — the same rule the
 * website lane's radius row settled (R-B1): the dummy's defaults are fixtures
 * that lie about a real node, and the SCHEMA decides what renders, so a value
 * that a given schema happens not to show costs nothing while a missing one
 * leaves an invented number on screen.
 */
export function hydrateSceneInspectorState(
  node: Node,
  scene: Scene,
): SceneInspectorState {
  const state: SceneInspectorState = {};

  // §1.0 header.
  state.title = node.name ?? `${node.kind.kind} ${node.id}`;
  state.locked = node.locked;

  // §1.4 Layout: position, rotation, opacity, size modes.
  // A pinned node's page-space box is authoritative for the human-owned
  // geometry (the editor's own `ObjectSection` rule); everything else reads
  // the transform, because `computed` is null at rest.
  const pinnedBox = isNodePinned(scene, node.id)
    ? (node.absolute_box ?? node.computed?.layout_bounds ?? null)
    : null;
  state.position = {
    x: numberText(pinnedBox ? pinnedBox.x : node.transform.x),
    y: numberText(pinnedBox ? pinnedBox.y : node.transform.y),
  };
  state.rotation = numberText(node.transform.rotation);
  // OQ-3: the engine's 0–1 is displayed as a percent.
  state.opacity = String(Math.round(node.opacity * 100));

  const width = dimensionState(
    node.size.width,
    node.computed?.layout_bounds.width ?? null,
  );
  const height = dimensionState(
    node.size.height,
    node.computed?.layout_bounds.height ?? null,
  );
  state.widthMode = width.mode;
  state.widthFixed = width.fixed;
  state.heightMode = height.mode;
  state.heightFixed = height.fixed;
  // §1.2: the V-alignment toggles are dead while the box hugs its text.
  state.valignDisabled = height.mode === "Hug";

  // §1.6 fill. A text node's fill is its TEXT color; every other kind's is the
  // Shape/Background fill.
  const fill = paintState(node.fills[0]?.paint);
  if (node.kind.kind === "text") {
    // Ruling A16: the text swatch states `swatch` too. A token-filled headline
    // (the harvest's own `$text.inverse`) used to show the shared
    // `DEFAULT_STATE` seed `#00F59B` — telling the user the text is mint green
    // while it is brand-token coloured, on a control that ACCEPTS a write
    // (§1.6's ratified detach), which is worse than the gradient case behind
    // §1.2's guard. Same fabrication as the Background swatch, two lines away.
    // Display only: §1.2's write gating is untouched.
    state.textColor = fill.swatch;
    if (fill.token !== undefined) state.tokenTextColor = fill.token;
  } else {
    // Ruling A15.1: the Background swatch states `swatch`, never a fixture.
    // This branch hydrates the CANVAS schema too — a selected root frame routes
    // there (`sceneSelectionFor`) and is hydrated as a node — so it must state
    // exactly what `hydrateSceneCanvasState` does, or the panel would differ
    // between the two ways of opening it.
    state.backgroundColor = fill.swatch;
    if (fill.token !== undefined) state.tokenBackgroundColor = fill.token;
    state.backgroundFill = fill.fill;
  }

  // §1.2/§1.4 Stroke. No stroke is truthfully none/0 — the dummy's default
  // width of 1 would state a hairline this node does not have.
  // UNCOVERED (AD2.2 §fixtures) for TEXT specifically: no harvested text node
  // carries a stroke (an outlined ad headline was not plausible). The mapping
  // is one path for every kind and is proven on `auto_row_copy`'s real stroke.
  const stroke = node.strokes[0];
  if (stroke) {
    // Ruling A16: `swatch` here too. It already spelled `color ?? token ??
    // none`, so solid and token strokes are unchanged; the one it fixes is a
    // GRADIENT stroke, which used to read "none" on a node that visibly has a
    // stroke. Display only — the width beside it still states the real width.
    state.strokeColor = paintState(stroke.paint).swatch;
    state.strokeWidth = numberText(stroke.width);
  } else {
    state.strokeColor = COLOR_NONE;
    state.strokeWidth = "0";
  }

  // §1.3 Shape radii. Read BY NAME: the contract's field order is TL, TR, BR,
  // BL while the serialized key order is TL, TR, BL, BR. `all` is the uniform
  // value, or empty when the corners differ (no single number is true).
  const { bottom_left, bottom_right, top_left, top_right } = node.corner;
  const uniform =
    top_left === top_right && top_right === bottom_right && bottom_right === bottom_left;
  state.radius = {
    all: uniform ? numberText(top_left) : "",
    bottomLeft: numberText(bottom_left),
    bottomRight: numberText(bottom_right),
    topLeft: numberText(top_left),
    topRight: numberText(top_right),
  };

  // §1.2 Typography (text only).
  if (node.kind.kind === "text") {
    const text = node.kind;
    state.fontFamily = text.font_family;
    state.fontSize = numberText(text.font_size);
    const weight = FONT_WEIGHT_LABELS[text.font_weight];
    if (weight) state.fontWeight = weight;
    // §1.2 row 5: `TextAlign` passes straight through — the ad schema's fourth
    // toggle IS `justify` (§2 row 2), so nothing is dropped at this seam.
    state.horizontalAlignment = text.align;
    state.verticalAlignment = VALIGN_LABELS[text.valign ?? "top"];
  }

  // §1.3 Image mode.
  if (node.kind.kind === "image") {
    const fit = node.asset_placement?.fit;
    if (fit) state.fillMode = IMAGE_FIT_LABELS[fit];
  }

  // §1.4 Auto Layout. Direction/wrap live on the node KIND; gap/grow/padding/
  // align live on `Node.layout` — so they hydrate independently.
  if (node.kind.kind === "auto_layout") {
    state.direction = node.kind.direction === "row" ? "horizontal" : "vertical";
    state.wrap = node.kind.wrap;
  }
  if (node.layout) {
    const layout = node.layout;
    state.gap = numberText(layout.gap);
    state.grow = numberText(layout.grow);
    const [top, right, bottom, left] = layout.padding;
    state.padding = {
      bottom: numberText(bottom),
      left: numberText(left),
      right: numberText(right),
      top: numberText(top),
    };
    if (layout.align_x) state.alignX = LAYOUT_ANCHOR_LABELS[layout.align_x];
    if (layout.align_y) state.alignY = LAYOUT_ANCHOR_LABELS[layout.align_y];
  }

  return state;
}

/**
 * What the ad inspector hydrates for ONE selection — the router over the two
 * hydrators below, so the panel reads the same values however it was opened.
 *
 * AD4.0 step 2. The canvas schema has TWO entry states (`sceneSelectionFor`
 * routes the page's ROOT FRAME to it), and a node hydration cannot state
 * §1.1's PAGE rows: with the artboard selected, the Size select fell back to
 * the dummy's own default preset and the Custom boxes to `1200`/`1200`,
 * whatever size the page really was — the same "a field may not display a
 * number the document does not have" rule that AD4.0's review already applied
 * twice. So a selected root frame hydrates the page's canvas state FIRST and
 * its own node state over it; the node wins every field they share (its title,
 * its lock, its own fill), and the page contributes only the rows a node has
 * no answer for.
 *
 * Every other selection is unchanged: a node hydrates as a node, the empty
 * selection as the page.
 */
export function hydrateSceneSelectionState(
  scene: Scene,
  pageId: PageId | null,
  node: Node | null,
): SceneInspectorState | null {
  if (!node) {
    return pageId ? hydrateSceneCanvasState(scene, pageId) : null;
  }
  const nodeState = hydrateSceneInspectorState(node, scene);
  if (!pageId || node.id !== rootFrameId(scene, pageId)) {
    return nodeState;
  }
  return { ...hydrateSceneCanvasState(scene, pageId), ...nodeState };
}

/**
 * §1.1: the canvas (page) schema — the state an EMPTY selection hydrates.
 *
 * Two rows: the size preset, matched on the page's pixel size (with the Custom
 * W/H pair always stating that same pixel size, whether or not a preset
 * matched), and the Background, which is the ROOT FRAME's first fill (founder
 * ruling — the page's own `background` property is not the edit target and is
 * not read here). With no root frame the Background is the ColorControl none
 * state and its writes are no-ops (the null contract).
 */
export function hydrateSceneCanvasState(
  scene: Scene,
  pageId: PageId,
): SceneInspectorState {
  const state: SceneInspectorState = {};

  const page = scene.pages[pageId];
  if (page) {
    const { height, width } = pagePixelSize(page);
    const preset = SIZE_PRESETS.find(
      (candidate) => candidate.width === width && candidate.height === height,
    );
    state.sizePreset = preset ? preset.label : CUSTOM_SIZE_PRESET;
    // ALWAYS, including when a preset matched (AD4.0 review finding, proven in
    // the browser): the W/H boxes are revealed by picking "Custom" in the
    // select, which happens on a page that matched a preset a moment earlier.
    // Filling them only in the no-preset case left that reveal showing the
    // shared dummy default (1200x1200) on, say, a 1080x1920 page — a size the
    // page does not have, which the user then edits from. The write is the
    // exact inverse of this function, so this function may never display a
    // number the page cannot state.
    state.customWidth = numberText(width);
    state.customHeight = numberText(height);
  }

  const frameId = page ? rootFrameId(scene, pageId) : null;
  const root = frameId ? scene.nodes[frameId] : null;
  const fill = paintState(root?.fills[0]?.paint);
  // Ruling A15.1: `swatch`, not `color` — a gradient-filled frame must show the
  // colour the document HAS (its first stop), not the dummy's `#00F59B` seed.
  state.backgroundColor = fill.swatch;
  if (fill.token !== undefined) state.tokenBackgroundColor = fill.token;
  state.backgroundFill = fill.fill;

  return state;
}

/**
 * A page's size in PIXELS — the only unit §1.1's W/H inputs speak.
 *
 * An authored-px page is stored in the engine's canonical form: a `pt` box
 * with the authored px size preserved on `size.source` and the export size on
 * `output.raster`. The raster output is preferred (it is already integral px
 * and is what the artifact actually exports at), then the px source, and only
 * then the box itself.
 *
 * Exported for the AD4.0 write half: a Custom W/H edit changes ONE dimension
 * and must keep the other exactly as displayed, so the write reads the size
 * through this same function rather than off the raw `pt` box. Those two
 * numbers differ whenever the raster rounded a fractional authored px.
 */
export function pagePixelSize(page: Page): { height: number; width: number } {
  const raster = page.size.output?.raster;
  if (raster) {
    return { height: raster.height_px, width: raster.width_px };
  }
  const source = page.size.source;
  if (source && source.unit === "px") {
    return { height: source.height, width: source.width };
  }
  return { height: page.size.height, width: page.size.width };
}
