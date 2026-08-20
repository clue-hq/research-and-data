import type { InspectorBackgroundFill } from "@/features/chat-shell/hooks/use-inspector-controller";
import type {
  Color,
  ColorStop,
  Fill,
  Node,
  Operation,
  Page,
  PageId,
  Paint,
  Rect,
  Scene,
  Stroke,
  TextAlign,
  VerticalAlign,
} from "../engine/scene/contracts";
import {
  updateNodeAbsoluteBox,
  updateNodeFills,
  updateNodeLocked,
  updateNodeStrokes,
  updateNodeTransform,
  updatePageSize,
  updateTextNode,
} from "../engine/scene/operations";
import { normalizePageSize } from "../engine/scene/pageGeometry";
import {
  getPage,
  isNodeDirectGeometryEditable,
  isNodePinned,
} from "../engine/scene/sceneQueries";
import {
  COLOR_NONE,
  SIZE_PRESETS,
  pagePixelSize,
  rootFrameId,
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
 * WHICH ROWS CARRY A KIND GUARD is decided by one rule: **the write's kind
 * condition is exactly hydrate's kind condition**, so the two stay inverses.
 *   • typography + `textColor` → text only. `scene-hydrate.ts:378-386` routes a
 *     text node's fill to `textColor` and every other kind's to
 *     `backgroundColor`, so accepting `textColor` for a rect would write a
 *     property that node does not hydrate.
 *   • stroke / position / rotation / lock → every kind, because hydrate's
 *     stroke and geometry mappings are one path for every kind
 *     (`scene-hydrate.ts:348-401`). Same posture as the web lane's radius row,
 *     which likewise refuses to invent a kind guard the mapping does not have.
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
 * A typed field's number, or `null`. The ad inspector's numeric fields are
 * free-text `InspectorInput`s firing per KEYSTROKE (`image-inspector.tsx:304`),
 * so "", "-" and "1e" are ordinary intermediate events, not commits: an empty
 * field is mid-edit, never a request to write 0 (JS's `Number("") === 0` would
 * say otherwise). Upstream's `NumberField` does not need this — it is an
 * `<input type="number">` and never sees the intermediate text.
 */
function finiteNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/** `fields.tsx:174` `roundForEditor`, ported at the one site upstream applies
 * it: the stroke width it stores. */
function roundForEditor(value: number): number {
  return Math.round(value * 1000) / 1000;
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

/**
 * One inspector change → one engine operation, or `null`.
 *
 * `isNodeDirectGeometryEditable` is the ready-made gate for the geometry rows
 * (unlocked AND (not solver-managed OR freehand)); it is the engine's own
 * predicate and is never re-implemented here.
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
      return updateNodeFills(node, [paintFill(node, paint)]);
    }

    // ── §1.2 row 2: Font family (§2 delta row 3 — the real vocabulary) ───────
    case "fontFamily": {
      if (!text || value.trim() === "") {
        return null;
      }
      return updateTextNode(node, { font_family: value });
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
      return updateTextNode(node, { font_size: size });
    }

    // ── §1.2 row 4: Weight — the nine named labels (§2 delta row 2) ──────────
    case "fontWeight": {
      if (!text) {
        return null;
      }
      const weight = FONT_WEIGHT_VALUES[value];
      if (weight === undefined) {
        return null;
      }
      return updateTextNode(node, { font_weight: weight });
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
      const valign = VALIGN_VALUES[value];
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
      // Keep the existing width. A strokeless node hydrates its width as "0"
      // (`scene-hydrate.ts:398-400`) — the truthful reading of "the existing
      // width" — and a zero-width stroke is not a stroke, so it clears.
      // DIVERGENCE from `RawStyleSection.tsx:38`, which defaults the width to
      // 1 and would mint a hairline the inspector's own width field says the
      // node does not have.
      const width = node.strokes[0]?.width ?? 0;
      if (width <= 0) {
        return updateNodeStrokes(node, []);
      }
      return updateNodeStrokes(node, [
        strokeWith(node, { color: { kind: "hex", value: hex }, kind: "solid" }, width),
      ]);
    }
    // ── §1.6: the stroke row's BRAND half ───────────────────────────────────
    // Same shape as the hex branch above and for the same reasons: the
    // existing width is kept (a strokeless node's is "0", which clears rather
    // than minting a hairline the width field says it does not have), and the
    // paint is the only thing that differs.
    case "tokenStrokeColor": {
      const paint = tokenPaint(palette, value);
      if (!paint) {
        return null;
      }
      const strokeWidthValue = node.strokes[0]?.width ?? 0;
      if (strokeWidthValue <= 0) {
        return updateNodeStrokes(node, []);
      }
      return updateNodeStrokes(node, [
        strokeWith(node, paint, strokeWidthValue),
      ]);
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
      // No existing stroke ⇒ no colour to keep, and inventing one is a guess
      // (upstream's `hexInputValueFromStroke` falls back to a hardcoded
      // `#256c70`, `RawStyleSection.tsx:185-191`). Refuse instead.
      if (!existing) {
        return null;
      }
      // The stored paint rides along VERBATIM: a width edit is not a colour
      // edit, so it must not detach a token-bound stroke (§1.6 binds raw
      // COLOUR writes). This too diverges from upstream's rebuild-as-solid.
      return updateNodeStrokes(node, [
        strokeWith(node, existing.paint, width),
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

    default:
      // Everything else is a later lane's row (§1.1/§1.3/§1.4), inert (§3),
      // dropped (§5), or simply unmapped — no operation.
      return null;
  }
}

/**
 * §1.1 row 1: the ONE page-size write, in the canonical form the engine mints
 * for an authored PX size.
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
 *     px trap: hydrate's `pagePixelSize` reads `output.raster` FIRST, so a
 *     spread that left the old raster on a resized page would make the
 *     inspector re-read the OLD size — the select snapping back to the
 *     previous preset while the canvas showed the new one.
 *   • `unit` — the canonical `pt` box with the authored px on `source`, which
 *     is what `is_canonical_page_size` (lumen-core `page_geometry.rs`) means
 *     by canonical; a literal `unit: "px"` page is legacy geometry the engine
 *     flags with LUMV0805.
 *
 * §1.1 is px-only (a `PageOutputSize.physical` a print page might carry is
 * therefore not preserved — a page authored in px has no physical output, and
 * the normalizer says so).
 *
 * BOTH dimensions are floored here, not just the typed one. `normalizePageSize`
 * SUBSTITUTES 1 for any non-finite or non-positive value
 * (`pageGeometry.ts` `normalizePositiveDimension`) — a silent guess, and
 * exactly what the null contract forbids — so a page whose displayed size
 * cannot state one of its dimensions refuses the write instead of turning a
 * width edit into a 1px-tall document. The floor is §1.1's own "min 1", so a
 * sub-pixel page is refused rather than rounded.
 */
function pxPageSizeOperation(
  page: Page,
  width: number,
  height: number,
): Operation | null {
  if (!isUsablePixelDimension(width) || !isUsablePixelDimension(height)) {
    return null;
  }
  return updatePageSize(
    page,
    normalizePageSize({ height, preset: "custom", unit: "px", width }),
  );
}

/** §1.1: a page dimension the inputs can honestly state — finite, and at least
 * the contract's one pixel. */
function isUsablePixelDimension(value: number): boolean {
  return Number.isFinite(value) && value >= 1;
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
 * §1.1 row 2: the fills write both Background rows end in — or `null` when the
 * mapped paint is the one the frame ALREADY carries.
 *
 * A change that changes nothing is not a write. It matters most on a RADIAL
 * gradient: the dummy's fill object always carries an `angle` and
 * `Paint::RadialGradient` has no field for one (§8 authorizes no engine
 * change), so every tick of an angle drag maps to a paint identical to the
 * stored one — a document version per tick that changes nothing. The same is
 * true of `ColorControl`, which re-commits its hex on blur whether or not it
 * changed. The scope is this row: the §1.2 rows keep AD3.1's behaviour.
 */
function backgroundFillsOperation(root: Node, paint: Paint): Operation | null {
  if (paintKey(root.fills[0]?.paint) === paintKey(paint)) {
    return null;
  }
  return updateNodeFills(root, [paintFill(root, paint)]);
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

/** A token name with the author-facing `$` folded away, so the two spellings
 * of one binding compare equal (`resolveTokenColor`'s own rule). */
function tokenKey(token: string): string {
  const trimmed = token.trim();
  return trimmed.startsWith("$") ? trimmed.slice(1) : trimmed;
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
      //      `DEFAULT_STATE` seed `#00F59B` on screen. Committing it would
      //      write the dummy's green into a real ad: a fabrication, and worse
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

    // ── §1.1 row 1: the Custom W/H inputs (px only, min 1) ───────────────────
    case "customWidth":
    case "customHeight": {
      const typed = finiteNumber(value);
      // Min 1 is the contract's floor and the engine's (a non-positive page is
      // LUMV0121). The PRESERVED dimension gets the same floor inside
      // `pxPageSizeOperation`, which is where the refusal is explained.
      if (typed === null || typed < 1) {
        return null;
      }
      // The UNTOUCHED dimension is read as PIXELS, through the very function
      // that put it on screen — never off `page.size.width/height`, which is a
      // `pt` box whose number can differ from the px the user is looking at
      // (a fractional authored px rounds into `output.raster`).
      const shown = pagePixelSize(page);
      return detail.property === "customWidth"
        ? pxPageSizeOperation(page, typed, shown.height)
        : pxPageSizeOperation(page, shown.width, typed);
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
