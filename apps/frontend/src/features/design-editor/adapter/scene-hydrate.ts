import type {
  InspectorBackgroundFill,
  InspectorPresentationState,
  InspectorSizeMode,
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
  Unit,
} from "../engine/scene/contracts";
import { defaultLayoutProps } from "../engine/scene/operations";
import {
  isNodeFreezableOnGesture,
  isNodePinned,
  nodePageSpaceBox,
  parentInfoForNode,
} from "../engine/scene/sceneQueries";
import { oklchToHexCss, type KitTokenMaps } from "../engine/scene/tokenColors";
import { resolvedTextFields, textTypographyResolves } from "../engine/scene/renderAdapter";
import { sceneAssetPassthroughUrl } from "./scene-canvas-view";
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
 *     computed box. RULING C9-P2 adds one exception, and only where the LIVE
 *     scene has been solved: a SOLVER-MANAGED node states its solved
 *     parent-relative offset (`solvedManagedOffset`), because that is the frame
 *     the C-9 freeze bakes and therefore the frame its write lands in.
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
 * ruling is stated in full (`scene-apply.ts`, with both upstream citations,
 * importing these two constants); they live HERE beside the hydration that
 * reads the minted stroke back out of the document.
 *
 * A9 makes the Stroke row's two fields move TOGETHER: a colour on a strokeless
 * node gives the document a 1px stroke, and a width on one gives it a teal
 * paint. AD4.R made the display half structural: the panel DISPLAYS the minted
 * scene by live derivation — the accepted document arrives in the same React
 * batch as the write and hydration states both fields from it — so the row
 * cannot go on saying "none / 0" over a node that now visibly has a stroke.
 * The mint is stated once, on the write side; nothing re-seeds a panel copy.
 */
export const MINTED_STROKE_WIDTH = 1;
export const MINTED_STROKE_HEX = "#256c70";

/**
 * A typed field's number, or `null`. The ad inspector's numeric fields are
 * free-text `InspectorInput`s, so "", "-" and "1e" reach the adapter as
 * ordinary text that names no number: an empty field is a cleared box, never a
 * request to write 0 (JS's `Number("") === 0` would say otherwise). AD4.R-6
 * moved these fields from per-keystroke writes to commit-on-blur/Enter, which
 * narrows how often the adapter sees a half-typed value but does not change
 * the contract — an emptied box still commits `""`, and this is what refuses
 * it. Upstream's `NumberField` does not need this — it is an `<input
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
 * A vocabulary lookup that cannot INHERIT — every `Record` lookup in this lane
 * goes through it.
 *
 * `TABLE[key]` finds `Object.prototype`'s own members for a key like
 * `constructor`, `toString` or `valueOf`: a FUNCTION, which is `!== undefined`,
 * so a `=== undefined` guard passes and the row proceeds with a value its
 * vocabulary does not contain. On the write side that reaches the engine as
 * `fit: <Function>`, which `JSON.stringify` drops — silently CLEARING the field
 * a label outside the vocabulary was supposed to leave alone. On the read side
 * it puts a function into inspector state.
 *
 * Neither is reachable from the selects, which offer only their own options —
 * but a stored document is JSON and its strings are not checked by the compile-
 * time unions these tables are keyed on, and the null contract is not a
 * function of what the UI happens to offer. One helper rather than a guard per
 * site, because Lane B adds several more of these tables.
 */
export function vocabulary<Value>(
  table: Readonly<Record<string, Value>>,
  key: string,
): Value | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/** `fields.tsx:174` `roundForEditor`, ported at the two sites upstream applies
 * it: the stroke width it stores, and the corner radius (through
 * `normalizeCornerRadius`). It lives HERE for `finiteNumber`'s own reason —
 * `radiusCommit`/`radiusCommitText` below need it and hydration states the
 * numbers it produces, while scene-apply (its other caller, for the stroke
 * width) already imports this file, so importing back would close a cycle. */
export function roundForEditor(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/**
 * §1.3 Radius / RULING A28: the number a radius commit WRITES for this text, or
 * `null` when it writes nothing.
 *
 * The one production caller is `scene-apply.ts`'s `radius.*` row, which takes
 * the number. `RadiusControls`' scene branch used to be the second, taking
 * `radiusCommitText` below to re-state the four corner boxes after a commit;
 * AD4.R-7 deleted that mirror (the boxes project the live document instead), so
 * the two rules can no longer disagree because there is only one. They did
 * disagree: the mirror asked the dummy's integer regex (`NUMERIC_RADIUS`,
 * `^\d+$`), so a fractional radius wrote all four corners while the boxes went
 * on showing the old numbers, and every re-type of one of those numbers
 * compared equal and was swallowed (browser-proven — it blocked restoring a
 * document by hand).
 *
 * The rule is `finiteNumber`'s, plus §1.3's refusal of a negative radius
 * (upstream folds one to 0; the null contract refuses instead — `scene-apply.ts`
 * says why), plus upstream's own rounding.
 */
export function radiusCommit(raw: string): number | null {
  const typed = finiteNumber(raw);
  return typed === null || typed < 0 ? null : roundForEditor(typed);
}

/**
 * A28: the canonical spelling of the number a radius commit puts in the
 * document, or `null` when the commit writes nothing.
 *
 * It is `numberText` of the written number, i.e. EXACTLY what
 * `hydrateSceneInspectorState` states for that corner on the next read. It was
 * written for the panel mirror AD4.R-7 deleted, and survives **test-side
 * only** (`scene-hydrate.test.ts`'s A28 vocabulary, `scene-apply.test.ts`'s
 * A31 chain): the canonical statement that hydration's spelling is the write's
 * own, which is now the only spelling a box can show. That is stronger than
 * echoing the user's own text back: `007` and `12.3456789` are accepted commits
 * whose documents hold `7` and `12.346`, and a box repeating the typed spelling
 * would be stating a number the document does not have.
 */
export function radiusCommitText(raw: string): string | null {
  const written = radiusCommit(raw);
  return written === null ? null : numberText(written);
}

/**
 * A9: the WIDTH a colour commit lands beside itself — `"1"` when the row was
 * showing no stroke at all, `null` when it was not (the node already has a
 * stroke, so the write keeps that width).
 *
 * AD4.R-6 deleted the panel mirror that consumed this: the Stroke row displays
 * the minted scene by live derivation, so no component re-seeds a width. It is
 * consumed by TESTS ONLY now, and kept as the canonical statement of A9's
 * numbers in the panel's own vocabulary, beside the `MINTED_STROKE_*`
 * constants the write (`scene-apply.ts`) owns and applies.
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
 * A9, the other direction: the COLOUR a width commit lands beside itself —
 * upstream's default when the row was showing no stroke and the typed width
 * really mints one, `null` otherwise. Test-only for the same reason as
 * `mintedStrokeWidth` above, and kept for the same one.
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
 *
 * AD4.B step 1 settles the rest of the CONTROLS the same way: binding §1.4's
 * Layout section gave `opacity`, `widthMode`/`heightMode`,
 * `widthFixed`/`heightFixed` (and, unbound until step 2, `grow`/`alignX`/
 * `alignY`) real state fields, so they have left this list too. What remains is
 * exactly what is NOT a control and therefore never needed one: the header's
 * text and one display fact.
 */
export interface SceneInspectorExtraState {
  /** genad2 Task 6: the UNIT §1.1's Custom W/H boxes are stating — `mm` on an
   * A4 page, `px` on the seeded ad. A display fact with no control (the panel
   * shows it as the inputs' inert `suffix`, the idiom the Rotation `°` and
   * Opacity `%` rows already use); changing a page's unit is page setup, which
   * the design agent owns, so there is deliberately no unit selector here. */
  customSizeUnit?: Unit;
  /** §1.0: the header title — the real node's display name. */
  title?: string;
  /** §1.2: the V-alignment toggles are disabled while the height mode is hug. */
  valignDisabled?: boolean;
  /** Bound font values cannot be edited until this document's kit resolves. */
  typographyUnavailable?: boolean;
}

/** §1.4/OQ-2's three display labels. ONE statement of the vocabulary, in the
 * inspector's own model (this file already imports that module), so the panel
 * and the adapter cannot drift apart on the spelling. */
export type SceneSizeMode = InspectorSizeMode;

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
const FONT_WEIGHT_LABELS: Record<string, string> = {
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

/**
 * §1.4 Auto Layout: the label ONE align axis reads — always a label, never
 * `undefined` (ruling L10, extended).
 *
 * `align_x`/`align_y` are OPTIONAL in the wire format (`contracts.ts:470-471`),
 * so an anchor can arrive absent (or, from a malformed payload, unusable). The
 * Align X/Y selects are BOUND rows, and the AD4.R rule for a bound row is that
 * hydration states it for every selection that displays it: leaving it absent
 * lets `DEFAULT_STATE`'s scaffolding seeds ("Space between"/"Center" — anchors
 * the dummy invented, which no document ever said) stand over a real node.
 *
 * The fallback is the engine's own `defaultLayoutProps()` anchor for that axis,
 * which is exactly what the write half's `scene-apply.ts::storedAnchor` carries
 * for an absent one — so the displayed anchor and the anchor a commit restates
 * for the untouched axis cannot disagree.
 *
 * `vocabulary` still does the refusing: a garbled or prototype-inherited key is
 * never SERVED as a label, it just resolves to the honest default instead of
 * leaving the row unstated.
 */
function anchorLabel(
  stored: LayoutAnchor | undefined,
  axis: "align_x" | "align_y",
): string {
  const label = stored ? vocabulary(LAYOUT_ANCHOR_LABELS, stored) : undefined;
  return label ?? LAYOUT_ANCHOR_LABELS[defaultLayoutProps()[axis] ?? "start"];
}

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

/** Ruling A15.2: ONE commit the Background section makes — the property and
 * the value, exactly as `useInspectorController.setValue` takes them. */
export type BackgroundCommit =
  | { property: "backgroundColor"; value: string }
  | { property: "backgroundFill"; value: InspectorBackgroundFill };

/**
 * §1.1 row 2 / Ruling A15.2: what ONE change of the Background fill control
 * commits — the whole handler's decision, pure, so the component holds none of
 * it: one handler that dispatches AND keeps a sibling control honest.
 *
 * Two browser-proven defects live here, and they were one bug. Their original
 * premise — the fill OBJECT in controller state is seeded once at mount and
 * does not track the writes that follow, so a mode switch commits a stale seed
 * — is RETIRED on the ad lane by AD4.R: under live hydration the fill object
 * tracks the document, so the values this function reads off the panel are the
 * document's own. What survives is the function itself, unchanged and still
 * needed: it is the pure decision for WHICH writes a mode switch dispatches,
 * because the two paints are different rows and a switch between them is not a
 * single property change.
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
   * shared `DEFAULT_STATE` seed. Browser-proven: with a radial
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

/**
 * §1.4 Dimensions (AD4.B step 1): the size an axis HAS — the number the W/H box
 * shows — or `null` when the document states none.
 *
 * `null` is reachable and is the honest answer: a hug or fill axis has no
 * stored size, and `computed` (the solver's box) is null on every node AT REST,
 * so a stored-and-not-yet-solved hug node truthfully has no width to show. The
 * live engine scene carries the solved bounds, which is where the number comes
 * from in the running panel.
 *
 * EXPORTED because the WRITE side asks the same question twice: a W/H commit's
 * inverse, and — the one that would otherwise drift — the Width/Height mode
 * select's Fixed arm, which must adopt the very number the box is showing. The
 * MVP editor substitutes a hardcoded 120 there (`fields.tsx::fixedDimensionValue`);
 * this lane refuses instead, the way the radius row refuses where upstream
 * folds to 0, so the panel can never write a size the user was not shown.
 */
export function dimensionSize(
  dimension: Dimension,
  computed: number | null,
): number | null {
  if (dimension.kind === "fixed") {
    return roundForEditor(dimension.value);
  }
  return computed === null ? null : roundForEditor(computed);
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
 * RULING C9-P2 / AD4.R — the number a SOLVER-MANAGED node's Position X/Y row
 * must state: its SOLVED offset inside its container, or `null` when the page
 * carries no solve to read.
 *
 * A managed child's stored `transform` is a dead number — the solver places it,
 * and the harvest's own `text_headline`/`group_proof` both sit at (0,0) while
 * the laid-out row puts them elsewhere. That was harmless while the panel
 * refused every geometry write on such a node; C-9 makes the write LAND, and it
 * lands in the frame the freeze bakes — `child solved box − container solved
 * box` (`editing.rs:1906-1910`), which is what this returns. Displaying the
 * stored (0,0) while committing into the baked frame would move the node by its
 * whole solved offset (~708px on the harvested ad) in a space the panel never
 * showed: display and write would disagree, which AD4.R forbids.
 *
 * Both boxes are required. The child's comes from `nodePageSpaceBox` (the same
 * solved geometry the canvas drag reads); the container's is read explicitly
 * rather than through `parentComputedOrigin`, whose (0,0)-for-an-unsolved-parent
 * answer would silently turn a page-space box into a "parent-relative" offset.
 * With either missing, the caller keeps the stored transform — the honest
 * pre-C-9 display for a page the renderer has not solved yet.
 *
 * No rounding: the bake subtracts raw solved coordinates, so the row states the
 * exact number the freeze will write.
 */
function solvedManagedOffset(
  scene: Scene,
  node: Node,
): { x: number; y: number } | null {
  const box = nodePageSpaceBox(scene, node.id);
  if (!box) {
    return null;
  }
  const parentInfo = parentInfoForNode(scene, node.id);
  if (!parentInfo || parentInfo.parent.kind !== "node") {
    return null;
  }
  const container = scene.nodes[parentInfo.parent.id]?.computed?.layout_bounds;
  if (!container) {
    return null;
  }
  return { x: box.x - container.x, y: box.y - container.y };
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
  tokenMaps?: KitTokenMaps | null,
  effectiveNode?: Node | null,
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
  // RULING C9-P2: a node the SOLVER places (the `isNodeFreezableOnGesture`
  // class — the very predicate `panelWriteIntent` and the canvas grab ask, so
  // the display can never disagree with which nodes freeze-then-write) states
  // the solved offset the C-9 freeze bakes, not its dead stored transform.
  // Null when the page carries no solve: the pre-C-9 transform display stands.
  const managedOffset = isNodeFreezableOnGesture(scene, node.id)
    ? solvedManagedOffset(scene, node)
    : null;
  const positionBox = pinnedBox ?? managedOffset;
  state.position = {
    x: numberText(positionBox ? positionBox.x : node.transform.x),
    y: numberText(positionBox ? positionBox.y : node.transform.y),
  };
  state.rotation = numberText(node.transform.rotation);
  // OQ-3: the engine's 0–1 is displayed as a percent.
  state.opacity = String(Math.round(node.opacity * 100));

  const computedWidth = node.computed?.layout_bounds.width ?? null;
  const computedHeight = node.computed?.layout_bounds.height ?? null;
  const width = dimensionState(node.size.width, computedWidth);
  const height = dimensionState(node.size.height, computedHeight);
  // §1.4 Dimensions: the W/H boxes are shown in EVERY mode, so they state the
  // size the node has rather than the Fixed-only input beside them — which is
  // empty on a hug or fill axis, where the scaffolding's invented `100` used to
  // stand. Unconditional, like every other Layout key (the header rule above):
  // a truthfully-unsolved axis states the honest empty string.
  const widthSize = dimensionSize(node.size.width, computedWidth);
  const heightSize = dimensionSize(node.size.height, computedHeight);
  state.width = widthSize === null ? "" : numberText(widthSize);
  state.height = heightSize === null ? "" : numberText(heightSize);
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
    // `DEFAULT_STATE` seed — telling the user the text is the seed colour
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
    // Rung A: the STORED content, verbatim. `text_transform` is a paint-time
    // concern (the engine uppercases when it draws, not when it stores), so the
    // row must state what a commit will replace, never what the canvas shows.
    state.content = text.content;
    state.typographyUnavailable = !textTypographyResolves(text, tokenMaps);
    const styled = resolvedTextFields(text, tokenMaps ?? { typography: {}, numbers: {} });
    state.fontFamily = styled.fontFamily;
    state.fontSize = numberText(styled.fontSize);
    const weight = vocabulary(FONT_WEIGHT_LABELS, String(styled.fontWeight));
    if (weight) state.fontWeight = weight;
    // §1.2 row 5: `TextAlign` passes straight through — the ad schema's fourth
    // toggle IS `justify` (§2 row 2), so nothing is dropped at this seam.
    state.horizontalAlignment = text.align;
    // A stored `valign` outside the engine's own three is not a fact, so it
    // states nothing and the caller's default stands. Assigning the `undefined`
    // that `vocabulary` returns would be WORSE than not assigning: the state is
    // merged with a spread, where an explicit `undefined` key beats the default
    // rather than falling back to it.
    const valign = vocabulary(VALIGN_LABELS, text.valign ?? "top");
    if (valign) state.verticalAlignment = valign;
  }

  // §1.3 Image mode.
  if (node.kind.kind === "image") {
    const fit = node.asset_placement?.fit;
    const mode = fit ? vocabulary(IMAGE_FIT_LABELS, fit) : undefined;
    if (mode) state.fillMode = mode;
    // §1.3 row 1 (AD4.A step 2): the Fill section's thumbnail shows THIS node's
    // own asset — the website lane's ruling R-B5 (`adapter/hydrate.ts:299-305`),
    // ad-side, and the same rule as every other control on this panel: a
    // control may not display something the document does not have. The dummy's
    // stock png was showing a stranger's photograph on every real ad image, and
    // it is also what a FAILED upload has to fall back to, so binding it is
    // part of making the upload row honest rather than a separate polish.
    //
    // The URL is the CANVAS's own resolver (`sceneAssetPassthroughUrl`) — the
    // public, content-addressed `/asset-store/{digest}` passthrough the
    // artboard already paints from — so the thumbnail and the artboard can
    // never disagree about which bytes this node carries, and no second route
    // is introduced. An asset with no usable digest resolves to null and keeps
    // the dummy default, exactly as the web lane keeps it for an asset-less
    // image: an honest placeholder beats a src that can only 404.
    const preview = sceneAssetPassthroughUrl(scene.assets, node.kind.asset_id);
    if (preview) state.imagePreviewSrc = preview;
    // §1.3 row 2 (AD4.A step 3): the Alt-text box. TWO fields can carry the
    // description and upstream reads both, in this order —
    // `asset_placement.alt_text ?? ImageNode.alt ?? ""`
    // (`ImageInspectorSection.tsx:61`). They are genuinely different facts: the
    // node's `alt` is its own authored description and the placement's is the
    // one a placement stamped, so an image with no `alt_text` legitimately
    // displays its `alt`. `scene-apply.ts::effectiveAltText` states the same
    // expression, which is what makes re-committing the displayed text a
    // no-op rather than a document version stating nothing new.
    //
    // ASSIGNED UNCONDITIONALLY, unlike `fillMode` and the preview above: the
    // empty string is a REAL value here (a decorative image is correctly
    // described by no text), so leaving the field absent would let the shared
    // default stand over a node whose description really is empty.
    state.altText = node.asset_placement?.alt_text ?? node.kind.alt ?? "";
  }

  // §1.4 Auto Layout. Direction/wrap live on the node KIND; gap/grow/padding/
  // align live on `Node.layout` — so they hydrate independently.
  if (node.kind.kind === "auto_layout") {
    state.direction = node.kind.direction === "row" ? "horizontal" : "vertical";
    state.wrap = node.kind.wrap;
  }
  // RULING L10 (AD4.B step 2): for an AUTO-LAYOUT node these five rows are
  // stated unconditionally — the AD4.R "state every bound key for every
  // selection" rule, which the Layout section above already follows. The Auto
  // Layout section renders for every `auto_layout` node (OQ-1 suppresses it for
  // a plain Frame, and no other schema carries it), while `Node.layout` is
  // genuinely optional in the wire format; a node that carries none really does
  // lay out at the engine's own `defaultLayoutProps()`, so those are the honest
  // values rather than an absence that lets `DEFAULT_STATE`'s scaffolding seeds
  // ("Space between"/"Center") stand over a real document.
  //
  // The engine's builder is called rather than restated, for the reason the
  // write half needs too: `updateAutoLayoutAlignment` seeds `node.layout ??
  // defaultLayoutProps()`, so the panel and the engine cannot disagree about
  // what a layout-less auto-layout node lays out as.
  //
  // Every OTHER kind is unchanged — it hydrates these rows only when it really
  // carries a layout, and no schema of its own displays them.
  const layout =
    node.layout ?? (node.kind.kind === "auto_layout" ? defaultLayoutProps() : null);
  if (layout) {
    const effective = effectiveNode?.layout;
    state.gap = layout.gap_token && effectiveNode !== undefined && !effective ? "" : numberText(effective?.gap ?? layout.gap);
    state.grow = numberText(layout.grow);
    const [top, right, bottom, left] = effective?.padding ?? layout.padding;
    state.padding = {
      bottom: numberText(bottom),
      left: numberText(left),
      right: numberText(right),
      top: numberText(top),
    };
    if (layout.padding_token && effectiveNode !== undefined && !effective) {
      state.padding = { top: "", right: "", bottom: "", left: "" };
    }
    // UNCONDITIONAL, unlike the valign row above — and for the same reason the
    // four rows above it are: these are BOUND rows on a section that renders
    // for every auto-layout node, while `align_x`/`align_y` are optional in the
    // wire format. A conditional assignment left an omitted (or garbled) anchor
    // displaying `DEFAULT_STATE`'s "Space between"/"Center" while a commit on
    // the OTHER axis restated this one as `start` — display and write
    // disagreeing about the same node. `anchorLabel` states the engine default
    // the write half already carries, so they cannot.
    state.alignX = anchorLabel(layout.align_x, "align_x");
    state.alignY = anchorLabel(layout.align_y, "align_y");
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
  tokenMaps?: KitTokenMaps | null,
  effectiveNode?: Node | null,
): SceneInspectorState | null {
  if (!node) {
    return pageId ? hydrateSceneCanvasState(scene, pageId) : null;
  }
  const nodeState = hydrateSceneInspectorState(node, scene, tokenMaps, effectiveNode);
  if (!pageId || node.id !== rootFrameId(scene, pageId)) {
    return nodeState;
  }
  return { ...hydrateSceneCanvasState(scene, pageId), ...nodeState };
}

/**
 * §1.1: the canvas (page) schema — the state an EMPTY selection hydrates.
 *
 * Two rows: the size preset, matched on the page's pixel size (with the Custom
 * W/H pair always stating the page's size AS AUTHORED — px on the seeded ad,
 * mm on an agent-authored A4 — plus the unit those numbers are in, whether or
 * not a preset matched; genad2 Task 6), and the Background, which is the ROOT
 * FRAME's first fill (founder
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
    const { height, unit, width } = pageDisplaySize(page);
    // genad2 Task 6: the three ratified labels SPELL px sizes ("...1200x1200"),
    // so only a px page can match one. A 1200x1200 MM page claiming "Linkedin
    // square" would name a size the page does not have — and picking that
    // option back would resize the document to 1200 px.
    const preset =
      unit === "px"
        ? SIZE_PRESETS.find(
            (candidate) =>
              candidate.width === width && candidate.height === height,
          )
        : undefined;
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
    // genad2 Task 6: the unit those two numbers are IN, shown beside them as
    // inert text. Without it the panel states a bare 210/297 that the eye reads
    // as pixels, and the commit — which lands in this same unit — looks like it
    // did something else.
    state.customSizeUnit = unit;
  }

  const frameId = page ? rootFrameId(scene, pageId) : null;
  const root = frameId ? scene.nodes[frameId] : null;
  const fill = paintState(root?.fills[0]?.paint);
  // Ruling A15.1: `swatch`, not `color` — a gradient-filled frame must show the
  // colour the document HAS (its first stop), not the dummy's seed.
  state.backgroundColor = fill.swatch;
  if (fill.token !== undefined) state.tokenBackgroundColor = fill.token;
  state.backgroundFill = fill.fill;

  return state;
}

/** genad2 Task 6: what `pageDisplaySize` answers — a page's size in the unit
 * the page is actually authored in. */
export interface PageDisplaySize {
  height: number;
  unit: Unit;
  width: number;
}

/**
 * genad2 Task 6: a page's size AS AUTHORED — the numbers §1.1's W/H boxes
 * display, and the unit they display beside them.
 *
 * This panel used to read every page as pixels, which was true while the only
 * page in the world was the seeded 1200x1200 ad. `open_design_leg@4` births a
 * document with no page and the design agent authors its own, in whatever
 * unit the medium wants — mm/in for print, px for digital — so a px-only read
 * MISREPORTS an A4 page: it falls through to the canonical `pt` box and shows
 * 595x842 as if those were pixels.
 *
 * The order is the engine's own certainty order, most-specific first:
 *
 *   • `output.physical` — a print page's authored physical size (210x297 mm).
 *     Preferred over `source` because it is the size the artifact is EXPORTED
 *     at, the same reason the raster wins below.
 *   • `output.raster` — the px export size. AHEAD of a px `source`,
 *     deliberately: that was the retired px-only read's documented rule and
 *     the two differ only when a fractional authored px rounds, so every px
 *     page's display stays byte-for-byte what it was.
 *   • `source` — the authored pair for a unit that mints no output (`pt`), and
 *     the general answer for any unit added later.
 *   • the canonical box, labelled with its OWN unit — `pt` for a page the
 *     engine minted, and honestly `px` for a legacy literal-px page (which the
 *     engine flags LUMV0805). Never a unit this function guessed.
 *
 * §1.1's WRITE half reads its unit from here too (`scene-apply.ts`), so the
 * commit lands in the unit the panel is showing — the same "the write is the
 * exact inverse of hydrate" rule the rest of this file runs on. That is what
 * makes typing 300 into an A4 page's H mean 300 mm rather than silently
 * converting the document to a 300px raster.
 */
export function pageDisplaySize(page: Page): PageDisplaySize {
  const physical = page.size.output?.physical;
  if (physical) {
    return { height: physical.height, unit: physical.unit, width: physical.width };
  }
  const raster = page.size.output?.raster;
  if (raster) {
    return { height: raster.height_px, unit: "px", width: raster.width_px };
  }
  const source = page.size.source;
  if (source) {
    return { height: source.height, unit: source.unit, width: source.width };
  }
  return { height: page.size.height, unit: page.size.unit, width: page.size.width };
}

/* genad2 Task 7 (close-out sweep): `pagePixelSize` — the px-only page read —
 * was DELETED here. Task 6 moved §1.1's panel and write onto
 * `pageDisplaySize`, which left it with ZERO production consumers, and a
 * px-named page read is a live hazard once pages can be physical: on an A4
 * page it returns the `pt` canonical box (595x842), which is precisely the
 * misreport this file now exists to prevent. A future consumer that genuinely
 * needs pixels (a raster buffer, an export size) should read
 * `page.size.output.raster` explicitly rather than resurrect a name that
 * silently answers "pixels" for a page authored in millimetres. */
