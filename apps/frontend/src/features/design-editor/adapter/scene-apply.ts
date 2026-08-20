import type {
  Fill,
  Node,
  Operation,
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
  updateTextNode,
} from "../engine/scene/operations";
import {
  isNodeDirectGeometryEditable,
  isNodePinned,
} from "../engine/scene/sceneQueries";
import { COLOR_NONE } from "./scene-hydrate";

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
 * Addressing (`selectionId` / `documentVersion` / "is this event for the node
 * I hold?") is the CALLER's gate, exactly as `hooks/use-inspector-writes.ts:78-89`
 * enforces it for the web lane — this adapter is pure and holds no selection.
 * It is deliberately not re-checked here: §1.1's canvas Background edits the
 * ROOT FRAME's fill while the selection is the (empty) canvas, so the addressed
 * selection and the written node legitimately differ, and a `selectionId ===
 * node.id` assertion inside the adapter would have to be special-cased away
 * again the moment that lane lands.
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
  selectionId: string;
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
 * The ported hex normalization (`ColorSwatchControl.tsx:256-261`
 * `normalizeHexInput`): lowercase, `#rrggbb` accepted, `#rrggbbaa` truncated to
 * six digits. ONE deliberate divergence — upstream falls back to a silent
 * `#000000` for anything else; we return `null`, because a silent black is
 * exactly the kind of guess the null contract forbids.
 */
function normalizeHex(raw: string): string | null {
  const trimmed = raw.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(trimmed)) {
    return trimmed.toLowerCase();
  }
  if (/^#[0-9a-fA-F]{8}$/.test(trimmed)) {
    return trimmed.slice(0, 7).toLowerCase();
  }
  return null;
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
 */
function isGradientGuarded(fills: Fill[]): boolean {
  if (fills.length > 1) {
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
 * §1.6: the single solid fill a hex swatch commits. The paint id is the node's
 * EXISTING fill id when it has one (preserving paint identity across an edit),
 * falling back to the id the standalone editor mints
 * (`ColorSwatchControl.tsx:236-238`, `paint_${node.id}_fill`).
 *
 * A raw hex DETACHES any brand token on that paint — the ratified §1.6 trade.
 * The user-facing "this leaves your brand palette" note is Gate G-B chrome
 * (§6 item 2) that does not exist yet; this comment is deliberately the only
 * place it is mentioned.
 */
function solidHexFill(node: Node, hex: string): Fill {
  return {
    id: node.fills[0]?.id ?? `paint_${node.id}_fill`,
    paint: { color: { kind: "hex", value: hex }, kind: "solid" },
  };
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
 * A pinned node with no resolvable box gets NO write (AD3.1 ruling): there is
 * nothing truthful to patch. NOTE — this is the one place this adapter is not
 * a strict inverse of hydration, which falls back to `node.transform` for a
 * boxless pin (as does upstream's `emitPosition`); the refusal is the
 * conservative direction and is pinned by its own test.
 *
 * When the box comes from `computed.layout_bounds` rather than a stored
 * `absolute_box`, the engine builder additionally bakes the box's size as
 * Fixed (`operations.ts:107-125`) — deliberate upstream behaviour: giving a
 * boxless pin its first box also defines its size.
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
  if (isNodePinned(scene, node.id)) {
    const box: Rect | null =
      node.absolute_box ?? node.computed?.layout_bounds ?? null;
    if (!box) {
      return null;
    }
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
