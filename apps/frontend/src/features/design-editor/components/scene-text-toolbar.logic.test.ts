import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { adBrandKit } from "../adapter/__fixtures__/brand-kit-colors";
import { buildScenePalette } from "../adapter/scene-palette";
import type { RangeFormatState } from "../engine/scene/textSpans";
import {
  SCENE_TEXT_MARK_CONTROLS,
  SCENE_TEXT_TOOLBAR_BOX_GAP,
  SCENE_TEXT_TOOLBAR_EDGE_GAP,
  sceneTextFillColor,
  sceneTextFillPatch,
  sceneTextMarkPatch,
  sceneTextMarkState,
  sceneTextMarkUnavailableReason,
  sceneTextStyleChord,
  sceneTextToolbarPosition,
  sceneTextToolbarSwatches,
} from "./scene-text-toolbar.logic";

/**
 * Rung C: the pure decisions behind the scene formatting toolbar — what a
 * toggle click authors from a tri-state, which keyboard chords map to which
 * channel, where the floating bar sits over the stage, and what the colour
 * control offers and writes.
 *
 * The colour cases run against the REAL brand kit the seeded ad is bound to
 * (`adapter/__fixtures__/brand-kit-colors`), never a hand-written token map —
 * the same discipline `scene-palette.test.ts` keeps.
 */

const PALETTE = buildScenePalette(adBrandKit());

const STAGE = { width: 1000, height: 800 };
const TOOLBAR = { width: 300, height: 40 };

/* -------------------------------------------------------------------------
 * The four mark toggles
 * ---------------------------------------------------------------------- */

test("the toolbar offers exactly the four span channels the engine has", () => {
  assert.deepEqual(
    SCENE_TEXT_MARK_CONTROLS.map((control) => control.channel),
    ["bold", "italic", "underline", "strikethrough"],
  );
});

test("a toggle turns the channel ON unless the whole selection already has it", () => {
  assert.deepEqual(sceneTextMarkPatch("bold", "off"), { bold: true });
  assert.deepEqual(sceneTextMarkPatch("bold", "on"), { bold: false });
  // MIXED means part of the selection lacks it — one click makes it uniform.
  assert.deepEqual(sceneTextMarkPatch("italic", "mixed"), { italic: true });
  assert.deepEqual(sceneTextMarkPatch("underline", "off"), { underline: true });
  assert.deepEqual(sceneTextMarkPatch("strikethrough", "on"), {
    strikethrough: false,
  });
});

test("a control reads its own channel's tri-state, and is inert on a caret", () => {
  const state = {
    bold: "on",
    italic: "mixed",
    underline: "off",
    strikethrough: "off",
    fill: { kind: "uniform", paint: null },
  } as const;
  const kitHasBoth = { family: "Inter", faces: { bold: true, italic: true } };
  assert.deepEqual(
    sceneTextMarkState("bold", state, { collapsed: false, inert: false, ...kitHasBoth }),
    {
      pressed: "on",
      disabled: false,
      reason: null,
    },
  );
  assert.deepEqual(
    sceneTextMarkState("italic", state, { collapsed: false, inert: false, ...kitHasBoth }),
    {
      pressed: "mixed",
      disabled: false,
      reason: null,
    },
  );
  // Founder-visible item 4: a collapsed caret disables the span toggles —
  // whole-node styling lives in the inspector, and `applyStyleToRange` no-ops
  // on an empty range anyway.
  assert.deepEqual(
    sceneTextMarkState("bold", state, { collapsed: true, inert: false, ...kitHasBoth }),
    {
      pressed: "on",
      disabled: true,
      reason: null,
    },
  );
  // G-H / the lock: the session's own inert flag disables everything.
  assert.deepEqual(
    sceneTextMarkState("bold", state, { collapsed: false, inert: true, ...kitHasBoth }),
    {
      pressed: "on",
      disabled: true,
      reason: null,
    },
  );
});

test("a mark whose face the kit lacks is disabled and says why", () => {
  const state: RangeFormatState = {
    bold: "off",
    italic: "off",
    underline: "off",
    strikethrough: "off",
    fill: { kind: "uniform", paint: null },
  };
  const faces = { bold: false, italic: false };
  assert.deepEqual(
    sceneTextMarkState("bold", state, {
      collapsed: false,
      inert: false,
      family: "seasonMix",
      faces,
    }),
    { pressed: "off", disabled: true, reason: "No bold face for “seasonMix” in the brand kit" },
  );
  assert.deepEqual(
    sceneTextMarkState("italic", state, {
      collapsed: false,
      inert: false,
      family: "seasonMix",
      faces,
    }),
    { pressed: "off", disabled: true, reason: "No italic face for “seasonMix” in the brand kit" },
  );
  // Underline/strikethrough never depend on a face.
  assert.equal(
    sceneTextMarkState("underline", state, {
      collapsed: false,
      inert: false,
      family: "seasonMix",
      faces,
    }).disabled,
    false,
  );
  // With the faces present, nothing changes from before.
  const ok = { bold: true, italic: true };
  assert.deepEqual(
    sceneTextMarkState("bold", state, {
      collapsed: false,
      inert: false,
      family: "seasonMix",
      faces: ok,
    }),
    { pressed: "off", disabled: false, reason: null },
  );
});

test("the face reason is exact copy, per channel and family", () => {
  assert.equal(
    sceneTextMarkUnavailableReason("bold", "Söhne", { bold: false, italic: true }),
    "No bold face for “Söhne” in the brand kit",
  );
  assert.equal(
    sceneTextMarkUnavailableReason("italic", "Söhne", { bold: true, italic: false }),
    "No italic face for “Söhne” in the brand kit",
  );
  assert.equal(
    sceneTextMarkUnavailableReason("bold", "Söhne", { bold: true, italic: false }),
    null,
  );
  assert.equal(
    sceneTextMarkUnavailableReason("strikethrough", "Söhne", { bold: false, italic: false }),
    null,
  );
});

/* -------------------------------------------------------------------------
 * The keyboard chords
 * ---------------------------------------------------------------------- */

test("⌘/Ctrl + B / I / U toggle their channels", () => {
  assert.equal(
    sceneTextStyleChord({ key: "b", metaKey: true, ctrlKey: false, altKey: false, shiftKey: false }),
    "bold",
  );
  assert.equal(
    sceneTextStyleChord({ key: "i", metaKey: false, ctrlKey: true, altKey: false, shiftKey: false }),
    "italic",
  );
  assert.equal(
    sceneTextStyleChord({ key: "u", metaKey: true, ctrlKey: false, altKey: false, shiftKey: false }),
    "underline",
  );
  // Caps lock reports the upper-case letter; it is the same chord.
  assert.equal(
    sceneTextStyleChord({ key: "B", metaKey: true, ctrlKey: false, altKey: false, shiftKey: false }),
    "bold",
  );
});

test("no chord exists for strikethrough or colour, and no bare letter is one", () => {
  for (const key of ["s", "x", "k"]) {
    assert.equal(
      sceneTextStyleChord({ key, metaKey: true, ctrlKey: false, altKey: false, shiftKey: false }),
      null,
      key,
    );
  }
  assert.equal(
    sceneTextStyleChord({ key: "b", metaKey: false, ctrlKey: false, altKey: false, shiftKey: false }),
    null,
  );
  // A modified chord is somebody else's shortcut, not ours.
  assert.equal(
    sceneTextStyleChord({ key: "b", metaKey: true, ctrlKey: false, altKey: false, shiftKey: true }),
    null,
  );
  assert.equal(
    sceneTextStyleChord({ key: "i", metaKey: true, ctrlKey: false, altKey: true, shiftKey: false }),
    null,
  );
});

/* -------------------------------------------------------------------------
 * Where the bar floats
 * ---------------------------------------------------------------------- */

test("the toolbar centres above the edited box", () => {
  const position = sceneTextToolbarPosition({
    box: { left: 400, top: 300, width: 200, height: 60 },
    stage: STAGE,
    toolbar: TOOLBAR,
  });
  assert.equal(position.placement, "above");
  assert.equal(position.left, 500 - TOOLBAR.width / 2);
  assert.equal(position.top, 300 - TOOLBAR.height - SCENE_TEXT_TOOLBAR_BOX_GAP);
});

test("a box near the top of the stage flips the toolbar BELOW it", () => {
  const position = sceneTextToolbarPosition({
    box: { left: 400, top: 10, width: 200, height: 60 },
    stage: STAGE,
    toolbar: TOOLBAR,
  });
  assert.equal(position.placement, "below");
  assert.equal(position.top, 10 + 60 + SCENE_TEXT_TOOLBAR_BOX_GAP);
});

test("the toolbar is clamped inside the stage on both edges", () => {
  const left = sceneTextToolbarPosition({
    box: { left: -40, top: 300, width: 60, height: 60 },
    stage: STAGE,
    toolbar: TOOLBAR,
  });
  assert.equal(left.left, SCENE_TEXT_TOOLBAR_EDGE_GAP);
  const right = sceneTextToolbarPosition({
    box: { left: 980, top: 300, width: 60, height: 60 },
    stage: STAGE,
    toolbar: TOOLBAR,
  });
  assert.equal(
    right.left,
    STAGE.width - TOOLBAR.width - SCENE_TEXT_TOOLBAR_EDGE_GAP,
  );
});

test("a stage narrower than the toolbar still puts it on screen, not off the left", () => {
  const position = sceneTextToolbarPosition({
    box: { left: 10, top: 200, width: 40, height: 20 },
    stage: { width: 200, height: 400 },
    toolbar: TOOLBAR,
  });
  assert.equal(position.left, SCENE_TEXT_TOOLBAR_EDGE_GAP);
});

test("a box below the stage's bottom keeps the toolbar inside it", () => {
  const position = sceneTextToolbarPosition({
    box: { left: 400, top: 5, width: 200, height: 900 },
    stage: STAGE,
    toolbar: TOOLBAR,
  });
  assert.equal(position.placement, "below");
  assert.equal(
    position.top,
    STAGE.height - TOOLBAR.height - SCENE_TEXT_TOOLBAR_EDGE_GAP,
  );
});

/* -------------------------------------------------------------------------
 * `topInset` — the occupied band at the top of the stage (D3a)
 *
 * The live walk (2026-08-24, seeded 1200×1200 ad): the headline sits near the
 * top of the artboard, the bar placed itself ~47 stage px above it, and that
 * landed inside the G-D banner band — which the seeded ad ALWAYS shows (the
 * non-dismissible brand-font fallback). `elementFromPoint` at the Bold button
 * returned the banner's span, so rung C was mouse-unreachable on it.
 *
 * The rule is geometric, not banner-aware: `topInset` is however much of the
 * stage's top is already spoken for, and the toolbar treats it as the top edge
 * — room is measured from there, and the clamp floors there.
 * ---------------------------------------------------------------------- */

test("a top inset moves the edge the toolbar measures its room against", () => {
  const box = { left: 400, top: 120, width: 200, height: 60 };
  // With a clear stage there IS room above (120 - 40 - 10 = 70 ≥ 12).
  const clear = sceneTextToolbarPosition({ box, stage: STAGE, toolbar: TOOLBAR });
  assert.equal(clear.placement, "above");
  assert.equal(clear.top, 70);
  // An 80px band at the top (a banner) makes the same 70 a collision, so the
  // bar flips below the node rather than under the banner.
  const occupied = sceneTextToolbarPosition({
    box,
    stage: { ...STAGE, topInset: 80 },
    toolbar: TOOLBAR,
  });
  assert.equal(occupied.placement, "below");
  assert.equal(occupied.top, 120 + 60 + SCENE_TEXT_TOOLBAR_BOX_GAP);
});

test("a top inset that still leaves room above keeps the toolbar above", () => {
  const position = sceneTextToolbarPosition({
    box: { left: 400, top: 300, width: 200, height: 60 },
    stage: { ...STAGE, topInset: 80 },
    toolbar: TOOLBAR,
  });
  assert.equal(position.placement, "above");
  assert.equal(position.top, 300 - TOOLBAR.height - SCENE_TEXT_TOOLBAR_BOX_GAP);
});

test("the clamp floors on the inset, so a squeezed toolbar never lands under it", () => {
  // A box tall enough that BELOW clamps against the stage bottom: the clamp's
  // floor is the inset, not 0, so the bar cannot be squeezed into the band.
  const position = sceneTextToolbarPosition({
    box: { left: 400, top: 5, width: 200, height: 900 },
    stage: { width: 200, height: 100, topInset: 60 },
    toolbar: TOOLBAR,
  });
  assert.equal(position.top, 60 + SCENE_TEXT_TOOLBAR_EDGE_GAP);
});

test("an absent inset is the old behaviour exactly — a clear stage top", () => {
  const box = { left: 400, top: 300, width: 200, height: 60 };
  assert.deepEqual(
    sceneTextToolbarPosition({ box, stage: { ...STAGE, topInset: 0 }, toolbar: TOOLBAR }),
    sceneTextToolbarPosition({ box, stage: STAGE, toolbar: TOOLBAR }),
  );
});

/* -------------------------------------------------------------------------
 * The stacking order (D3b)
 *
 * The other half of the same walk finding: even correctly placed, an
 * INFORMATIONAL banner must never eat a click meant for an INTERACTIVE
 * surface. Asserted against the stylesheets themselves because that is where
 * the ordering lives — the same discipline `scene-image-ai.test.ts` keeps.
 * ---------------------------------------------------------------------- */

const CANVAS_STYLESHEET = readFileSync(
  new URL("./scene-artifact-canvas.module.css", import.meta.url),
  "utf8",
);
const TOOLBAR_STYLESHEET = readFileSync(
  new URL("./scene-text-toolbar.module.css", import.meta.url),
  "utf8",
);

/** The `z-index` a rule declares, or null when it declares none. */
function zIndexOf(stylesheet: string, selector: string): number | null {
  const rule = new RegExp(`\\${selector} \\{([^}]*)\\}`).exec(stylesheet);
  const declared = rule ? /z-index:\s*(\d+)/.exec(rule[1]) : null;
  return declared ? Number(declared[1]) : null;
}

test("the interactive text surfaces stack ABOVE the informational banners", () => {
  const banners = zIndexOf(CANVAS_STYLESHEET, ".bannerLayer");
  const overlay = zIndexOf(CANVAS_STYLESHEET, ".textEditOverlay");
  const toolbar = zIndexOf(TOOLBAR_STYLESHEET, ".anchor");
  assert.equal(banners, 40);
  assert.ok(overlay !== null && overlay > banners);
  assert.ok(toolbar !== null && toolbar > banners);
  // And the bar stays above the caret it belongs to, as it always has.
  assert.ok(toolbar !== null && overlay !== null && toolbar > overlay);
});

/* -------------------------------------------------------------------------
 * The colour control
 * ---------------------------------------------------------------------- */

test("the swatches are the document's own brand vocabulary, ramps hidden", () => {
  const swatches = sceneTextToolbarSwatches(PALETTE);
  assert.equal(swatches.length, 20);
  assert.equal(
    swatches.some((swatch) => swatch.label.startsWith("palette.")),
    false,
  );
});

test("no kit means NO swatches — never a fixture palette writing phantom tokens", () => {
  assert.deepEqual(sceneTextToolbarSwatches(null), []);
});

test("a brand swatch writes a TOKEN binding, so the run keeps following the kit", () => {
  assert.deepEqual(sceneTextFillPatch(PALETTE, { kind: "token", label: "text.inverse" }), {
    fill: { kind: "token", token: "text.inverse" },
  });
});

test("a token this kit does not offer writes nothing at all", () => {
  assert.equal(sceneTextFillPatch(PALETTE, { kind: "token", label: "Primary" }), null);
  assert.equal(sceneTextFillPatch(null, { kind: "token", label: "text.inverse" }), null);
});

test("§1.6's custom half: a hex writes a solid paint, normalized", () => {
  assert.deepEqual(sceneTextFillPatch(PALETTE, { kind: "hex", value: "#FF0000" }), {
    fill: { kind: "solid", color: { kind: "hex", value: "#ff0000" } },
  });
  // Eight digits truncate to six, exactly as every other colour row does.
  assert.deepEqual(sceneTextFillPatch(PALETTE, { kind: "hex", value: "#11223344" }), {
    fill: { kind: "solid", color: { kind: "hex", value: "#112233" } },
  });
});

test("an unusable hex writes nothing — a silent black is the guess we refuse", () => {
  assert.equal(sceneTextFillPatch(PALETTE, { kind: "hex", value: "red" }), null);
  assert.equal(sceneTextFillPatch(PALETTE, { kind: "hex", value: "" }), null);
});

test("Clear removes the override, back to the node's own fill", () => {
  assert.deepEqual(sceneTextFillPatch(PALETTE, { kind: "clear" }), { fill: null });
});

test("the colour the control SHOWS: the override, or the node's fill when there is none", () => {
  // `{kind:"uniform", paint:null}` means the range carries no override at all,
  // so the honest swatch is the node's own painted colour.
  assert.equal(
    sceneTextFillColor(PALETTE, { kind: "uniform", paint: null }, "#C7C2F5"),
    "#C7C2F5",
  );
  assert.equal(
    sceneTextFillColor(
      PALETTE,
      { kind: "uniform", paint: { kind: "solid", color: { kind: "hex", value: "#ff0000" } } },
      "#C7C2F5",
    ),
    "#ff0000",
  );
  assert.equal(
    sceneTextFillColor(
      PALETTE,
      { kind: "uniform", paint: { kind: "token", token: "surface.brand" } },
      "#C7C2F5",
    ),
    "#533AFD",
  );
});

test("a MIXED selection shows no colour — and neither does an unresolvable token", () => {
  assert.equal(sceneTextFillColor(PALETTE, { kind: "mixed" }, "#C7C2F5"), null);
  assert.equal(
    sceneTextFillColor(
      PALETTE,
      { kind: "uniform", paint: { kind: "token", token: "not.a.token" } },
      "#C7C2F5",
    ),
    null,
  );
});
