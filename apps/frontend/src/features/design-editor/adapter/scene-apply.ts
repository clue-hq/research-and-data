import type { InspectorBackgroundFill } from "@/features/chat-shell/hooks/use-inspector-controller";
import type {
  AssetPlacement,
  AssetRecord,
  AutoLayoutProps,
  Color,
  ColorStop,
  CornerRadii,
  Dimension,
  Fill,
  ImageFitMode,
  ImageNode,
  LayoutAnchor,
  Node,
  Operation,
  Page,
  PageId,
  PagePreset,
  Paint,
  Rect,
  Scene,
  Stroke,
  TextAlign,
  TextNode,
  Unit,
  VerticalAlign,
} from "../engine/scene/contracts";
import { buildNodePlacementOperations } from "../engine/scene/assetLibrary";
import {
  defaultLayoutProps,
  nodePatch,
  set,
  updateAutoLayoutAlignment,
  updateAutoLayoutNode,
  updateNodeAbsoluteBox,
  updateNodeFills,
  updateNodeLayout,
  updateNodeLocked,
  updateNodeSize,
  updateNodeStrokes,
  updateNodeTransform,
  updatePageSize,
  updateTextNode,
} from "../engine/scene/operations";
import { normalizePageSize } from "../engine/scene/pageGeometry";
import { resolvedTextFields, textTypographyResolves } from "../engine/scene/renderAdapter";
import type { KitTokenMaps } from "../engine/scene/tokenColors";
import {
  remapSpansByDiff,
  spanValidationIssues,
  spansVectorForContentEdit,
} from "../engine/scene/textSpans";
import {
  getPage,
  isNodeDirectGeometryEditable,
  isNodePinned,
} from "../engine/scene/sceneQueries";
import {
  COLOR_NONE,
  MINTED_STROKE_HEX,
  MINTED_STROKE_WIDTH,
  SIZE_PRESETS,
  dimensionSize,
  finiteNumber,
  pageDisplaySize,
  radiusCommit,
  rootFrameId,
  roundForEditor,
  vocabulary,
} from "./scene-hydrate";
import {
  normalizeHex,
  scenePaletteToken,
  type ScenePalette,
} from "./scene-palette";

/**
 * AD3.1: the pure write adapter for the SCENE (ad) lane — one inspector change
 * event → one engine operation, or `null`. It is the exact inverse of
 * `scene-hydrate.ts` (which is the authority on every vocabulary here) and the
 * ad-side sibling of the website lane's `apply.ts::inspectorChangeToOperation`,
 * whose house style it follows: contract-row citations in comments, a `switch`
 * on `property`, and `null` for anything unmapped.
 *
 * Null contract (identical to the web lane): an unknown property, an unmapped
 * value, the wrong node kind, an unparseable number, or a locked node produces
 * NO operation. Never a guess, never a throw. AD3.1 implements the §1.2 TEXT
 * schema's rows plus the §1.0 header lock; every later lane extends this same
 * switch.
 *
 * AD4.0 adds a SECOND exported function, `sceneCanvasChangeToOperation`, at
 * the foot of the file: §1.1's canvas rows are raised by a page-addressed
 * event and the canvas selection carries no node at all, so they cannot ride
 * the node signature. Same null contract, same voice; its own header states
 * its decisions. Step 1 built its size row (an `update_page`); step 2 its
 * Background row, which is an `update_node` on the page's ROOT FRAME.
 *
 * AD4.0 step 3 gives BOTH functions a `palette` parameter and every colour row
 * a second, brand half (`tokenTextColor` / `tokenStrokeColor` /
 * `tokenBackgroundColor`): §1.6 says a brand swatch writes a TOKEN binding
 * while custom hex writes a literal, so each control now has a hex row and a
 * token row that share their guards and differ only in the paint. The palette
 * is what validates the label a pick reports; `scene-palette.ts` is that
 * module and states the offer-and-resolve policy in full.
 *
 * Addressing (`selectionId` / `documentVersion` / "is this event for the node
 * I hold?") is the CALLER's gate, exactly as `hooks/use-inspector-writes.ts:78-89`
 * enforces it for the web lane — this adapter is pure and holds no selection.
 * It is deliberately not re-checked here: §1.1's canvas Background edits the
 * ROOT FRAME's fill while the selection is the (empty) canvas, so the addressed
 * selection and the written node legitimately differ — a `selectionId ===
 * node.id` assertion inside the adapter would have had to be special-cased
 * away the moment step 2 landed.
 *
 * AD4.A adds §1.3's two pure-adapter IMAGE rows to the node function: the
 * Fit/Fill/Crop mode (an `asset_placement` patch) and the corner radius (a
 * `corner` patch that clears the radius token). Both build their `update_node`
 * inline through `nodePatch`, because `engine/scene/operations.ts` is a
 * verbatim upstream port with no `updateNodeCorner`/`updateNodeAssetPlacement`
 * builder and this lane does not edit it. The AI suite is NOT here: it is
 * async, multi-step and carries no `property`/`value` pair, so it cannot ride
 * this seam at all.
 *
 * AD4.A step 2 adds §1.3's PLACEMENT decision as two more exports at the foot
 * of the node function — `sceneImageReplacementTarget` (may this node take a
 * picture?) and `sceneImagePlacementOperations` (which operations, or none).
 * They are not `switch` cases for the same reason: a placement carries a minted
 * `AssetRecord`, not a `property`/`value` pair, so it reaches this adapter from
 * a hook (`use-scene-replace-image.ts`, `use-scene-image-ai.ts`) rather than
 * from an inspector event. Everything that is a DECISION still lives here, with
 * its §1.3 siblings; only the transport lives in the hooks.
 *
 * AD4.A step 3 adds §1.3's ALT TEXT case to the switch, and folds Generate and
 * candidate-Accept into that same placement function — three flows, one rule
 * (the coordinator's alt-text ruling, stated in full at its site).
 *
 * WHICH ROWS CARRY A KIND GUARD is decided by one rule: **the write's kind
 * condition is exactly hydrate's kind condition**, so the two stay inverses.
 *   • typography + `textColor` → text only. `scene-hydrate.ts:378-386` routes a
 *     text node's fill to `textColor` and every other kind's to
 *     `backgroundColor`, so accepting `textColor` for a rect would write a
 *     property that node does not hydrate.
 *   • §1.4's SHAPE FILL rows (`backgroundColor` / `tokenBackgroundColor`, node
 *     -addressed — AD4.B step 3) → every NON-text kind, the exact complement of
 *     the line above and read off the same hydrate branch. That includes the
 *     GROUP, whose panel renders no Shape section at all (OQ-6): hiding a
 *     control is a presentation decision, and a kind guard here that hydrate
 *     does not have would be the very drift this rule prevents.
 *   • `fillMode` → image only, because hydrate states it for an image node and
 *     for nothing else (`scene-hydrate.ts:687-691`).
 *   • `fitToText` (Plan 4 item F) → text only. Its control lives on the text
 *     schema alone and its write states a text fact — the box hugs its copy —
 *     so there is nothing for it to mean on any other kind.
 *   • §1.4's AUTO LAYOUT rows (direction / wrap / gap / grow / padding / align)
 *     → `auto_layout` only. Ruling L10 makes hydrate state the whole set for
 *     every auto-layout node (defaults included) and for no other kind's
 *     schema — OQ-1 suppresses the section on a plain Frame — so that is the
 *     write's condition too. It is also a crash guard here: the engine's
 *     `updateAutoLayoutNode` THROWS on a non-auto-layout node.
 *   • stroke / position / rotation / lock / RADIUS → every kind, because
 *     hydrate's stroke, geometry and corner mappings are one path for every
 *     kind (`scene-hydrate.ts:348-401`, `:660-672`). Same posture as the web
 *     lane's radius row, which likewise refuses to invent a kind guard the
 *     mapping does not have — and it is what lets Lane B's rectangle and
 *     auto-layout schemas inherit the radius row rather than restate it.
 */

export interface SceneChangeDetail {
  property: string;
  /** The selection the event was raised under, as the CALLER's gate proved it.
   * On the §1.1 canvas rows that is `null` (the empty selection) OR the page's
   * ROOT FRAME id — the two states that render the canvas schema
   * (`canvasWriteTarget`). Either way this adapter never reads it: it is pure
   * and holds no selection (the file header says why). An event carrying no
   * addressing at all leaves it `undefined`, which is a different fact and
   * never reaches here. */
  selectionId: string | null;
  value: unknown;
}

/** §1.2 row 4 / §2 delta row 2: the inverse of `scene-hydrate.ts`'s
 * `FONT_WEIGHT_LABELS` — all nine named weights, and nothing else. The web
 * lane's four-name vocabulary ("Semi Bold") is a DIFFERENT schema's and has no
 * option in the ad select, so it writes nothing. */
const FONT_WEIGHT_VALUES: Record<string, number> = {
  "100 Thin": 100,
  "200 Extra Light": 200,
  "300 Light": 300,
  "400 Regular": 400,
  "500 Medium": 500,
  "600 Semi Bold": 600,
  "700 Bold": 700,
  "800 Extra Bold": 800,
  "900 Black": 900,
};

/** §1.2 row 5 / §2 delta row 2: `TextAlign` passes straight through — the ad
 * schema's fourth toggle IS `justify`, so nothing is dropped at this seam. */
const TEXT_ALIGN_VALUES = new Set<string>([
  "center",
  "justify",
  "left",
  "right",
]);

/** §1.2 row 6: the inverse of `scene-hydrate.ts`'s `VALIGN_LABELS` — the
 * dummy's `middle` is the engine's `center`. The engine's own word is not in
 * the dummy's vocabulary and therefore is not accepted. */
const VALIGN_VALUES: Record<string, VerticalAlign> = {
  bottom: "bottom",
  middle: "center",
  top: "top",
};

/** §1.4/OQ-2 (AD4.B step 1): the inverse of the mode select's three DISPLAY
 * labels — the engine's own lowercase `Dimension.kind` words. `token` is
 * deliberately absent: no v1 control offers it (the MVP's own select refuses
 * the value too), so a stored token dimension is left alone unless the user
 * picks one of the three. The engine's spellings are not in the dummy's
 * vocabulary and are therefore not accepted, exactly as `VALIGN_VALUES`
 * refuses `center`. */
const SIZE_MODE_KINDS: Record<string, "fill" | "fixed" | "hug"> = {
  Fill: "fill",
  Fixed: "fixed",
  Hug: "hug",
};

/** §1.4 Auto Layout (AD4.B step 2): the inverse of hydrate's
 * `node.kind.direction === "row" ? "horizontal" : "vertical"`. The seam carries
 * the STATE vocabulary (`InspectorDirection`), not the select's display labels
 * ("Row"/"Column") — the panel maps those, exactly as it maps the wrap select's
 * two labels onto the boolean `state.wrap`. The engine's own `row`/`column` are
 * not in the state vocabulary and are therefore not accepted. */
const LAYOUT_DIRECTION_VALUES: Record<string, "column" | "row"> = {
  horizontal: "row",
  vertical: "column",
};

/** §1.4 Auto Layout (AD4.B step 2): the inverse of `scene-hydrate.ts`'s
 * `LAYOUT_ANCHOR_LABELS` — the five labels the Align X/Y selects offer, and
 * nothing else. The engine's own snake spellings (`space_between`) are not in
 * the dummy's vocabulary and are therefore not accepted. */
const LAYOUT_ANCHOR_VALUES: Record<string, LayoutAnchor> = {
  Center: "center",
  End: "end",
  "Space between": "space_between",
  Start: "start",
  Stretch: "stretch",
};

/** §1.4 Auto Layout: which slot of `AutoLayoutProps.padding` a Pad box owns.
 * The tuple order is the wire format's — **[top, right, bottom, left]** — and
 * hydrate destructures it the same way, so this table is the one place the
 * order is stated for the write. */
const PADDING_SLOTS: Record<string, 0 | 1 | 2 | 3> = {
  "padding.bottom": 2,
  "padding.left": 3,
  "padding.right": 1,
  "padding.top": 0,
};

/**
 * §1.4 Auto Layout: the `AutoLayoutProps` a commit BUILDS ON.
 *
 * `Node.layout` is optional in the wire format and the section renders for a
 * layout-less auto-layout node all the same, so a commit seeds the engine's own
 * `defaultLayoutProps()` — the very values hydration states for it (ruling
 * L10), and the same seed `updateAutoLayoutAlignment` uses internally, so the
 * panel and the engine cannot disagree about what such a node lays out as.
 *
 * Spread authored properties to preserve unrelated bindings and layout mode.
 * An explicit gap or padding override replaces only its own binding; padding
 * siblings come from the paired resolved view before its shared token is removed.
 */
function layoutBase(node: Node): AutoLayoutProps {
  return node.layout ?? defaultLayoutProps();
}

/**
 * §1.4 Auto Layout: the anchor an UNTOUCHED axis carries into an alignment
 * commit — what the node stores, or the engine's own seed when it stores none.
 *
 * Both members are optional in the wire format, which is why this is a function
 * rather than a field read: the two selects commit independently, so the axis
 * the user did not touch must be restated exactly as it was, and the value
 * hydration is SHOWING for an absent one is `defaultLayoutProps()`'s. The
 * literal tail is the type system's and not a second policy — the builder's
 * return type declares both members optional even though it always states them.
 */
function storedAnchor(
  layout: AutoLayoutProps,
  axis: "align_x" | "align_y",
): LayoutAnchor {
  return layout[axis] ?? defaultLayoutProps()[axis] ?? "start";
}

/** §1.4 Auto Layout: a Gap/Grow/Pad box's number, or `null`. Negative refuses
 * rather than folds — the radius and stroke-width rule: these fields are free
 * text, so a number the engine cannot hold names no intent the panel may
 * guess at. Zero is a REAL value and is accepted. */
function layoutNumber(raw: string): number | null {
  const value = finiteNumber(raw);
  return value === null || value < 0 ? null : value;
}

/** §1.3 Mode (AD4.A): the inverse of `scene-hydrate.ts`'s `IMAGE_FIT_LABELS` —
 * the three labels the dummy's select offers (`FILL_MODES`), and nothing else.
 * The engine's own words (`cover`, `contain`) are not in that vocabulary and
 * are therefore not accepted, exactly as `VALIGN_VALUES` refuses `center`. */
const IMAGE_FIT_VALUES: Record<string, ImageFitMode> = {
  Crop: "crop",
  Fill: "cover",
  Fit: "contain",
};

/**
 * §1.3 Mode: the fit a node EFFECTIVELY has, which is what the no-change guard
 * compares against — not the stored key.
 *
 * An absent `fit` is `contain` exactly, on both renderers: the exporter maps
 * `Some(Contain) | None` onto the same `xMidYMid meet`
 * (`lumen-export/src/svg.rs::image_preserve_aspect_ratio`) and the rasterizer's
 * `(_, Some(ratio))` letterbox arm takes both (`lumen-skia/src/render.rs`).
 * The panel says the same thing — hydrate states no mode for a placement-less
 * image, so the shared `Fit` default stands — so "Fit" on such a node is a
 * gesture that changes neither the pixels nor the panel, and minting a
 * placement for it would be a document version that states nothing new.
 */
function effectiveImageFit(placement: AssetPlacement | null | undefined): ImageFitMode {
  return placement?.fit ?? "contain";
}

/**
 * §1.3 Alt text (AD4.A step 3): the description the box is SHOWING, which is
 * what its no-change guard compares against.
 *
 * Two fields can carry it and upstream reads both, in this order:
 * `asset_placement.alt_text ?? ImageNode.alt ?? ""`
 * (`ImageInspectorSection.tsx:61`). They are genuinely different facts —
 * `ImageNode.alt` is the node's own authored description and the placement's is
 * the one a placement stamped — so a node with no `alt_text` legitimately
 * displays its `alt`, and re-committing that text must mint no document
 * version. Hydration states the same expression, so the two stay inverses.
 */
function effectiveAltText(node: Node): string {
  const stored = node.asset_placement?.alt_text;
  if (typeof stored === "string") {
    return stored;
  }
  return (node.kind.kind === "image" ? node.kind.alt : null) ?? "";
}

/**
 * §1.3 Replace image: is the placement this write would produce the one the
 * node ALREADY carries? The standing "a change that changes nothing is not a
 * write" rule (`sameCorner`, `sameStroke`), applied to the upload row — where
 * it is reachable in one gesture, because `POST /assets` deduplicates by
 * content, so re-picking the file already in the node mints the record the node
 * already points at.
 *
 * ONE FIELD IS COMPARED, and this is the invariant that makes that enough:
 * `sceneImagePlacementOperations` builds the next placement as
 * `{...node.asset_placement, alt_text}`, so every other field is identical to
 * the stored one BY CONSTRUCTION and a four-field comparison (which is what
 * this was) reads as load-bearing while three of its branches can never be
 * false. It is the ONE function all three placement flows go through — upload,
 * Generate and candidate-Accept — so **a caller that ever builds the placement
 * any other way must widen this again.** Absent and `null` fold together, for `sameStroke`'s reason exactly:
 * every field of `AssetPlacement` is optional (`contracts.ts:446`) and the
 * stored bytes omit the ones they do not use.
 */
function sameAltText(
  existing: AssetPlacement | null | undefined,
  next: AssetPlacement,
): boolean {
  return (existing?.alt_text ?? null) === (next.alt_text ?? null);
}

/**
 * §1.3 Radius: the four corners this write commits — one named corner replaced
 * (or all four, for `radius.all`), with `token` CLEARED (§4: "a raw radius
 * write clears `corner.token`", which is upstream's own `cornerWith` /
 * `cornerWithAll` rule, `RawStyleSection.tsx:155-174`).
 *
 * EVERY FIELD IS NAMED ON BOTH SIDES, deliberately. The TS/Rust struct order is
 * TL, TR, BR, BL while the stored bytes read TL, TR, BL, BR (`scene.rs:1284`
 * vs the harvested `image_hero`), so both sides serialize by field NAME and key
 * order cannot break correctness on its own — but a tuple, an array or an
 * `Object.values()` here would transpose BR and BL silently and render subtly
 * wrong. There is no positional form of this function to get wrong.
 */
function cornerWith(
  existing: CornerRadii,
  property: string,
  radius: number,
): CornerRadii {
  const all = property === "radius.all";
  return {
    bottom_left:
      all || property === "radius.bottomLeft" ? radius : existing.bottom_left,
    bottom_right:
      all || property === "radius.bottomRight" ? radius : existing.bottom_right,
    top_left: all || property === "radius.topLeft" ? radius : existing.top_left,
    top_right:
      all || property === "radius.topRight" ? radius : existing.top_right,
    token: null,
  };
}

/**
 * §1.3 Radius: is the corner this write would produce the one the node ALREADY
 * carries? The standing "a change that changes nothing is not a write" rule
 * (`backgroundFillsOperation`, `sameStroke`), applied to the radius row — where
 * it matters most, because the ad schema passes `RadiusControls` no
 * `onApplyAll` and one all-corners gesture therefore dispatches SEVERAL corner
 * events, each of which would otherwise mint an empty document version and an
 * empty undo step for a corner that already held that number.
 *
 * The TOKEN is part of the comparison, for `sameStroke`'s reason exactly:
 * `cornerWith` always clears it, so the same four numbers over a token-bound
 * corner is a real change — and one that shows, since the renderer PREFERS a
 * resolved radius token over the four numbers
 * (`engine/scene/renderAdapter.ts:270-301`). Absent and `null` are folded to
 * the one fact they both state (the field is optional and the real stored bytes
 * omit it), or every untokened corner would look changed and defeat the guard.
 */
function sameCorner(existing: CornerRadii, next: CornerRadii): boolean {
  return (
    existing.bottom_left === next.bottom_left &&
    existing.bottom_right === next.bottom_right &&
    existing.top_left === next.top_left &&
    existing.top_right === next.top_right &&
    (existing.token ?? null) === (next.token ?? null)
  );
}

/**
 * The half of upstream's guard that binds EVERY fill control here: the panel
 * shows one fill (`scene-hydrate.ts` reads `fills[0]`) and every write replaces
 * the whole array, so a second layer would be destroyed by a control that never
 * showed it. The engine calls stacked paints `EffectFeature::MultiFill`
 * (`lumen-core/src/render_contract.rs`); §1 gives them no control at all.
 */
function isMultiFill(fills: Fill[]): boolean {
  return fills.length > 1;
}

/**
 * Mirrors `subsystems/clue-design/apps/editor/src/components/ColorSwatchControl.tsx:228-234`
 * (`isGradientGuarded`), reimplemented locally because the seam forbids
 * importing design-subsystem internals. True when a destructive single-swatch
 * replace would clobber a fill the control cannot faithfully represent: more
 * than one fill layer, or a paint that is neither solid nor token.
 *
 * Upstream DISABLES the swatch in that state; the ad inspector's ColorControl
 * has no disabled state, so the honest equivalent under the null contract is to
 * refuse the write rather than flatten a gradient the control cannot show.
 *
 * SCOPE (AD4.0 step 2): this is the guard for a BARE swatch — §1.2's Color row.
 * §1.1's Background swatch keeps only the multi-fill half, because it is not
 * bare: a fill-type select sits above it and the swatch renders only while that
 * select says "Solid". `backgroundTarget` states that reasoning in full.
 */
function isGradientGuarded(fills: Fill[]): boolean {
  if (isMultiFill(fills)) {
    return true;
  }
  const paint = fills[0]?.paint;
  return paint ? paint.kind !== "solid" && paint.kind !== "token" : false;
}


/**
 * The single fill layer any of these controls commits. The paint id is the
 * node's EXISTING fill id when it has one (preserving paint identity across an
 * edit), falling back to the id the standalone editor mints
 * (`ColorSwatchControl.tsx:236-238`, `paint_${node.id}_fill`).
 *
 * AD4.0 step 2 generalized this from `solidHexFill` (below) so §1.1's gradient
 * rows mint their paint id the same way — one rule, not two.
 */
function paintFill(node: Node, paint: Paint): Fill {
  return { id: node.fills[0]?.id ?? `paint_${node.id}_fill`, paint };
}

/**
 * §1.6: the solid paint a hex swatch commits.
 *
 * A raw hex DETACHES any brand token on that paint — the ratified §1.6 trade.
 * The user-facing "this leaves your brand palette" note is Gate G-B chrome
 * (§6 item 2) that does not exist yet; this comment is deliberately the only
 * place it is mentioned.
 */
function solidHexPaint(hex: string): Paint {
  return { color: { kind: "hex", value: hex }, kind: "solid" };
}

/** §1.6: that paint as the node's single fill layer. */
function solidHexFill(node: Node, hex: string): Fill {
  return paintFill(node, solidHexPaint(hex));
}

/**
 * §1.6, the other half (AD4.0 step 3): the paint a BRAND SWATCH commits — a
 * token binding rather than a burnt-in colour, so the element keeps following
 * the kit.
 *
 * `label` is what `ColorControl` reports on a Theme-tab pick, and it is
 * VALIDATED against the document's own palette before it can become a paint:
 * `scenePaletteToken` returns `null` for a label this kit does not offer, and
 * `null` here is no operation. That is what stops the dummy's fallback palette
 * ("Primary", "Dark", …) from binding a real ad to a token nothing can
 * resolve — the null contract, applied to the brand vocabulary.
 *
 * The token is written BARE. The kit's own keys are bare, upstream's writer
 * takes the bare catalog name (`ColorSwatchControl.tsx:38-41` → `tokenFill`)
 * and renders the `$` only as author-facing sugar, and the engine's resolver
 * strips a leading `$` before lookup (`tokenColors.ts::resolveTokenColor`), so
 * both spellings name one entry and the bare one is canonical.
 */
function tokenPaint(
  palette: ScenePalette | null | undefined,
  label: string,
): Paint | null {
  const token = scenePaletteToken(palette, label);
  return token === null ? null : { kind: "token", token };
}

/** §1.2 row 7: the stroke shape, mirroring `RawStyleSection.tsx:139-153`
 * (`solidStroke`) — the existing paint id is reused, and a raw width write
 * clears any `width_token` exactly as upstream does. */
function strokeWith(
  node: Node,
  paint: Stroke["paint"],
  width: number,
): Stroke {
  return {
    id: node.strokes[0]?.id ?? `paint_${node.id}_stroke`,
    paint,
    width: roundForEditor(width),
    width_token: null,
  };
}

/**
 * RULING A9 (standing): the Stroke row MINTS a stroke on a strokeless node,
 * using upstream's own two defaults rather than refusing.
 *
 * AD3.1 refused both directions — it read a strokeless node's width as the 0
 * the panel displays (so a colour pick cleared) and would not invent a colour
 * for a width (so a width write was dropped). That left §1.2's ratified Stroke
 * row permanently dead on exactly the kinds where strokes are common, and
 * Lane B's rect/ellipse schemas need it. §1.5's "editor semantics govern
 * everywhere" makes adopting the standalone editor's constants a LIFT, not an
 * invention; refusing was the divergence.
 *
 *   • width — `RawStyleSection.tsx:38`:
 *     `solidStroke(node, hex, node.strokes[0]?.width ?? 1)`.
 *   • colour — `RawStyleSection.tsx:52`, `solidStroke(node,
 *     hexInputValueFromStroke(node), value)`, whose no-stroke return is
 *     `#256c70` (`RawStyleSection.tsx:185-191`).
 *
 * Both apply to the hex and the token halves of the row alike, or it is
 * coherent in only one of them.
 *
 * The two constants live in `scene-hydrate.ts` beside the rest of the row's
 * vocabulary, because the PANEL needs the same pair: a stroke row still
 * reading "none / 0" over a node this write just gave a 1px teal stroke would
 * be the panel lying about the document.
 */

/**
 * FIX 1 (review): is the stroke this write would produce the one the node
 * ALREADY carries? The `backgroundFillsOperation` rule — "a change that
 * changes nothing is not a write" — applied to the §1.6 stroke row.
 *
 * The WHOLE stroke is compared, not just its paint: `strokeWith` always writes
 * `width_token: null` (upstream's rule), so an identical paint over a
 * width-token-bound stroke is a real change and must not be dropped.
 *
 * `width_token` is OPTIONAL on the contract (`contracts.ts:522`) and the real
 * stored bytes omit it entirely — the harvested `auto_row_copy` stroke has no
 * such key — so absent and `null` are folded to the one fact they both state:
 * this stroke has no width token. Comparing them literally would have made
 * every real stroke look changed and defeated the guard.
 */
function sameStroke(existing: Stroke | undefined, next: Stroke): boolean {
  return (
    existing !== undefined &&
    existing.id === next.id &&
    existing.width === next.width &&
    (existing.width_token ?? null) === (next.width_token ?? null) &&
    paintKey(existing.paint) === paintKey(next.paint)
  );
}

/**
 * §1.2 row 8: X/Y. A PINNED node's page-space `absolute_box` is authoritative
 * for its geometry, so the write patches the box — the exact inverse of
 * `scene-hydrate.ts:350-356`, which reads a pinned node's x/y from that box,
 * and the same rule the standalone editor's own `ObjectSection.tsx:93-99`
 * (`emitPosition`) follows. Writing the transform instead would be silently
 * discarded by the solver and the typed value would snap back on the next
 * hydrate.
 *
 * A pinned node with NO resolvable box falls back to the transform, because
 * that is what hydration displays for it (`scene-hydrate.ts:350-356` — the box
 * first, then `node.transform`) and what upstream's `emitPosition` writes for
 * it (`ObjectSection.tsx:93-99`, which falls through to `emitTransform`).
 * Refusing instead would leave the user editing a field that shows a real
 * number and silently does nothing — a worse failure than the write the two
 * precedents agree on.
 *
 * When the box comes from `computed.layout_bounds` rather than a stored
 * `absolute_box`, the engine builder additionally bakes the box's size as
 * Fixed (`operations.ts:107-125`) — deliberate upstream behaviour (same code,
 * same inputs, same result there): giving a boxless pin its first box also
 * defines its size.
 */
function positionOperation(
  node: Node,
  scene: Scene,
  axis: "x" | "y",
  value: number,
): Operation | null {
  if (!isNodeDirectGeometryEditable(scene, node.id)) {
    return null;
  }
  const box: Rect | null = isNodePinned(scene, node.id)
    ? (node.absolute_box ?? node.computed?.layout_bounds ?? null)
    : null;
  if (box) {
    return updateNodeAbsoluteBox(
      node,
      axis === "x" ? { ...box, x: value } : { ...box, y: value },
    );
  }
  return updateNodeTransform(
    node,
    axis === "x"
      ? { ...node.transform, x: value }
      : { ...node.transform, y: value },
  );
}

/** Detach an edited role while preserving the other effective text fields. */
function inspectorTypographyOperation(
  node: Node,
  change: Partial<Pick<TextNode, "font_family" | "font_size" | "font_weight">>,
  tokenMaps?: KitTokenMaps | null,
): Operation | null {
  if (node.kind.kind !== "text") return null;
  const text = node.kind;
  if (!textTypographyResolves(text, tokenMaps)) return null;
  if (!text.style_token && !text.font_size_token && !text.line_height_token && !text.letter_spacing_token) {
    return updateTextNode(node, change);
  }
  const maps = tokenMaps ?? { typography: {}, numbers: {} };
  const styled = resolvedTextFields(text, maps);
  const effective = { ...text, font_family: styled.fontFamily, font_size: styled.fontSize,
    font_weight: styled.fontWeight, line_height: styled.lineHeight,
    letter_spacing: styled.letterSpacing };
  if (Object.entries(change).every(([key, value]) => effective[key as keyof TextNode] === value)) {
    return null;
  }
  // A literal edit detaches the role. Keep other bindings only when they still
  // produce the value the user saw; a previously shadowed token must not wake up.
  const detached = resolvedTextFields({ ...text, style_token: null }, maps);
  const kind: typeof text = { ...effective, ...change, style_token: null,
    font_size_token: change.font_size === undefined && detached.fontSize === styled.fontSize
      ? text.font_size_token : null,
    line_height_token: detached.lineHeight === styled.lineHeight ? text.line_height_token : null,
    letter_spacing_token: detached.letterSpacing === styled.letterSpacing ? text.letter_spacing_token : null,
  };
  return { kind: "update_node", node_id: node.id, patch: nodePatch({
    kind: set(kind), explicit_text_tokens: {
      style: false, font_size: kind.font_size_token != null,
      line_height: kind.line_height_token != null,
      letter_spacing: kind.letter_spacing_token != null,
    },
  }) };
}

/**
 * One inspector change → one engine operation, or `null`.
 * `isNodeDirectGeometryEditable` gates geometry rows using the engine's own
 * predicate (unlocked AND either unmanaged or freehand).
 */
export function sceneChangeToOperation(
  detail: SceneChangeDetail,
  node: Node,
  scene: Scene,
  /** AD4.0 step 3 / §1.6: the document's brand vocabulary, for the token rows
   * only. Absent or `null` — no kit attached, a kit fetch that failed, any
   * caller that has not threaded one — means no label can be validated, so no
   * token write happens. Every other row ignores it. */
  palette?: ScenePalette | null,
  tokenMaps?: KitTokenMaps | null,
  effectiveNode?: Node | null,
): Operation | null {
  const { property } = detail;

  // §1.0: the header lock. It is decided BEFORE the lock gate below — the lock
  // gates every other write for that node, so gating the unlock too would make
  // a locked node permanently locked. It is also the one row whose committed
  // value is a BOOLEAN, so it resolves ahead of the string coercion the rest
  // of the controls share (the web lane's `wrap`/`visible` posture).
  if (property === "locked") {
    if (typeof detail.value !== "boolean") {
      return null;
    }
    return updateNodeLocked(node, detail.value);
  }

  // §1.0 / §4: "lock gates every write path".
  if (node.locked) {
    return null;
  }

  // §1.4 Auto Layout Wrap (AD4.B step 2): the SECOND boolean row, and it
  // resolves here for the lock row's reason exactly — `state.wrap` is a boolean
  // in `InspectorPresentationState`, so the select's two display labels are
  // mapped by the PANEL and never cross this seam, and the value therefore
  // cannot survive the string coercion below. It sits AFTER the lock gate,
  // unlike the lock itself: a locked node refuses it like every other row. The
  // web lane's own Wrap row is the precedent (`apply.ts:331`, row 22).
  //
  // KIND GUARD: `auto_layout` only — hydrate's condition for this row, the file
  // header's standing rule, and `updateAutoLayoutNode` THROWS on anything else.
  if (property === "wrap") {
    if (node.kind.kind !== "auto_layout" || typeof detail.value !== "boolean") {
      return null;
    }
    return updateAutoLayoutNode(node, { wrap: detail.value });
  }

  const value = typeof detail.value === "string" ? detail.value : null;
  if (value === null) {
    return null;
  }

  const text = node.kind.kind === "text" ? node.kind : null;

  switch (property) {
    // ── §1.2 row 1: Color = the text fill (§1.6 policy) ──────────────────────
    case "textColor": {
      if (!text) {
        return null;
      }
      if (isGradientGuarded(node.fills)) {
        return null;
      }
      const hex = normalizeHex(value);
      if (hex === null) {
        return null;
      }
      return updateNodeFills(node, [solidHexFill(node, hex)]);
    }

    // ── §1.6: the same row's BRAND half — a Theme-tab pick ───────────────────
    // Its guards are the hex row's, exactly: the kind condition is hydrate's
    // (a text node's fill is `textColor`), and the gradient/multi-fill guard is
    // the same single-swatch clobber rule. Only the paint differs.
    case "tokenTextColor": {
      if (!text || isGradientGuarded(node.fills)) {
        return null;
      }
      const paint = tokenPaint(palette, value);
      if (!paint) {
        return null;
      }
      // FIX 1 (review): the same no-change rule the Background row has always
      // had. Re-picking the swatch this node already wears — which the picker
      // shows as PRESSED, because its resolved colour matches — must not mint
      // a document version, and on the seeded headline it would have changed
      // only the stored `$` sugar. `paintKey` folds that spelling away.
      if (paintKey(node.fills[0]?.paint) === paintKey(paint)) {
        return null;
      }
      return updateNodeFills(node, [paintFill(node, paint)]);
    }

    // ── §1.4 Shape: Fill — the NON-text fill, both halves (AD4.B step 3) ─────
    //
    // The SAME two properties §1.1's Background rows carry, addressed at the
    // selected NODE instead of the page's root frame, because that is exactly
    // what hydrate states: its fill branch routes a text node's paint to
    // `textColor` and EVERY OTHER KIND's to `backgroundColor` (+
    // `tokenBackgroundColor`). So the kind condition here is `!text` — the
    // file header's standing rule that the write's kind condition IS
    // hydrate's, and the precise complement of the two rows above.
    //
    // OQ-6: the GROUP schema renders neither a Shape nor a Stroke section, so
    // the panel raises no fill event for a group. That is a presentation fact
    // and is deliberately NOT restated as a refusal here — hydrate states a
    // group's fill like any other non-text kind, and a kind guard the adapter
    // has and hydrate does not is exactly the drift the standing rule exists
    // to prevent (the kind-agnostic radius row already settled this shape).
    //
    // THE GUARDS ARE §1.2's COLOR ROW's, not §1.1's Background row's, because
    // this control is a BARE swatch: no fill-type select sits above it, so a
    // gradient or a multi-layer fill is one the user cannot see and a solid
    // write would silently destroy. `backgroundTarget`'s comment states the
    // asymmetry from the other side.
    case "backgroundColor": {
      if (text || isGradientGuarded(node.fills)) {
        return null;
      }
      // The `none` sentinel is `scene-hydrate.ts`'s own (`COLOR_NONE`), the
      // honest "this node has no fill" state a fill-less node hydrates as —
      // committing it means clearing the fills, exactly as §1.2's stroke row
      // clears the strokes. §1.1's canvas Background has no such branch, and
      // the difference is real rather than an inconsistency: its swatch renders
      // only while its fill-type select says "Solid", so the sentinel cannot
      // reach that seam, while THIS row's swatch is the whole control.
      if (value === COLOR_NONE) {
        return updateNodeFills(node, []);
      }
      const hex = normalizeHex(value);
      if (hex === null) {
        return null;
      }
      // §1.6, node-side: a raw hex DETACHES a token-bound fill — the ratified
      // trade. Through `backgroundFillsOperation` so the paint, the paint id
      // and the no-change rule are §1.1's, stated once: `ColorControl`
      // re-commits its hex on blur whether or not it moved, so without the
      // guard opening and closing the picker would mint a document version and
      // an undo step that change nothing.
      return backgroundFillsOperation(node, solidHexPaint(hex));
    }

    // ── §1.6: the Shape Fill row's BRAND half ────────────────────────────────
    // Its guards are the hex row's exactly; only the paint differs.
    case "tokenBackgroundColor": {
      if (text || isGradientGuarded(node.fills)) {
        return null;
      }
      const paint = tokenPaint(palette, value);
      if (!paint) {
        return null;
      }
      return backgroundFillsOperation(node, paint);
    }

    // ── Rung A: Text — what the node SAYS (rich-text plan, 2026-08-24) ───────
    //
    // The empty string is a LEGAL commit here, unlike every other text row: an
    // emptied text node is a node that says nothing, which is a real edit and a
    // node that survives — so no `trim() === ""` refusal, and none of the
    // string coercion above needs relaxing (a non-string never reaches the
    // switch).
    //
    // D4, and rung C's answer to it (founder-visible item 6). The engine CLEARS
    // a spanned node's spans when the content changes and the spans arrive
    // byte-identical (`operations.rs:620-631`) — right for a caller who forgot
    // them, wrong for one that can still place them. So a spanned node's edit
    // now carries a REMAPPED vector: the conservative prefix/suffix diff
    // (`remapSpansByDiff`, the same one the caret session's untracked path
    // uses), which keeps styling inside the unchanged prefix and suffix and
    // trims or drops what touched the changed middle. It never guesses — this
    // row sees only the before and after strings, so a bolded word the user
    // retyped in the middle comes back unstyled rather than mis-styled.
    //
    // `spansVectorForContentEdit` runs LAST, immediately before the write, and
    // its output is never re-normalized: its whole job is to make a vector the
    // engine cannot mistake for a stale carry-forward, and normalizing would
    // merge that deliberate split back together.
    //
    // A node with no spans writes the content channel alone, exactly as rung A
    // did — there is nothing to remap and nothing for the engine to clear.
    //
    // RECORDED, NOT FIXED (review 2026-08-24, P3-5): a content commit whose
    // value equals the stored content still writes, and its spans channel then
    // carries the NORMALIZED stored vector — so a no-op "edit" could mint a
    // document version whose only change is a span merge. It is unreachable
    // from the shipped UI: every inspector row commits through `fieldCommit`,
    // which suppresses a re-type of the live value before it ever reaches this
    // switch. Left as it is rather than adding a guard nothing can trip.
    case "content": {
      if (!text) {
        return null;
      }
      const stored = text.spans ?? [];
      if (stored.length === 0) {
        return updateTextNode(node, { content: value });
      }
      const remapped = remapSpansByDiff(text.content, value, stored);
      const vector = spansVectorForContentEdit(text, value, remapped);
      // The pre-send gate, the caret session's own
      // (`scene-text-edit.ts::textEditCommitOperations`) repeated here rather
      // than assumed: the engine validates spans at LAYOUT, not at apply, so an
      // invalid vector applies clean and then drops the node out of measurement
      // (LUMV0906) with nothing refused. Unreachable by construction — every
      // `textSpans.ts` exit normalizes onto the five rules — and load-bearing
      // anyway. Loud in dev/test; in production the spans channel is dropped
      // and the content edit still lands, which is the honest degradation.
      const issues = spanValidationIssues(value, vector);
      if (issues.length > 0) {
        if (process.env.NODE_ENV !== "production") {
          throw new Error(
            `refusing to write an invalid spans vector: ${issues.join("; ")}`,
          );
        }
        return updateTextNode(node, { content: value });
      }
      return updateTextNode(node, { content: value, spans: vector });
    }

    // ── §1.2 row 2: Font family (§2 delta row 3 — the real vocabulary) ───────
    case "fontFamily": {
      if (!text || value.trim() === "") {
        return null;
      }
      return inspectorTypographyOperation(node, { font_family: value }, tokenMaps);
    }

    // ── §1.2 row 3: Size — a free number ≥ 1 (§2 delta row 2) ────────────────
    case "fontSize": {
      if (!text) {
        return null;
      }
      const size = finiteNumber(value);
      if (size === null || size < 1) {
        return null;
      }
      return inspectorTypographyOperation(node, { font_size: size }, tokenMaps);
    }

    // ── §1.2 row 4: Weight — the nine named labels (§2 delta row 2) ──────────
    case "fontWeight": {
      if (!text) {
        return null;
      }
      const weight = vocabulary(FONT_WEIGHT_VALUES, value);
      if (weight === undefined) {
        return null;
      }
      return inspectorTypographyOperation(node, { font_weight: weight }, tokenMaps);
    }

    // ── §1.2 row 5: H-alignment — four toggles (§2 delta row 2) ──────────────
    case "horizontalAlignment": {
      if (!text || !TEXT_ALIGN_VALUES.has(value)) {
        return null;
      }
      return updateTextNode(node, { align: value as TextAlign });
    }

    // ── §1.2 row 6: V-alignment — "disabled when height mode is hug" ─────────
    case "verticalAlignment": {
      if (!text) {
        return null;
      }
      // `scene-hydrate.ts:373-375` sets `valignDisabled` in exactly this case;
      // writing here would contradict a control the inspector has disabled.
      if (node.size.height.kind === "hug") {
        return null;
      }
      const valign = vocabulary(VALIGN_VALUES, value);
      if (valign === undefined) {
        return null;
      }
      return updateTextNode(node, { valign });
    }

    // ── §1.2 row 7: Stroke colour + width (width 0 clears) ───────────────────
    case "strokeColor": {
      // The `none` sentinel is `scene-hydrate.ts`'s own (`COLOR_NONE`, the
      // shared inspector default's spelling) — the honest "this node has no
      // stroke" state, which committing means clearing the strokes.
      if (value === COLOR_NONE) {
        return updateNodeStrokes(node, []);
      }
      const hex = normalizeHex(value);
      if (hex === null) {
        return null;
      }
      // Keep the existing width; with NO stroke at all, MINT one at upstream's
      // default (ruling A9, stated at `MINTED_STROKE_WIDTH`). A stored
      // ZERO-width stroke still clears — the width field truthfully shows 0
      // for it, and a zero-width stroke is not a stroke.
      const width = node.strokes[0]?.width ?? MINTED_STROKE_WIDTH;
      if (width <= 0) {
        return updateNodeStrokes(node, []);
      }
      return updateNodeStrokes(node, [
        strokeWith(node, { color: { kind: "hex", value: hex }, kind: "solid" }, width),
      ]);
    }
    // ── §1.6: the stroke row's BRAND half ───────────────────────────────────
    // Same shape as the hex branch above and for the same reasons — ruling A9's
    // minted width included, so the row behaves the same however the colour was
    // chosen. Only the paint differs.
    case "tokenStrokeColor": {
      const paint = tokenPaint(palette, value);
      if (!paint) {
        return null;
      }
      const strokeWidthValue = node.strokes[0]?.width ?? MINTED_STROKE_WIDTH;
      if (strokeWidthValue <= 0) {
        return updateNodeStrokes(node, []);
      }
      const stroke = strokeWith(node, paint, strokeWidthValue);
      // FIX 1 (review): re-picking the token this stroke already wears is not
      // a write. The whole stroke is compared — see `sameStroke`.
      if (sameStroke(node.strokes[0], stroke)) {
        return null;
      }
      return updateNodeStrokes(node, [stroke]);
    }
    case "strokeWidth": {
      const width = finiteNumber(value);
      if (width === null || width < 0) {
        return null;
      }
      if (width === 0) {
        return updateNodeStrokes(node, []);
      }
      const existing = node.strokes[0];
      // The stored paint rides along VERBATIM: a width edit is not a colour
      // edit, so it must not detach a token-bound stroke (§1.6 binds raw
      // COLOUR writes). That diverges from upstream, which rebuilds the stroke
      // as a solid through `hexInputValueFromStroke` and so silently detaches.
      //
      // With NO stroke there is no paint to keep, and ruling A9 settles what
      // happens: MINT upstream's own default colour (`MINTED_STROKE_HEX`)
      // rather than refuse. AD3.1 refused here, which left a width typed on a
      // strokeless node doing nothing at all.
      return updateNodeStrokes(node, [
        strokeWith(
          node,
          existing?.paint ?? {
            color: { kind: "hex", value: MINTED_STROKE_HEX },
            kind: "solid",
          },
          width,
        ),
      ]);
    }

    // ── §1.2 row 8: Position X/Y and Rotation ────────────────────────────────
    case "position.x":
    case "position.y": {
      const position = finiteNumber(value);
      if (position === null) {
        return null;
      }
      return positionOperation(
        node,
        scene,
        property === "position.x" ? "x" : "y",
        position,
      );
    }
    case "rotation": {
      if (!isNodeDirectGeometryEditable(scene, node.id)) {
        return null;
      }
      const rotation = finiteNumber(value);
      if (rotation === null) {
        return null;
      }
      // Raw pass-through, no degree/radian conversion (`scene-hydrate.ts:357`
      // hydrates it raw). Rotation rides the TRANSFORM even for a pinned node,
      // whose box carries position and size only (`operations.ts:127-129`).
      return updateNodeTransform(node, { ...node.transform, rotation });
    }

    // ── §1.4 Layout: Dimensions W/H (AD4.B step 1) ───────────────────────────
    // NO KIND GUARD, the file header's standing rule: hydrate states `width`
    // and `height` for every kind, so the four dummy schemas and OQ-1's plain
    // Frame reach this row without a second implementation.
    //
    // VERIFIED against the MVP editor's own W/H write (`ObjectSection.tsx`'s
    // `emitExtent`, read-only): a pinned node's page-space box takes the
    // number; every other node has that ONE axis rewritten to a Fixed
    // dimension, so a size typed on a hug or fill axis FLIPS that axis to
    // fixed rather than being refused. The panel's "Width fixed"/"Height fixed"
    // inputs commit this same property (the MVP's `SizingSection` writes the
    // identical `{kind:"fixed"}` from its own fixed field), so the two controls
    // are one write path rather than two cases that could disagree.
    //
    // NOT gated on `isNodeDirectGeometryEditable`, unlike Position and
    // Rotation: sizing is a layout INPUT, not direct geometry — the MVP's
    // `SizingSection` gates its size fields on the node's lock alone and says
    // so in as many words ("layout-managed children can change sizing mode even
    // when their direct X/Y geometry is locked"). Its `ObjectSection` W/H pair
    // does take the geometry gate, and the two MVP surfaces are simply split;
    // the ad panel has ONE W/H row that doubles as the fixed input, so the
    // permissive rule is the one that keeps both of its jobs working.
    case "width":
    case "height": {
      const axis = property === "width" ? "width" : "height";
      const size = finiteNumber(value);
      // The MVP's fixed-size fields are `min={1}`; the ad's are free text, so
      // the floor is a refusal here rather than a browser-enforced minimum —
      // the §1.2 font-size row's rule exactly.
      if (size === null || size < 1) {
        return null;
      }
      const box: Rect | null = isNodePinned(scene, node.id)
        ? (node.absolute_box ?? node.computed?.layout_bounds ?? null)
        : null;
      if (box) {
        return updateNodeAbsoluteBox(node, { ...box, [axis]: size });
      }
      return updateNodeSize(node, {
        ...node.size,
        [axis]: { kind: "fixed", value: size },
      });
    }

    // ── §1.4 Layout: Opacity — shown as %, written 0–1 (OQ-3) ────────────────
    case "opacity": {
      const percent = finiteNumber(value);
      if (percent === null) {
        return null;
      }
      // The one Layout row that FOLDS rather than refuses out-of-range input,
      // and the difference is the field itself: opacity is a bounded ratio, so
      // "150" names a real intent (fully opaque) the engine can state, while an
      // out-of-range radius or size names none. Both ends, because the engine's
      // own contract is 0–1 and a document holding -0.05 would render nothing
      // the panel could then explain.
      const clamped = Math.min(100, Math.max(0, percent));
      return {
        kind: "update_node",
        node_id: node.id,
        patch: nodePatch({ opacity: set(clamped / 100) }),
      };
    }

    // ── §1.4 Layout: Width/Height mode — Fixed | Hug | Fill (OQ-2) ───────────
    case "widthMode":
    case "heightMode": {
      const axis = property === "widthMode" ? "width" : "height";
      const current = node.size[axis];
      const mode = vocabulary(SIZE_MODE_KINDS, value);
      if (mode === undefined) {
        return null;
      }
      let dimension: Dimension;
      if (mode === "hug") {
        // WIRE FORMAT: the hug arm of `Dimension` has NO `value` member
        // (`contracts.ts`), and an extra one is a shape the Rust core does not
        // accept. Written as a bare literal so it cannot acquire one.
        dimension = { kind: "hug" };
      } else if (mode === "fill") {
        // OQ-2/§5: fill WEIGHTS have no v1 input, so the weight is 1 — which is
        // also what the MVP's own mode select seeds a non-fill axis with.
        dimension = { kind: "fill", value: { weight: 1 } };
      } else {
        // The size the panel is SHOWING for this axis — hydration's own
        // derivation, so the flip writes the number the user was looking at.
        // Null (an unsolved hug/fill axis, whose W/H box is empty) writes
        // nothing rather than the MVP's hardcoded 120.
        const size = dimensionSize(
          current,
          node.computed?.layout_bounds[axis] ?? null,
        );
        if (size === null) {
          return null;
        }
        dimension = { kind: "fixed", value: size };
      }
      return updateNodeSize(node, { ...node.size, [axis]: dimension });
    }

    // ── Plan 4 item F: "Fit to text" — the text box hugs its copy ────────────
    // ONE write, one document version: the height flips to hug (the authoring
    // default Plan 4 restores) and nothing else moves. Width is deliberately
    // untouched — a fixed width is the wrap width the author chose. The value
    // is not read; the button carries "1" for the event's sake only.
    case "fitToText": {
      if (!text || node.size.height.kind === "hug") {
        return null;
      }
      return updateNodeSize(node, { ...node.size, height: { kind: "hug" } });
    }

    // ── §1.4 Auto Layout: Direction (AD4.B step 2) ───────────────────────────
    // KIND GUARD: `auto_layout` only, on all six rows below. That is hydrate's
    // condition for them (ruling L10 states the whole set for every auto-layout
    // node and for no other kind's schema — OQ-1 suppresses the section on a
    // plain Frame), the file header's standing rule — and here it is also a
    // crash guard: `updateAutoLayoutNode` THROWS on a non-auto-layout node.
    case "direction": {
      if (node.kind.kind !== "auto_layout") {
        return null;
      }
      const direction = vocabulary(LAYOUT_DIRECTION_VALUES, value);
      if (direction === undefined) {
        return null;
      }
      return updateAutoLayoutNode(node, { direction });
    }

    // ── §1.4 Auto Layout: Gap and Grow ───────────────────────────────────────
    // Both are members of the SAME `AutoLayoutProps`, so each rewrites its own
    // member over `layoutBase` — the stored props, or the engine's defaults for
    // a layout-less node — rather than building a fresh object that would drop
    // its sibling and the two tokens.
    case "gap":
    case "grow": {
      if (node.kind.kind !== "auto_layout") {
        return null;
      }
      const size = layoutNumber(value);
      if (size === null) {
        return null;
      }
      const layout = { ...layoutBase(node), [property]: size };
      if (property === "gap" && layout.gap_token) layout.gap_token = undefined;
      return updateNodeLayout(node, layout);
    }

    // ── §1.4 Auto Layout: Pad T / R / B / L ──────────────────────────────────
    case "padding.top":
    case "padding.right":
    case "padding.bottom":
    case "padding.left": {
      if (node.kind.kind !== "auto_layout") {
        return null;
      }
      const size = layoutNumber(value);
      if (size === null) {
        return null;
      }
      const base = layoutBase(node);
      // ONE slot replaced, in the wire format's own [top, right, bottom, left]
      // order (`PADDING_SLOTS` is where that order is stated). The tuple is
      // rebuilt rather than mutated — `layoutBase` may hand back the node's own
      // stored array, and an operation must never edit the scene it reads.
      if (base.padding_token && !effectiveNode?.layout) return null;
      const padding: AutoLayoutProps["padding"] = [
        ...(base.padding_token ? effectiveNode!.layout!.padding : base.padding),
      ];
      padding[PADDING_SLOTS[property]] = size;
      return updateNodeLayout(node, { ...base, padding, ...(base.padding_token ? { padding_token: undefined } : {}) });
    }

    // ── §1.4 Auto Layout: Align X / Align Y ──────────────────────────────────
    case "alignX":
    case "alignY": {
      if (node.kind.kind !== "auto_layout") {
        return null;
      }
      const anchor = vocabulary(LAYOUT_ANCHOR_VALUES, value);
      if (anchor === undefined) {
        return null;
      }
      // TWO selects, one engine builder that takes BOTH anchors — so the axis
      // this commit did NOT touch is read off the node (falling back to the
      // engine's own default, exactly as hydrate does). Without that, choosing
      // an Align X would silently reset Align Y to `start`.
      const base = layoutBase(node);
      return property === "alignX"
        ? updateAutoLayoutAlignment(node, anchor, storedAnchor(base, "align_y"))
        : updateAutoLayoutAlignment(node, storedAnchor(base, "align_x"), anchor);
    }

    // ── §1.3 row 1: Mode — Fit / Fill / Crop (AD4.A) ─────────────────────────
    // KIND GUARD: image only, because `scene-hydrate.ts:687-691` states
    // `fillMode` for an image node and for nothing else — the file header's
    // standing rule that the write's kind condition IS hydrate's.
    //
    // GATE G-C: Crop is selectable and writes `fit: "crop"`; the focal-point
    // control is §6 mockup-gated chrome that does not exist, so the node's
    // stored focal point simply RIDES ALONG in the spread below. That is not
    // incidental — the crop window is computed FROM the focal point
    // (`lumen-export/src/svg.rs::focal_crop_geometry`), so dropping it would
    // recentre the image the moment the user chose Crop.
    case "fillMode": {
      if (node.kind.kind !== "image") {
        return null;
      }
      const fit = vocabulary(IMAGE_FIT_VALUES, value);
      if (fit === undefined) {
        return null;
      }
      const placement = node.asset_placement;
      if (effectiveImageFit(placement) === fit) {
        return null;
      }
      // A placement-less image MINTS one rather than refusing — ruling A9's
      // posture, and here it is upstream's literal behaviour: its own image
      // inspector reads `node.asset_placement ?? {}` and emits
      // `{...placement, fit}` (`ImageInspectorSection.tsx:80-87,198-210`), so
      // minting is the LIFT and refusing would be the divergence. Refusing
      // would also leave the Mode select showing a mode the document never
      // got. Every field of `AssetPlacement` is optional (`contracts.ts:446`),
      // so `{fit}` alone is a complete, valid placement.
      return {
        kind: "update_node",
        node_id: node.id,
        patch: nodePatch({ asset_placement: set({ ...placement, fit }) }),
      };
    }

    // ── §1.3 row 2: Alt text (AD4.A step 3) ──────────────────────────────────
    // The AI suite's one MANUAL row: upstream has no alt-text generator (a
    // repo-wide grep finds `alt_text` only in its image inspector, the contract
    // types and `withDefaultAlt`), so this is an ordinary `asset_placement`
    // patch through the ordinary property seam.
    //
    // KIND GUARD: image only, the file header's standing rule — hydrate states
    // `altText` for an image node and for nothing else.
    case "altText": {
      if (node.kind.kind !== "image") {
        return null;
      }
      // A non-string is not a description. Unlike every numeric row there is
      // nothing to parse: the box's own text IS the value, and "" is a real
      // one (a decorative image is correctly described by no text at all), so
      // it is accepted rather than folded into "unchanged".
      if (typeof value !== "string") {
        return null;
      }
      if (effectiveAltText(node) === value) {
        return null;
      }
      // A placement-less image MINTS one, exactly as the Mode row above does
      // and for the same reason: refusing would leave the box showing a
      // description the document never took.
      return {
        kind: "update_node",
        node_id: node.id,
        patch: nodePatch({
          asset_placement: set({ ...node.asset_placement, alt_text: value }),
        }),
      };
    }

    // ── §1.3 row 2: Radius — the `all` box and the four corners (AD4.A) ──────
    // NO KIND GUARD, for the same reason the stroke and geometry rows have
    // none: hydrate's radius mapping is one path for every kind
    // (`scene-hydrate.ts:660-672`), so Lane B's rectangle and auto-layout
    // schemas reach this row without a second implementation.
    case "radius.all":
    case "radius.bottomLeft":
    case "radius.bottomRight":
    case "radius.topLeft":
    case "radius.topRight": {
      // RULING A28: the acceptance rule and the rounding are `radiusCommit`'s,
      // in `scene-hydrate.ts`, because the PANEL asks the same question — "did
      // this commit write anything, and what?" — to decide whether the four
      // corner boxes must re-state themselves. One rule, so the mirror and the
      // write cannot disagree.
      //
      // Upstream SUBSTITUTES where this refuses — `normalizeCornerRadius` folds
      // a negative or non-finite value to 0 (`RawStyleSection.tsx:181-183`) —
      // because its field is an `<input type="number" min="0">` that cannot
      // produce one. The ad's field is free text, so the same fold would be a
      // silent guess; §1.2's stroke width settles this the same way.
      const radius = radiusCommit(value);
      if (radius === null) {
        return null;
      }
      const corner = cornerWith(node.corner, property, radius);
      if (sameCorner(node.corner, corner)) {
        return null;
      }
      return {
        kind: "update_node",
        node_id: node.id,
        patch: nodePatch({ corner: set(corner) }),
      };
    }

    default:
      // Everything else is a later lane's row (§1.1/§1.4), inert (§3), dropped
      // (§5), or simply unmapped — no operation. §1.3's REMAINING rows (Replace
      // image, the AI suite) are not among them: they never reach this seam at
      // all, because they carry no `property`/`value` pair.
      return null;
  }
}

/**
 * §1.3 row 1 (Replace image) / §4: the node a replacement may land on — its
 * `ImageNode`, or `null` when this row is not offered for it.
 *
 * ONE rule, MANY call sites, which is why it is a function rather than an
 * inline pair of checks. Every flow that spends to mint a picture asks it
 * BEFORE the transport (`use-scene-replace-image.ts`'s upload,
 * `use-scene-image-ai.ts`'s generate and edit), because minting an asset that
 * then cannot be placed is a half write — a registry row nothing references,
 * paid for — and `sceneImagePlacementOperations` asks it again AFTER, because
 * the selection can be locked while the call is in flight. Duplicating the
 * condition would let them drift.
 *
 * The kind guard is hydrate's, the file header's standing rule: `imagePreviewSrc`
 * and `fillMode` are stated for an image node and for nothing else
 * (`scene-hydrate.ts`). The lock is §4, the same gate `sceneChangeToOperation`
 * applies to every property row.
 */
export function sceneImageReplacementTarget(node: Node): ImageNode | null {
  if (node.kind.kind !== "image" || node.locked) {
    return null;
  }
  return node.kind;
}

/**
 * §1.3: the document change behind EVERY way a picture reaches an image node —
 * Replace image (upload), Generate, and candidate Accept. The canonical
 * `upsert_asset` + `place_asset_in_node` pair, or `null` for no write.
 *
 * ONE FUNCTION FOR THREE FLOWS, per the coordinator's ruling of 2026-08-21.
 * Step 2 shipped the upload row overwriting `alt_text` with the new asset's
 * label (the plan's own line, written before an Alt-text control existed); step
 * 3 adds that control, which makes alt text USER-AUTHORED ACCESSIBILITY
 * CONTENT — and silently replacing a person's description with
 * `ad4a-upload-test.png` on the next image swap is the defect this lane has
 * been closing all phase, in its most damaging form. Upstream's own regenerate
 * carries it forward (`currentPlacement`), and two paths disagreeing about a
 * user's content is worse than touching a shipped row, so all three now share
 * this one rule.
 *
 * THE PAIR AND ITS ORDER ARE THE ENGINE'S, never rebuilt here:
 * `buildNodePlacementOperations` (`engine/scene/assetLibrary.ts`, a verbatim
 * upstream port) returns exactly those two, in that order, and the order is
 * load-bearing rather than stylistic — `Scene::place_asset_in_node` looks the
 * record up in `scene.assets` first and fails `op.asset_missing` when it is not
 * there (`lumen-core/src/operations.rs:666-671`). One batch, so the two land as
 * ONE undo step and the canvas repaints once.
 *
 * THE PLACEMENT CARRIES FORWARD. `place_asset_in_node` REPLACES the node's
 * whole `asset_placement` (`operations.rs:691`), so a bare `{alt_text}` — what
 * the plan's line reads as on its own — would drop the fit and the focal point:
 * the Mode select beside this control would go on saying "Fill" over a node the
 * upload had just reset to the absent-fit default, and the crop would recentre.
 * Upstream carries the same two fields forward for the same reason
 * (`ImageInspectorSection.tsx::currentPlacement`), though it also DEFAULTS a
 * missing fit to `cover`; this does not, because on this lane an absent fit IS
 * `contain` (`effectiveImageFit`, with the exporter/rasterizer evidence), so
 * minting one would silently change the picture.
 *
 * A32: because the placement is built as `{...stored, alt_text}`, every other
 * field is identical to the stored one BY CONSTRUCTION — which is exactly the
 * invariant `sameAltText` rests on. A caller that ever mints a field here must
 * widen that guard with it; the invariant is pinned by its own test.
 */
export function sceneImagePlacementOperations(
  node: Node,
  record: AssetRecord,
): Operation[] | null {
  const image = sceneImageReplacementTarget(node);
  if (!image) {
    return null;
  }
  const placement: AssetPlacement = {
    ...node.asset_placement,
    // THE ALT TEXT CARRIES FORWARD, and falls back to the asset's own label
    // only for a node that has none. Passed explicitly rather than left to
    // `withDefaultAlt`'s `?? record.label`, so the value the guard below
    // compares is the value that gets written.
    alt_text: node.asset_placement?.alt_text ?? record.label,
  };
  // A change that changes nothing is not a write. Reachable in one gesture on
  // every path: `POST /assets` deduplicates by content, and `/assets/generate`
  // keys a generation cache on prompt + model + size, so re-picking the same
  // file — or re-running the same prompt — hands back the record this node
  // already points at, under a placement it already holds.
  if (image.asset_id === record.id && sameAltText(node.asset_placement, placement)) {
    return null;
  }
  return buildNodePlacementOperations(record, node.id, placement);
}

/**
 * §1.1 row 1: the ONE page-size write, in the canonical form the engine mints
 * for a size authored in the page's own unit (genad2 Task 6; it was PX-only
 * until then).
 *
 * `normalizePageSize` is the engine's own constructor (a verbatim upstream
 * port, `engine/scene/pageGeometry.ts`) and is exactly what the standalone
 * editor's custom W/H fields commit through
 * (`DocumentPageSection.tsx:180-190` `customPageSize`). Using it settles the
 * three fields the plan's `{...page.size}` spread would have carried over,
 * and each answer is the engine's, not ours:
 *
 *   • `orientation` — RECOMPUTED from the numbers written
 *     (`orientationForDimensions`). The engine does not derive it on apply
 *     (`operations.rs::update_page` stores the `PageSize` verbatim) and the
 *     editor's own Orientation field is a read-only render of `width > height`,
 *     so a spread would leave a resized 1920×1200 page still claiming
 *     `portrait`.
 *   • `source` / `output` — REPLACED, not kept. This is the sharp end of the
 *     px trap: hydrate's `pageDisplaySize` reads `output` FIRST, so a
 *     spread that left the old raster on a resized page would make the
 *     inspector re-read the OLD size — the select snapping back to the
 *     previous preset while the canvas showed the new one.
 *   • `unit` — the canonical `pt` box with the authored size on `source`, which
 *     is what `is_canonical_page_size` (lumen-core `page_geometry.rs`) means
 *     by canonical; a literal `unit: "px"` page is legacy geometry the engine
 *     flags with LUMV0805.
 *
 * BOTH dimensions are floored here, not just the typed one. `normalizePageSize`
 * SUBSTITUTES 1 for any non-finite or non-positive value
 * (`pageGeometry.ts` `normalizePositiveDimension`) — a silent guess, and
 * exactly what the null contract forbids — so a page whose displayed size
 * cannot state one of its dimensions refuses the write instead of turning a
 * width edit into a 1px-tall document. The floor is §1.1's own "min 1", so a
 * sub-pixel page is refused rather than rounded.
 *
 * genad2 Task 6: the UNIT is now a parameter. §1.1 shipped px-only — this
 * function hard-coded `unit: "px"`, so an A4 page's W/H edit rewrote a
 * millimetre document as a pixel one and DROPPED `output.physical`. The
 * normalizer has always spoken every unit (`outputForSource` mints `physical`
 * for mm/in, `raster` for px, nothing for pt); only this call site was px.
 */
function pageSizeOperation(
  page: Page,
  width: number,
  height: number,
  unit: Unit,
  preset: PagePreset,
): Operation | null {
  if (!isUsablePageDimension(width) || !isUsablePageDimension(height)) {
    return null;
  }
  return updatePageSize(
    page,
    normalizePageSize({ height, preset, unit, width }),
  );
}

/**
 * §1.1 row 1's PRESET SELECT half: its three labels are CLIENT vocabulary that
 * spell px sizes, so they always write px and always write `custom` — none of
 * them is one of the engine's own `PagePreset`s. Unchanged by Task 6, on
 * purpose: picking "Story (9:16) - 1080x1920" on an A4 page really does mean
 * "make this a 1080x1920 pixel page".
 */
function pxPageSizeOperation(
  page: Page,
  width: number,
  height: number,
): Operation | null {
  return pageSizeOperation(page, width, height, "px", "custom");
}

/** §1.1: a page dimension the inputs can honestly state — finite, and at least
 * the contract's 1. The floor is unit-blind (1 px, 1 mm, 1 in), which is
 * §1.1's shipped contract rather than the engine's own (any positive number is
 * legal; a non-positive one is LUMV0121) — a page smaller than one unit is
 * refused rather than rounded. */
function isUsablePageDimension(value: number): boolean {
  return Number.isFinite(value) && value >= 1;
}

/**
 * genad2 Task 6: the `preset` a W/H commit writes — the page's OWN preset when
 * the committed numbers still ARE that preset, `custom` otherwise.
 *
 * §1.1 stamped `custom` unconditionally, so re-typing 297 into an A4 page's H
 * demoted the document to a custom size while changing nothing about it. The
 * table is the engine's, verbatim from `lumen-core/page_geometry.rs::
 * page_size_for_preset`, stated here rather than added to `pageGeometry.ts`
 * (a byte-identical upstream port this lane may not edit) — and stated as
 * short/long because the engine sorts the pair by orientation, so A4 landscape
 * (297x210) is still A4.
 *
 * Deliberately NOT a promotion: a page stored as `custom` whose numbers happen
 * to be A4's stays `custom`. Naming a preset the document never claimed is the
 * same fabrication in the other direction.
 *
 * The record is TOTAL over `PagePreset` (genad2 Task 7 close-out sweep), not
 * `Partial`: a preset added to the engine's `PagePreset` union must be given
 * an answer HERE or the TypeScript build fails, rather than silently falling
 * through to `custom` and demoting every page of the new preset the first time
 * someone nudges its H. `custom` is `null` because it has no fixed size — the
 * one preset for which "no dimensions" is the truthful answer.
 */
const PRESET_DIMENSIONS: Record<
  PagePreset,
  { long: number; short: number; unit: Unit } | null
> = {
  a4: { long: 297, short: 210, unit: "mm" },
  custom: null,
  envelope_dl: { long: 220, short: 110, unit: "mm" },
  linkedin_ad: { long: 1200, short: 627, unit: "px" },
  us_letter: { long: 11, short: 8.5, unit: "in" },
};

function preservedPreset(
  page: Page,
  width: number,
  height: number,
  unit: Unit,
): PagePreset {
  const stored = page.size.preset;
  const dimensions = stored ? PRESET_DIMENSIONS[stored] : undefined;
  if (!stored || !dimensions || dimensions.unit !== unit) {
    return "custom";
  }
  return Math.min(width, height) === dimensions.short &&
    Math.max(width, height) === dimensions.long
    ? stored
    : "custom";
}

/**
 * §1.1 row 2: the node the Background rows write — the page's ROOT FRAME
 * (founder ruling: "edits the root frame's fill; the page-background property
 * is not the edit target"), or `null` when this control may not write.
 *
 * `rootFrameId` is IMPORTED from `scene-hydrate.ts`, not restated: the write
 * must land on the very node the panel read, and a second "which child is the
 * root frame?" rule is exactly the drift that file's one-table discipline
 * exists to prevent.
 *
 * Three refusals live here because both Background rows share them:
 *   • NO ROOT FRAME → null. AD2.4 hydrates the Background as the ColorControl
 *     none state in that case, and the plan says the write is a no-op.
 *   • LOCKED → null (§4, "lock gates every write path"). These rows land on a
 *     NODE, which carries a lock — unlike §1.1's size rows, whose `Page` does
 *     not (the function below explains that asymmetry).
 *   • MULTI-FILL → null (`isMultiFill`, upstream's own first clause).
 *
 * WHAT IS DELIBERATELY *NOT* REFUSED HERE — a root frame whose single fill is
 * a GRADIENT. §1.2's Color row refuses that (`isGradientGuarded`) because its
 * control is a BARE swatch: it cannot show a gradient at all, so a write there
 * would clobber one the user never saw. §1.1's swatch is not bare — a
 * fill-type select sits above it, and `BackgroundFillControl` renders the
 * swatch ONLY while that select says "Solid" (`inspector-primitives.tsx`), so
 * reaching this row means the user asked for a solid on purpose. Refusing
 * would also DEAD-END the gradient→solid transition, because the select itself
 * commits no colour (`backgroundPaint`'s `solid` case explains why).
 */
function backgroundTarget(scene: Scene, pageId: PageId): Node | null {
  const frameId = rootFrameId(scene, pageId);
  const root = frameId ? scene.nodes[frameId] : null;
  if (!root || root.locked || isMultiFill(root.fills)) {
    return null;
  }
  return root;
}

/**
 * §1.1 row 2 / §1.4 Shape: the fills write every SHAPE-fill row ends in — or
 * `null` when the mapped paint is the one the node ALREADY carries.
 *
 * A change that changes nothing is not a write. It matters most on a RADIAL
 * gradient: the dummy's fill object always carries an `angle` and
 * `Paint::RadialGradient` has no field for one (§8 authorizes no engine
 * change), so every tick of an angle drag maps to a paint identical to the
 * stored one — a document version per tick that changes nothing. The same is
 * true of `ColorControl`, which re-commits its hex on blur whether or not it
 * changed.
 *
 * It was written for §1.1's two canvas Background rows and takes any NODE, so
 * AD4.B step 3's node-addressed Fill rows share it whole rather than restating
 * the paint, the paint-id and the no-change rules a third time — the parameter
 * is `node` now for that reason (it was `root`). The §1.2 TEXT rows keep
 * AD3.1's behaviour and stay out of it deliberately.
 */
function backgroundFillsOperation(node: Node, paint: Paint): Operation | null {
  if (paintKey(node.fills[0]?.paint) === paintKey(paint)) {
    return null;
  }
  return updateNodeFills(node, [paintFill(node, paint)]);
}

/**
 * A paint's identity as one canonical string. There is no paint-equality
 * helper in the engine port to reuse, so this follows the codebase's own
 * technique for comparing a structured scene value — `scene-canvas-view.ts`'s
 * `textMeasurementSignature`, which folds a node's measurement inputs into one
 * delimited key rather than deep-equalling them.
 *
 * CANONICAL, not literal, on both of the spellings the stored bytes really
 * carry:
 *   • a hex compares LOWER-cased, because that is what `normalizeHex` writes
 *     while a stored paint may carry any casing (`#0E0B2E` in the real
 *     document) — `#0E0B2E` and `#0e0b2e` are the same colour, not a new
 *     document version.
 *   • a TOKEN compares without its author-facing `$` (AD4.0 step 3). The
 *     seeded ad's own paints carry the sugar (`$text.inverse`) while the kit's
 *     keys and the picker's writes are bare, and `resolveTokenColor` treats
 *     them as one token — so re-picking the swatch a frame already wears must
 *     not mint a version that changes only the sugar.
 * Everything else compares as stored, so a token never reads as equal to the
 * literal hex a write would put in its place (detaching a binding IS a
 * change).
 */
function paintKey(paint: Paint | undefined): string {
  if (!paint) {
    return "none";
  }
  switch (paint.kind) {
    case "solid":
      return `solid|${colorKey(paint.color)}`;
    case "token":
      return `token|${tokenKey(paint.token)}`;
    case "linear_gradient":
      return `linear|${paint.angle}|${stopsKey(paint.stops)}`;
    case "radial_gradient":
      return `radial|${stopsKey(paint.stops)}`;
  }
}

function stopsKey(stops: ColorStop[]): string {
  return stops
    .map((stop) => `${colorKey(stop.color)}@${stop.position}`)
    .join(",");
}

function colorKey(color: Color): string {
  switch (color.kind) {
    case "hex":
      return color.value.trim().toLowerCase();
    case "token":
      return `$${tokenKey(color.token)}`;
    case "oklch":
      return `oklch(${color.l},${color.c},${color.h},${color.alpha})`;
  }
}

/**
 * A token name with the author-facing `$` folded away, so the two spellings of
 * one binding compare equal.
 *
 * It folds `$` and NOTHING ELSE — deliberately identical to
 * `tokenColors.ts::resolveTokenColor`, which strips a leading `$` and looks the
 * rest up verbatim. FIX 4 (review): this used to `trim()` too, which made two
 * values the ENGINE treats differently compare equal here — a paint stored as
 * `" surface.brand"` resolves to nothing, and folding the space would have read
 * a pick of the real `surface.brand` as a no-op, leaving that document
 * unrepairable from the panel.
 */
function tokenKey(token: string): string {
  return token.startsWith("$") ? token.slice(1) : token;
}

/**
 * §1.1 row 2 / the plan's "2–6 stops": the DUMMY's own stop-count rule, which
 * is the stricter of the two authorities and therefore the one that binds.
 *
 * The ENGINE's floor is ONE stop — `linear(...)`/`radial(...)` reject an empty
 * stop list with LUMD0239/LUMD0240 (`lumen-core/src/dsl.rs`) — and it sets no
 * maximum; `lumen-core/src/validation.rs` and `preflight.rs` carry no gradient
 * rules at all. The dummy is where 2–6 comes from: `BackgroundFillControl`'s
 * "Add color stop" button is `disabled` at 6 stops (and `addStop` returns
 * early there), and every stop's Remove button is `disabled` at 2
 * (`inspector-primitives.tsx`). A list outside that range did not come from
 * this control, so it is not this control's write.
 */
const MIN_GRADIENT_STOPS = 2;
const MAX_GRADIENT_STOPS = 6;

/**
 * §1.1 row 2: the dummy's whole `InspectorBackgroundFill` → one `Paint`, or
 * `null`. The inverse of `scene-hydrate.ts`'s `paintState`, which is the
 * authority on every vocabulary here.
 *
 * The value arrives as `unknown` (it is the raw event detail), so the shape is
 * checked field by field rather than cast: this row is the ONE canvas row
 * whose committed value is an object, and a malformed one is not a write.
 */
function backgroundPaint(raw: unknown): Paint | null {
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const fill = raw as Partial<InspectorBackgroundFill>;
  switch (fill.type) {
    case "solid":
      // DELIBERATE NON-WRITE, and the one place in this file where refusing is
      // NOT the whole answer — it is a recorded gap. Read this before changing
      // it.
      //
      // The RULING (orchestrator, on review of this step) is that a solid fill
      // object should write THE SWATCH'S CURRENT COLOUR — what the panel is
      // displaying — and that refusing is correct only if the control's state
      // does not carry a usable one. It does not, on both counts:
      //
      //   1. THE EVENT DOES NOT CARRY IT. `BackgroundFillControl` hands
      //      `onFillChange` the fill object alone — `{angle, stops, type}` —
      //      and the swatch colour is a SEPARATE prop (`solidColor`, i.e. the
      //      sibling `state.backgroundColor`) that never enters it; the
      //      controller then dispatches that object verbatim
      //      (`use-inspector-controller.ts` `setValue`). Nothing on the wire
      //      states the colour, and this adapter is pure — it cannot read
      //      controller state.
      //   2. IN THE ONLY CASE THAT REACHES HERE, THAT STATE IS A FIXTURE. This
      //      event fires from the fill-type SELECT, so the document's paint is
      //      not solid — and hydrate deliberately states no `backgroundColor`
      //      for a non-solid paint (only facts hydrate), leaving the shared
      //      `DEFAULT_STATE` seed on screen. Committing it would
      //      write the dummy's seed into a real ad: a fabrication, and worse
      //      than `stops[0]`, which is at least a colour the document has.
      //
      // `stops[0]` is not the answer either: the stops are inert while solid
      // (`scene-hydrate.ts`'s `solidFill` says so; `backgroundFillCss` proves
      // it by ignoring them), and on a gradient→solid switch `stops[0]` is the
      // GRADIENT's first stop — again not what the panel is showing.
      //
      // So the colour arrives on the `backgroundColor` row instead, and
      // picking "Solid" alone changes nothing until a colour is picked. The
      // FOUNDER-FACING GAP that leaves (reported at this step's review): the
      // fix belongs to the control/hydrate seam — either the controller puts
      // the swatch colour on the `backgroundFill` event, or hydrate states a
      // truthful swatch colour beside a non-solid paint (upstream's own
      // `hexInputValue` shows `#000000`; the first stop is the other
      // candidate) — and both are rulings, not this adapter's to take.
      return null;
    case "linear-gradient": {
      // The angle is stored verbatim as an `f64` and rotation is modular, so
      // any FINITE angle is written as given — nothing is substituted. (The
      // control clamps to 0–360 before it ever commits.)
      if (typeof fill.angle !== "number" || !Number.isFinite(fill.angle)) {
        return null;
      }
      const stops = gradientStops(fill.stops);
      if (!stops) {
        return null;
      }
      return { angle: fill.angle, kind: "linear_gradient", stops };
    }
    case "radial-gradient": {
      const stops = gradientStops(fill.stops);
      if (!stops) {
        return null;
      }
      // §5-style recorded loss: the dummy's object always carries an angle and
      // `Paint::RadialGradient { stops }` has no field for it (`contracts.ts`;
      // `lumen-core/src/scene.rs`). §8 authorizes no engine change, so the
      // angle is DROPPED — it reverts to 0 on the next reload — and
      // `backgroundFillsOperation` keeps that loss from becoming a phantom
      // write.
      return { kind: "radial_gradient", stops };
    }
    default:
      return null;
  }
}

/** §1.1 row 2: the control's percent stops as the engine's 0–1 ones. */
function gradientStops(raw: unknown): ColorStop[] | null {
  if (!Array.isArray(raw)) {
    return null;
  }
  if (raw.length < MIN_GRADIENT_STOPS || raw.length > MAX_GRADIENT_STOPS) {
    return null;
  }
  const stops: ColorStop[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) {
      return null;
    }
    const stop = entry as { color?: unknown; position?: unknown };
    // ONE unmappable stop refuses the WHOLE write — a partially-mapped
    // gradient is a fabrication. This is also what protects a token-bound
    // stop: `colorText` states a token colour as its `$name`, which is not a
    // hex, so an angle drag on a brand-bound gradient refuses instead of
    // silently detaching every stop (§1.6 licenses detaching on a raw COLOUR
    // write, which an angle drag is not).
    const hex = typeof stop.color === "string" ? normalizeHex(stop.color) : null;
    if (hex === null) {
      return null;
    }
    // The renderer CLAMPS a stop into 0–1 (`lumen-skia/src/render.rs`
    // `gradient_stops`) — a silent substitution, exactly what the null
    // contract forbids — and the control's own input clamps to 0–100 before it
    // commits, so an out-of-range position did not come from this control.
    if (
      typeof stop.position !== "number" ||
      !Number.isFinite(stop.position) ||
      stop.position < 0 ||
      stop.position > 100
    ) {
      return null;
    }
    stops.push({ color: { kind: "hex", value: hex }, position: stop.position / 100 });
  }
  // Stop ORDER rides through verbatim: hydrate preserves it, the engine stores
  // a list, and sorting here would invent a canonicalization neither side has.
  return stops;
}

/**
 * §1.1: one canvas-schema inspector change → one operation, or `null`.
 *
 * A SECOND function beside `sceneChangeToOperation`, not a branch inside it,
 * because these rows are raised by a PAGE-addressed event and the canvas
 * selection has no node at all — there is nothing to hand a node adapter. Same
 * null contract, same house style, same file.
 *
 * The two §1.1 rows do NOT write the same thing, and that asymmetry is the
 * founder's ruling, not an accident: row 1 (size) is an `update_page`; row 2
 * (Background) is an `update_node` on the page's ROOT FRAME, because "the
 * page-background property is not the edit target".
 *
 * WHY NO LOCK GATE ON THE SIZE ROWS (§4, "lock gates every write path"): a
 * `Page` carries no `locked` field (`contracts.ts:118-126`) and hydration
 * never states one for the canvas schema (`hydrateSceneCanvasState` writes no
 * `locked`), so there is no lock there to honour — refusing on the root
 * frame's lock would be inventing a policy the contract does not have. §4
 * binds NODE rows, and the Background rows land on a node, so they DO carry
 * the gate (`backgroundTarget`).
 *
 * The preset table, the px conversion and the root-frame rule are all imported
 * from `scene-hydrate.ts` rather than restated: this function must be the
 * exact inverse of what the panel is showing, and hydrate is the authority on
 * all three.
 */
export function sceneCanvasChangeToOperation(
  detail: SceneChangeDetail,
  scene: Scene,
  pageId: PageId,
  /** §1.6's brand vocabulary, for the Background token row only — the node
   * function's parameter, with the same absent-means-no-token-write rule. */
  palette?: ScenePalette | null,
): Operation | null {
  // A page the live scene does not carry is never a write — the same posture
  // the node path takes when the selection and the scene disagree.
  const page = getPage(scene, pageId);
  if (!page) {
    return null;
  }

  // ── §1.1 row 2: Background — the whole fill object ───────────────────────
  // The one canvas row whose committed value is an OBJECT (the fill-type
  // select and the gradient editor commit `InspectorBackgroundFill` entire),
  // so it resolves AHEAD of the string coercion the other rows share — the
  // same posture the `locked` boolean takes in the node function.
  if (detail.property === "backgroundFill") {
    const root = backgroundTarget(scene, pageId);
    if (!root) {
      return null;
    }
    const paint = backgroundPaint(detail.value);
    if (!paint) {
      return null;
    }
    return backgroundFillsOperation(root, paint);
  }

  const value = typeof detail.value === "string" ? detail.value : null;
  if (value === null) {
    return null;
  }

  switch (detail.property) {
    // ── §1.1 row 1: the size preset select ───────────────────────────────────
    case "sizePreset": {
      // The engine has no per-platform presets (its own `PagePreset` names A4,
      // US Letter, the 1200×627 `linkedin_ad` banner, DL and custom), so the
      // three ratified labels are CLIENT vocabulary and every one of them
      // writes a custom size. "Custom" itself names no size — the W/H inputs
      // below carry it — so it misses this table and writes nothing, exactly
      // like a label the select does not offer.
      const preset = SIZE_PRESETS.find(
        (candidate) => candidate.label === value,
      );
      if (!preset) {
        return null;
      }
      return pxPageSizeOperation(page, preset.width, preset.height);
    }

    // ── §1.1 row 1: the Custom W/H inputs (the page's own unit, min 1) ───────
    case "customWidth":
    case "customHeight": {
      const typed = finiteNumber(value);
      // Min 1 is the contract's floor and the engine's (a non-positive page is
      // LUMV0121). The PRESERVED dimension gets the same floor inside
      // `pageSizeOperation`, which is where the refusal is explained.
      if (typed === null || typed < 1) {
        return null;
      }
      // genad2 Task 6: the page is read AS AUTHORED, through the very function
      // that put it on screen — never off `page.size.width/height`, which is a
      // canonical `pt` box whose numbers differ from what the user is looking
      // at (a fractional authored px rounds into `output.raster`; an A4 page's
      // 210x297 mm is a 595x842 pt box).
      //
      // Both halves of the commit come from that one read, so the write cannot
      // disagree with the display: the UNTOUCHED dimension is the number the
      // other box is showing, and the UNIT is the one printed beside them —
      // which is what makes typing 300 into an A4 page's H mean 300 mm. The
      // typed number is therefore never reinterpreted, and a physical page
      // stays physical (`output.physical` survives) instead of being silently
      // rewritten as a raster.
      const shown = pageDisplaySize(page);
      const width = detail.property === "customWidth" ? typed : shown.width;
      const height = detail.property === "customHeight" ? typed : shown.height;
      return pageSizeOperation(
        page,
        width,
        height,
        shown.unit,
        preservedPreset(page, width, height, shown.unit),
      );
    }

    // ── §1.1 row 2: Background — the solid swatch (§1.6 policy) ──────────────
    case "backgroundColor": {
      const root = backgroundTarget(scene, pageId);
      if (!root) {
        return null;
      }
      // NO `COLOR_NONE` BRANCH, deliberately — unlike §1.2's stroke row, whose
      // sentinel clears the strokes. `ColorControl` commits through
      // `commitColor`, which fires `onColorChange` only for a value matching
      // /^#[0-9A-F]{6}$/i, and its `none` prop (a DISABLED swatch) is never
      // passed by `BackgroundFillControl` (`inspector-primitives.tsx`). The
      // sentinel therefore cannot reach this seam, and a branch the UI cannot
      // reach would be untested speculation. It is refused below with every
      // other non-hex. (Hydration CAN show "none" on a fill-less root frame;
      // that is a display state, not a value this control ever commits.)
      const hex = normalizeHex(value);
      if (hex === null) {
        return null;
      }
      // The §1.6 trade, canvas-side: a raw hex detaches a token-bound root
      // frame's brand binding. Shares §1.2's Color row's paint and paint-id
      // rules (`solidHexPaint` / `paintFill`, both reached through
      // `backgroundFillsOperation`) — one implementation of "write a hex fill
      // onto a node", not two.
      return backgroundFillsOperation(root, solidHexPaint(hex));
    }

    // ── §1.6: the Background swatch's BRAND half ────────────────────────────
    // Shares `backgroundTarget`'s refusals (no root frame / locked /
    // multi-fill) and `backgroundFillsOperation`'s no-change rule, so
    // re-picking the token the frame already carries writes nothing.
    case "tokenBackgroundColor": {
      const root = backgroundTarget(scene, pageId);
      if (!root) {
        return null;
      }
      const paint = tokenPaint(palette, value);
      if (!paint) {
        return null;
      }
      return backgroundFillsOperation(root, paint);
    }

    default:
      // Every §1.2 node row and anything unmapped — no operation.
      return null;
  }
}
