import {
  normalizeHex,
  scenePaletteColor,
  scenePaletteToken,
  type ScenePalette,
  type ScenePaletteOption,
} from "../adapter/scene-palette";
import type {
  RangeFillState,
  RangeFormatState,
  StylePatch,
  TriState,
} from "../engine/scene/textSpans";

/**
 * Rung C: the pure decisions behind the scene formatting toolbar
 * (`scene-text-toolbar.tsx`) — the control set, what a click authors, the
 * keyboard chords, the floating position, and the colour vocabulary.
 *
 * The same split, and the same reason, as `web-rich-text-toolbar.logic.ts`
 * beside it: this repo's runner (`tsx --test`) cannot render React, so the
 * component holds only the DOM and event work that must touch a real tree and
 * every decision it makes lives here, where it is tested.
 *
 * ── WHAT IS LIFTED, AND WHAT IS NEW ──────────────────────────────────────
 * Standing constraint 2 (presentation truth): the scene toolbar reuses the web
 * toolbar's visual language rather than commissioning a new one
 * (founder-visible item 2), so the CONTROL VOCABULARY here is deliberately its
 * sibling's — the same four marks in the same order with the same glyphs and
 * the same tri-state pressed/mixed treatment, and `richTextAriaPressed`'s aria
 * mapping is imported rather than restated.
 *
 * What could NOT be lifted is the positioning: the web toolbar floats
 * `position: fixed` over an iframe in viewport coordinates, while this one is
 * an absolutely-positioned sibling of the canvas inside the stage, in the same
 * STAGE px the caret overlay and the selection outline live in. Same math,
 * different frame — {@link sceneTextToolbarPosition} is the web toolbar's
 * `computeToolbarPosition` in that frame.
 */

/** The four span channels the engine's `TextSpan` actually carries. */
export type SceneTextMarkChannel =
  | "bold"
  | "italic"
  | "underline"
  | "strikethrough";

export interface SceneTextMarkControl {
  channel: SceneTextMarkChannel;
  label: string;
  glyph: string;
  /** The chord that also toggles it, or null where none exists. */
  shortcut: string | null;
}

/**
 * The mark row, mirroring `RICH_TEXT_MARK_CONTROLS` (`engine/webRichText.ts`)
 * order and glyphs exactly.
 *
 * Strikethrough carries NO chord: the web lane's ⇧⌘X is a Lexical binding, and
 * minting a scene-only shortcut for one of four marks would be inventing UI.
 * The button is the whole affordance (and says so in its title).
 */
export const SCENE_TEXT_MARK_CONTROLS: readonly SceneTextMarkControl[] = [
  { channel: "bold", label: "Bold", glyph: "B", shortcut: "⌘B" },
  { channel: "italic", label: "Italic", glyph: "I", shortcut: "⌘I" },
  { channel: "underline", label: "Underline", glyph: "U", shortcut: "⌘U" },
  { channel: "strikethrough", label: "Strikethrough", glyph: "S", shortcut: null },
] as const;

/**
 * What a click on one mark authors: the channel goes ON unless the WHOLE
 * selection already carries it. A `mixed` selection therefore becomes uniformly
 * styled on the first click and uniformly unstyled on the second — the
 * behaviour every text editor has, and the reason the patch reads the tri-state
 * rather than a boolean.
 */
export function sceneTextMarkPatch(
  channel: SceneTextMarkChannel,
  state: TriState,
): StylePatch {
  const next = state !== "on";
  switch (channel) {
    case "bold":
      return { bold: next };
    case "italic":
      return { italic: next };
    case "underline":
      return { underline: next };
    case "strikethrough":
      return { strikethrough: next };
  }
}

/** Which face-dependent marks the selected node's family can actually paint. */
export interface SceneTextFaceAvailability {
  bold: boolean;
  italic: boolean;
}

/**
 * Why a mark cannot be applied, or null. Only bold and italic need a face; the
 * copy is the founder-ratified sentence (Plan 1, 2026-09-04) and names the family
 * so the user knows which font to add to the kit.
 */
export function sceneTextMarkUnavailableReason(
  channel: SceneTextMarkChannel,
  family: string,
  faces: SceneTextFaceAvailability,
): string | null {
  if (channel === "bold" && !faces.bold) {
    return `No bold face for “${family}” in the brand kit`;
  }
  if (channel === "italic" && !faces.italic) {
    return `No italic face for “${family}” in the brand kit`;
  }
  return null;
}

/**
 * One mark button's rendered state.
 *
 * Three gates, any of which disables the button:
 *
 *  • `collapsed` — founder-visible item 4: with a caret and no range there is
 *    nothing to style (`applyStyleToRange` no-ops on an empty range), and
 *    whole-node styling already lives in the inspector;
 *  • `inert` — the session's own gate (a locked node, or Gate G-H's in-flight
 *    turn);
 *  • `faces` — the kit has no face for this mark; the button carries the reason
 *    as its title, so a toggle that could only write an unpaintable weight says
 *    so instead of silently doing nothing.
 */
export function sceneTextMarkState(
  channel: SceneTextMarkChannel,
  format: RangeFormatState,
  {
    collapsed,
    inert,
    family,
    faces,
  }: { collapsed: boolean; inert: boolean; family: string; faces: SceneTextFaceAvailability },
): { pressed: TriState; disabled: boolean; reason: string | null } {
  const reason = sceneTextMarkUnavailableReason(channel, family, faces);
  return { pressed: format[channel], disabled: collapsed || inert || reason !== null, reason };
}

/**
 * The chord a key event fires, or null.
 *
 * ⌘/Ctrl + B / I / U only. Shift and Alt disqualify a chord outright — those
 * combinations belong to the browser and to other surfaces — and no chord
 * exists for strikethrough or colour.
 */
export function sceneTextStyleChord(event: {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}): SceneTextMarkChannel | null {
  if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.altKey) {
    return null;
  }
  switch (event.key.toLowerCase()) {
    case "b":
      return "bold";
    case "i":
      return "italic";
    case "u":
      return "underline";
    default:
      return null;
  }
}

/** The web toolbar's `EDGE_GAP`, in stage px: the minimum gap to any stage edge. */
export const SCENE_TEXT_TOOLBAR_EDGE_GAP = 12;
/** The web toolbar's `RANGE_GAP`, in stage px: the gap to the edited box. */
export const SCENE_TEXT_TOOLBAR_BOX_GAP = 10;

export interface SceneTextToolbarPosition {
  left: number;
  top: number;
  placement: "above" | "below";
}

/**
 * Where the bar sits over the stage, in the STAGE px the caret overlay is
 * positioned in.
 *
 * `computeToolbarPosition`'s rules, one frame over: centred on the edited box,
 * above it when there is room and below it otherwise, and clamped so it can
 * never leave the stage. Unlike the web toolbar it never answers null — the
 * session is open and the box is on the stage by construction, and a hidden
 * toolbar over a live caret would be a session with no way to format.
 *
 * ── `topInset` (D3a, live walk 2026-08-24) ───────────────────────────────
 * The walk edited the seeded ad's top-of-artboard headline. There WAS room
 * above it by the rule above, so the bar went above — straight into the G-D
 * banner band, which that ad always shows (the non-dismissible brand-font
 * fallback). `elementFromPoint` at the Bold button returned the banner's span
 * and a real mouse sequence there did nothing.
 *
 * `topInset` is how much of the stage's top is already spoken for, measured by
 * the host (0 when nothing is). The rule stays the same GEOMETRIC one — "is
 * there room above?" — with the top edge moved down to the inset, so a bar
 * that would land in an occupied band flips below the node instead. It is not
 * banner-aware and does not need to be: anything the host declares occupied
 * behaves identically, and a fixed 40px guess would be wrong the moment a
 * banner wrapped to two lines.
 *
 * The clamp floors on the inset too, so the below case cannot be squeezed back
 * up into the band by a short stage. Where the two must overlap anyway (a
 * stage with no room on either side), the stylesheet's stacking order is what
 * keeps the bar clickable — the two halves of D3 are deliberately independent.
 */
export function sceneTextToolbarPosition({
  box,
  stage,
  toolbar,
}: {
  box: { left: number; top: number; width: number; height: number };
  /** `topInset` is the occupied band at the stage's top, in stage px; absent
   * means a clear stage, which is the pre-D3a behaviour exactly. */
  stage: { width: number; height: number; topInset?: number };
  toolbar: { width: number; height: number };
}): SceneTextToolbarPosition {
  const inset = Math.max(0, stage.topInset ?? 0);
  const ceiling = inset + SCENE_TEXT_TOOLBAR_EDGE_GAP;
  const centre = box.left + box.width / 2;
  const left = Math.min(
    stage.width - toolbar.width - SCENE_TEXT_TOOLBAR_EDGE_GAP,
    Math.max(SCENE_TEXT_TOOLBAR_EDGE_GAP, centre - toolbar.width / 2),
  );
  const above = box.top - toolbar.height - SCENE_TEXT_TOOLBAR_BOX_GAP;
  const placement = above >= ceiling ? "above" : "below";
  const top =
    placement === "above"
      ? above
      : Math.min(
          stage.height - toolbar.height - SCENE_TEXT_TOOLBAR_EDGE_GAP,
          box.top + box.height + SCENE_TEXT_TOOLBAR_BOX_GAP,
        );
  return {
    left: Math.max(SCENE_TEXT_TOOLBAR_EDGE_GAP, left),
    top: Math.max(ceiling, top),
    placement,
  };
}

/** What the colour control was asked to write. */
export type SceneTextFillChoice =
  | { kind: "token"; label: string }
  | { kind: "hex"; value: string }
  | { kind: "clear" };

/**
 * §1.6's colour policy, applied to a RANGE instead of a node: the kit's brand
 * swatches are what the picker offers, and with no kit attached it offers
 * NOTHING rather than the dummy's fixture palette — a label validated against
 * nothing is not a token, and `{kind:"token", token:"Primary"}` is a binding no
 * kit could resolve (`scene-palette.ts`'s own rule, at the same gate).
 */
export function sceneTextToolbarSwatches(
  palette: ScenePalette | null | undefined,
): readonly ScenePaletteOption[] {
  return palette?.options ?? [];
}

/**
 * The fill patch a colour pick authors, or null when nothing may be written.
 *
 * The three cases are §1.6's, verbatim: a brand swatch writes a TOKEN binding
 * (so the run keeps following the kit), a custom hex writes a solid paint
 * (`normalizeHex`'s null-on-garbage contract — a silent `#000000` is exactly
 * the guess this lane refuses), and Clear removes the override so the range
 * paints with the node's own fill again.
 *
 * `StylePatch`'s fill is narrowed to solid-or-token at the type level, so a
 * gradient — which the engine rejects on a span, LUMV0908 — is unrepresentable
 * here rather than refused later.
 */
export function sceneTextFillPatch(
  palette: ScenePalette | null | undefined,
  choice: SceneTextFillChoice,
): StylePatch | null {
  if (choice.kind === "clear") {
    return { fill: null };
  }
  if (choice.kind === "token") {
    const token = scenePaletteToken(palette, choice.label);
    return token === null ? null : { fill: { kind: "token", token } };
  }
  const hex = normalizeHex(choice.value);
  return hex === null
    ? null
    : { fill: { kind: "solid", color: { kind: "hex", value: hex } } };
}

/**
 * The colour the control SHOWS for the current selection, or null when it can
 * honestly show none.
 *
 * `{kind:"uniform", paint:null}` is the "no override" reading — the range
 * inherits the node — so the swatch is the node's own painted colour, which the
 * overlay already resolved off the render descriptor. A MIXED selection and an
 * unresolvable token both show nothing: an unpaintable swatch is worse than no
 * swatch (`buildScenePalette`'s own rule).
 */
export function sceneTextFillColor(
  palette: ScenePalette | null | undefined,
  fill: RangeFillState,
  nodeColor: string,
): string | null {
  if (fill.kind === "mixed") {
    return null;
  }
  const paint = fill.paint;
  if (paint === null) {
    return nodeColor;
  }
  if (paint.kind === "solid") {
    return paint.color.kind === "hex" ? paint.color.value : null;
  }
  if (paint.kind === "token") {
    return scenePaletteColor(palette, paint.token);
  }
  return null;
}
