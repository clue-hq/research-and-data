import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import type { Node, Scene } from "../engine/scene/contracts";
import { adBrandKit } from "./__fixtures__/brand-kit-colors";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
  adAutoLayout,
  adEllipse,
  adFrame,
  adGroup,
  adImage,
  adLine,
  adPlainText,
  adRect,
  adTokenText,
} from "./__fixtures__/scene-nodes";
import type { InspectorBackgroundFill } from "@/features/chat-shell/hooks/use-inspector-controller";
import { normalizePageSize } from "../engine/scene/pageGeometry";
import {
  COLOR_NONE,
  CUSTOM_SIZE_PRESET,
  SIZE_PRESETS,
  backgroundFillCommits,
  hydrateSceneCanvasState,
  hydrateSceneInspectorState,
  hydrateSceneSelectionState,
  mintedStrokeColor,
  mintedStrokeWidth,
  pageDisplaySize,
  radiusCommit,
  radiusCommitText,
  rootFrameId,
  sceneSelectionFor,
} from "./scene-hydrate";
import { buildScenePalette } from "./scene-palette";
import { setKitTokenMaps, setTokenColorMap } from "../engine/scene/renderAdapter";
import type { KitTokenMaps } from "../engine/scene/tokenColors";

/** The dummy ad inspector's own source, read off disk: a `.tsx` cannot be
 * imported under this runner (`tsx --test`, no DOM), so the vocabulary guard
 * below reads the literal instead. Same technique as
 * `scene-engine-banners.test.ts`, which pins upstream banner copy this way. */
const AD_INSPECTOR_SOURCE = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../chat-shell/components/image-inspector.tsx",
  ),
  "utf8",
);

/**
 * AD2.4: this file IS the ad-inspector mapping contract's §1 table for the
 * SCENE lane — selection routing (§1.4 + OQ-1/OQ-6, §5) and value hydration
 * (§1.0–§1.4), one `it` per control row, each citing its row.
 *
 * Every case runs against AD2.2's harvested bytes (`__fixtures__/scene-nodes`,
 * document `doc_ad22linkedinsquare00000000001`) — never a hand-written node.
 * Two contract rows have NO fixture coverage and are deliberately NOT faked
 * here (a `token` Dimension and a non-empty TEXT stroke were not plausible in
 * a real ad); both are marked `UNCOVERED` at their mapping site.
 *
 * Where a row needs a page the harvest does not have (a non-preset page size,
 * a page with no root frame), the test CLONES the real scene and edits that
 * one field — the derived-fixture technique AD2.3's canvas suite already uses
 * — rather than inventing a node.
 */

const SCENE = HARVESTED_AD_PAGE;
const AD_ROOT_FRAME_ID = "frame_ad_root";

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** The harvested page at another size, in the engine's canonical form for an
 * authored-px page (pt box + px source + px raster output all agreeing). */
function withPageSize(width: number, height: number): Scene {
  const scene = clone(SCENE);
  const page = scene.pages[AD_PAGE_ID];
  page.size = {
    ...page.size,
    height,
    output: { raster: { height_px: height, width_px: width } },
    source: { height, unit: "px", width },
    width,
  };
  return scene;
}

// ── §1.4 kind → schema (+ OQ-1, OQ-6 and the §5 unrepresented kinds) ────────

it("§1.4: a text node routes to the text schema", () => {
  assert.deepEqual(sceneSelectionFor(adTokenText(), AD_ROOT_FRAME_ID), {
    selection: "text",
    suppressAutoLayoutSection: false,
  });
});

it("§1.3/§1.4: an image node routes to the image schema", () => {
  assert.deepEqual(sceneSelectionFor(adImage(), AD_ROOT_FRAME_ID), {
    selection: "image",
    suppressAutoLayoutSection: false,
  });
});

it("§1.4: an auto_layout node routes to the auto-layout schema with all sections", () => {
  assert.deepEqual(sceneSelectionFor(adAutoLayout(), AD_ROOT_FRAME_ID), {
    selection: "auto-layout",
    suppressAutoLayoutSection: false,
  });
});

it("§1.4/OQ-1: a plain frame renders the auto-layout schema minus its Auto Layout section", () => {
  // The same real frame, seen while some OTHER node is the page root — the
  // non-root frame case (this document has exactly one frame, and it is root).
  assert.deepEqual(sceneSelectionFor(adFrame(), "some_other_root"), {
    selection: "auto-layout",
    suppressAutoLayoutSection: true,
  });
});

it("§1.1: the page's root frame IS the canvas selection", () => {
  assert.deepEqual(
    sceneSelectionFor(adFrame(), rootFrameId(SCENE, AD_PAGE_ID)),
    { selection: "canvas", suppressAutoLayoutSection: false },
  );
});

it("§1.4: a rect node routes to the rectangle schema", () => {
  assert.deepEqual(sceneSelectionFor(adRect(), AD_ROOT_FRAME_ID), {
    selection: "rectangle",
    suppressAutoLayoutSection: false,
  });
});

it("§1.4: an ellipse node routes to the ellipse schema", () => {
  assert.deepEqual(sceneSelectionFor(adEllipse(), AD_ROOT_FRAME_ID), {
    selection: "ellipse",
    suppressAutoLayoutSection: false,
  });
});

it("§1.4/OQ-6: a group node routes to the group schema", () => {
  assert.deepEqual(sceneSelectionFor(adGroup(), AD_ROOT_FRAME_ID), {
    selection: "group",
    suppressAutoLayoutSection: false,
  });
});

it("§5: a line node has NO schema — the selection resolves to null", () => {
  assert.equal(sceneSelectionFor(adLine(), AD_ROOT_FRAME_ID), null);
});

it("§1.1: rootFrameId is the page's first frame child, or null when it has none", () => {
  assert.equal(rootFrameId(SCENE, AD_PAGE_ID), AD_ROOT_FRAME_ID);
  assert.equal(rootFrameId(SCENE, "page_that_is_not_here"), null);
  const rootless = clone(SCENE);
  rootless.pages[AD_PAGE_ID].children = ["line_divider"];
  assert.equal(rootFrameId(rootless, AD_PAGE_ID), null);
});

// ── §1.0 header ────────────────────────────────────────────────────────────

it("§1.0: the header title is the real node name (never a Figma artifact)", () => {
  assert.equal(hydrateSceneInspectorState(adImage(), SCENE).title, "Hero image");
});

it("§1.0: Lock reads Node.locked", () => {
  assert.equal(hydrateSceneInspectorState(adImage(), SCENE).locked, false);
});

// ── §1.4 Layout section ────────────────────────────────────────────────────

it("§1.4/OQ-3: opacity 0.8 hydrates as the percent string '80'", () => {
  assert.equal(hydrateSceneInspectorState(adPlainText(), SCENE).opacity, "80");
});

it("§1.4/OQ-3: opacity 1.0 hydrates as '100'", () => {
  assert.equal(hydrateSceneInspectorState(adImage(), SCENE).opacity, "100");
});

it("§1.4/OQ-2: a fixed Dimension is mode Fixed with its fixed value", () => {
  const state = hydrateSceneInspectorState(adImage(), SCENE);
  assert.equal(state.widthMode, "Fixed");
  assert.equal(state.widthFixed, "1056");
  assert.equal(state.heightMode, "Fixed");
  assert.equal(state.heightFixed, "676");
});

it("§1.4/OQ-2: a hug Dimension is mode Hug and shows no fixed input", () => {
  const state = hydrateSceneInspectorState(adAutoLayout(), SCENE);
  assert.equal(state.heightMode, "Hug");
  assert.equal(state.heightFixed, "");
});

it("§1.4/OQ-2: a fill Dimension is mode Fill and shows no fixed input (weights stay out, §5)", () => {
  const state = hydrateSceneInspectorState(adGroup(), SCENE);
  assert.equal(state.widthMode, "Fill");
  assert.equal(state.widthFixed, "");
});

// ── §1.4 Dimensions W/H (AD4.B step 1) ─────────────────────────────────────

it("§1.4 Dimensions: a fixed axis states its OWN value in the W/H box", () => {
  // The dummy's scaffolding showed a flat `100` on every node; the box now
  // states the size the document has. `widthFixed` states the same number for
  // a fixed axis — the two keys differ only where the axis is NOT fixed (the
  // next two cases), which is exactly why the W/H box needs its own key.
  const state = hydrateSceneInspectorState(adImage(), SCENE);
  assert.equal(state.width, "1056");
  assert.equal(state.height, "676");
});

it("§1.4 Dimensions: a hug or fill axis states the SOLVED bounds, not the empty fixed input", () => {
  // `computed` is null on every STORED node (asserted above), so the solved box
  // is what the live engine scene carries and the harvest cannot: one field is
  // cloned and edited — `auto_row_copy`'s own solved geometry — rather than a
  // node invented to carry it. Rounding is `roundForEditor`'s, the editor's own.
  const scene = clone(SCENE);
  const node = scene.nodes.auto_row_copy; // width fixed 1056, height HUG
  node.computed = {
    layout_bounds: { height: 148.55555, width: 1056, x: 72, y: 96 },
    render_bounds: { height: 148.55555, width: 1056, x: 72, y: 96 },
  };
  const state = hydrateSceneInspectorState(node, scene);
  assert.equal(state.heightFixed, "", "a hug axis still has no FIXED input");
  assert.equal(state.height, "148.556", "but the W/H box states the solved size");
  assert.equal(state.width, "1056");
});

it("§1.4 Dimensions: an unsolved hug/fill axis states nothing rather than a number the node lacks", () => {
  const state = hydrateSceneInspectorState(adAutoLayout(), SCENE);
  assert.equal(adAutoLayout().computed, null);
  assert.equal(state.height, "");
  assert.equal(hydrateSceneInspectorState(adGroup(), SCENE).width, "");
});

it("§1.4/AD4.R: all five schema kinds state EVERY Layout key — no kind guard", () => {
  // The AD4.R rule at this file's `hydrateSceneInspectorState` header: a bound
  // row that hydration leaves unstated falls back to the dummy's fixture
  // default, which would state a number the node does not have. The four dummy
  // schemas plus OQ-1's plain Frame are the ones AD4.B binds.
  for (const node of [adFrame(), adAutoLayout(), adRect(), adEllipse(), adGroup()]) {
    const state = hydrateSceneInspectorState(node, SCENE);
    for (const key of [
      "height",
      "heightFixed",
      "heightMode",
      "opacity",
      "position",
      "rotation",
      "width",
      "widthFixed",
      "widthMode",
    ] as const) {
      assert.ok(Object.hasOwn(state, key), `${node.id} must state ${key}`);
    }
  }
});

it("§1.4: Position X/Y read the transform (`computed` is null on every stored node)", () => {
  assert.equal(adImage().computed, null);
  assert.deepEqual(hydrateSceneInspectorState(adImage(), SCENE).position, {
    x: "72",
    y: "452",
  });
});

it("§1.4: a pinned node's Position X/Y read its absolute_box, not its transform", () => {
  const pinned = clone(SCENE);
  const node = pinned.nodes.image_hero;
  node.position_mode = "absolute";
  node.absolute_box = { height: 676, width: 1056, x: 140, y: 900 };
  assert.deepEqual(hydrateSceneInspectorState(node, pinned).position, {
    x: "140",
    y: "900",
  });
});

/** A solved page-space box on a node the harvest never laid out — the
 * `scene-arrange.test.ts` `withGeometry` recipe, so a "what does the panel show
 * once the renderer has solved this page" case is still harvested bytes plus
 * one field. */
function withSolvedBoxes(
  boxes: Readonly<Record<string, { x: number; y: number; width: number; height: number }>>,
  base: Scene = SCENE,
): Scene {
  const scene = clone(base);
  for (const [nodeId, box] of Object.entries(boxes)) {
    const node = scene.nodes[nodeId];
    assert.ok(node, `fixture node ${nodeId} missing`);
    node.computed = { layout_bounds: { ...box }, render_bounds: { ...box } };
  }
  return scene;
}

it("§1.4/C-9 (Ruling C9-P2): a SOLVER-MANAGED child's Position X/Y state its SOLVED parent-relative offset, not the stored (0,0)", () => {
  // AD4.R — display and write must agree. A managed child's stored transform is
  // a dead number (the harvest's `text_headline`/`group_proof` are both (0,0));
  // the solver places it, and the C-9 freeze BAKES that solved offset onto the
  // transform (`editing.rs:1906-1910`: child solved box − container solved box)
  // before the panel's write lands. Showing the stored (0,0) while the first
  // commit writes into the baked frame would move the node ~700px in a space
  // the panel never showed. So the row states the offset the freeze will bake.
  const solved = withSolvedBoxes({
    auto_row_copy: { height: 296, width: 1056, x: 72, y: 72 },
    group_proof: { height: 40, width: 220, x: 780, y: 149 },
    text_headline: { height: 120, width: 640, x: 72, y: 72 },
  });
  assert.deepEqual(
    hydrateSceneInspectorState(solved.nodes.text_headline, solved).position,
    { x: "0", y: "0" },
  );
  // The one that lies today: stored (0,0), solved offset (708, 77) — the exact
  // pair Lane C live-verified (`_memory/2026-08-22-ad4c-canvas-gestures.md`).
  assert.deepEqual(solved.nodes.group_proof.transform.x, 0);
  assert.deepEqual(
    hydrateSceneInspectorState(solved.nodes.group_proof, solved).position,
    { x: "708", y: "77" },
  );
});

it("§1.4/C-9: a node the solver does NOT own keeps reading its transform, solved or not", () => {
  // The change is scoped to the `isNodeFreezableOnGesture` class exactly — the
  // same predicate the canvas grab and `panelWriteIntent` ask. A plain frame's
  // child owns its transform whether or not the page has been laid out, and a
  // freehand child of a FROZEN container owns it too (that transform IS the
  // baked offset), so neither may be re-derived from the solve.
  const solved = withSolvedBoxes({
    frame_ad_root: { height: 1080, width: 1080, x: 0, y: 0 },
    rect_accent_bar: { height: 8, width: 320, x: 500, y: 600 },
  });
  assert.deepEqual(
    hydrateSceneInspectorState(solved.nodes.rect_accent_bar, solved).position,
    { x: "72", y: "368" },
  );
  const free = clone(solved);
  free.nodes.auto_row_copy.layout = {
    ...free.nodes.auto_row_copy.layout!,
    layout_mode: "free",
  };
  free.nodes.auto_row_copy.computed = {
    layout_bounds: { height: 296, width: 1056, x: 72, y: 72 },
    render_bounds: { height: 296, width: 1056, x: 72, y: 72 },
  };
  free.nodes.group_proof.computed = {
    layout_bounds: { height: 40, width: 220, x: 780, y: 149 },
    render_bounds: { height: 40, width: 220, x: 780, y: 149 },
  };
  free.nodes.group_proof.transform = {
    ...free.nodes.group_proof.transform,
    x: 708,
    y: 77,
  };
  assert.deepEqual(
    hydrateSceneInspectorState(free.nodes.group_proof, free).position,
    { x: "708", y: "77" },
  );
});

it("§1.4/C-9: with NO solve to read, a managed child falls back to the stored transform", () => {
  // The harvest itself: `computed` is null on every stored node, so a panel
  // opened before the renderer has solved the page has nothing better to state
  // than the transform — the pre-C-9 behaviour, unchanged. Same for a solved
  // child whose CONTAINER is unsolved: the difference would be page space, not
  // parent space, which is not the number the freeze bakes.
  assert.equal(SCENE.nodes.group_proof.computed, null);
  assert.deepEqual(
    hydrateSceneInspectorState(adGroup(), SCENE).position,
    { x: "0", y: "0" },
  );
  const childOnly = withSolvedBoxes({
    group_proof: { height: 40, width: 220, x: 780, y: 149 },
  });
  assert.deepEqual(
    hydrateSceneInspectorState(childOnly.nodes.group_proof, childOnly).position,
    { x: "0", y: "0" },
  );
});

it("§1.4: Rotation reads transform.rotation", () => {
  assert.equal(hydrateSceneInspectorState(adImage(), SCENE).rotation, "0");
});

// ── §1.6 fills → the ColorControl state ────────────────────────────────────

it("§1.1/§1.6: a solid fill hydrates as its hex on the solid fill type", () => {
  const state = hydrateSceneInspectorState(adFrame(), SCENE);
  assert.equal(state.backgroundColor, "#0E0B2E");
  assert.equal(state.backgroundFill?.type, "solid");
});

it("A16/§1.6: a TOKEN-filled text states its token name in the swatch, never a fixture", () => {
  // The harvested headline's real fill is the `$text.inverse` brand token.
  // Leaving `textColor` unstated left the shared `DEFAULT_STATE` seed on
  // screen — the swatch claiming the headline is the seed colour while
  // it is brand-token coloured — and unlike the gradient case this control
  // ACCEPTS a write (§1.6's ratified detach), so the lie was live, not inert.
  const state = hydrateSceneInspectorState(adTokenText(), SCENE);
  assert.equal(state.tokenTextColor, "$text.inverse");
  assert.equal(state.textColor, "$text.inverse");
});

it("A16/§1.6: a GRADIENT-filled text states its first stop — the write stays guarded, only the display changes", () => {
  // UNCOVERED by the harvest (no text carries a gradient), so the scene is
  // cloned and ONE field is edited: `rect_accent_bar`'s real 3-stop paint onto
  // the headline. The refusal this display sits behind is unchanged and is
  // proven where it lives (`scene-apply.test.ts`, "§1.6 guard: a GRADIENT fill
  // is not writable through the single swatch").
  const scene = clone(SCENE);
  scene.nodes.text_headline.fills = [...adRect().fills];
  assert.equal(
    hydrateSceneInspectorState(scene.nodes.text_headline, scene).textColor,
    "#533AFD",
  );
});

it("§1.2/§1.6: a solid text fill hydrates as the text color", () => {
  assert.equal(hydrateSceneInspectorState(adPlainText(), SCENE).textColor, "#C7C2F5");
});

it("§1.6: a linear gradient hydrates its angle and its stops as 0–100 percent", () => {
  assert.deepEqual(hydrateSceneInspectorState(adRect(), SCENE).backgroundFill, {
    angle: 90,
    stops: [
      { color: "#533AFD", position: 0 },
      { color: "#8B5CF6", position: 50 },
      { color: "#EA2261", position: 100 },
    ],
    type: "linear-gradient",
  });
});

it("§1.6: a node with no fill hydrates as the ColorControl none state", () => {
  assert.equal(hydrateSceneInspectorState(adImage(), SCENE).backgroundColor, "none");
});

// ── §1.2/§1.4 Stroke section ───────────────────────────────────────────────

it("§1.4: the stroke color and width read strokes[0]", () => {
  const state = hydrateSceneInspectorState(adAutoLayout(), SCENE);
  assert.equal(state.strokeColor, "#2E2470");
  assert.equal(state.strokeWidth, "2");
});

it("§1.2: a node with no stroke hydrates none/0, never the dummy's width 1", () => {
  const state = hydrateSceneInspectorState(adPlainText(), SCENE);
  assert.equal(state.strokeColor, "none");
  assert.equal(state.strokeWidth, "0");
});

it("A16/§1.4: a GRADIENT stroke states its first stop — it used to read `none` on a node that has one", () => {
  // One field edited on a clone: the harvested gradient paint moved onto
  // `auto_row_copy`'s REAL stroke, so the width beside it is real too. Solid
  // and token strokes are unchanged (the row already read `color ?? token`).
  const scene = clone(SCENE);
  scene.nodes.auto_row_copy.strokes[0].paint = adRect().fills[0].paint;
  const state = hydrateSceneInspectorState(scene.nodes.auto_row_copy, scene);
  assert.equal(state.strokeColor, "#533AFD");
  assert.equal(state.strokeWidth, "2");
});

// ── §1.2 Typography ────────────────────────────────────────────────────────

it("rung A: the Text row reads TextNode.content verbatim — newlines included", () => {
  assert.equal(
    hydrateSceneInspectorState(adPlainText(), SCENE).content,
    "3.4x faster triage",
  );
  assert.equal(
    hydrateSceneInspectorState(adTokenText(), SCENE).content,
    "Every inbound fax, routed to the right EHR queue.",
  );
  // The STORED content, not the painted one: `text_transform` is a paint-time
  // concern, so an uppercasing node still states what it will be edited as.
  const multiline = clone(SCENE);
  const node = multiline.nodes.text_proof_stat;
  if (node.kind.kind === "text") node.kind.content = "3.4x\nfaster triage";
  assert.equal(
    hydrateSceneInspectorState(node, multiline).content,
    "3.4x\nfaster triage",
  );
});

it("rung A: a NON-text node states no content at all — the row is text-only", () => {
  for (const node of [adRect(), adImage(), adAutoLayout(), adGroup()]) {
    assert.equal(hydrateSceneInspectorState(node, SCENE).content, undefined, node.id);
  }
});

it("§1.2: the font family reads TextNode.font_family", () => {
  assert.equal(hydrateSceneInspectorState(adPlainText(), SCENE).fontFamily, "Inter");
});

it("token-styled inspector values follow the supplied kit, never another canvas's kit", () => {
  const scene = clone(SCENE);
  const node = scene.nodes.text_headline;
  assert.equal(node.kind.kind, "text");
  if (node.kind.kind !== "text") throw new Error("expected text");
  node.kind = { ...node.kind, font_family: "Inter", font_size: 16, font_weight: 400,
    style_token: "type.headline", font_size_token: "type.size.6xl" };
  const maps: KitTokenMaps = { colors: {}, typography: {
    "type.headline": { fontFamily: "Season Mix", fontSize: 80, fontWeight: 500 },
  }, numbers: { "type.size.6xl": 67.5 } };
  const before = JSON.stringify(scene);
  setKitTokenMaps({ colors: {}, typography: {
    "type.headline": { fontFamily: "Wrong Brand", fontSize: 32, fontWeight: 900 },
  }, numbers: {} });
  try {
    const state = hydrateSceneSelectionState(scene, AD_PAGE_ID, node, maps);
    assert.equal(state?.fontFamily, "Season Mix");
    assert.equal(state?.fontSize, "67.5");
    assert.equal(state?.fontWeight, "500 Medium");
    assert.equal(state?.typographyUnavailable, false);
    const loading = hydrateSceneSelectionState(scene, AD_PAGE_ID, node, null);
    assert.equal(loading?.fontFamily, "Inter");
    assert.equal(loading?.fontSize, "16");
    assert.equal(loading?.typographyUnavailable, true);
    const incomplete = structuredClone(maps);
    delete incomplete.typography["type.headline"];
    assert.equal(hydrateSceneSelectionState(scene, AD_PAGE_ID, node, incomplete)?.typographyUnavailable, true);
    assert.equal(JSON.stringify(scene), before);
  } finally {
    setTokenColorMap({});
  }
});

it("§1.2: the font size is the free number as a string", () => {
  assert.equal(hydrateSceneInspectorState(adPlainText(), SCENE).fontSize, "26");
  assert.equal(hydrateSceneInspectorState(adTokenText(), SCENE).fontSize, "54");
});

it("§1.2: the font weight is the nine-name label for its numeric weight", () => {
  assert.equal(
    hydrateSceneInspectorState(adPlainText(), SCENE).fontWeight,
    "600 Semi Bold",
  );
  assert.equal(
    hydrateSceneInspectorState(adTokenText(), SCENE).fontWeight,
    "700 Bold",
  );
});

it("§1.2: the horizontal alignment passes TextAlign through (justify included)", () => {
  assert.equal(
    hydrateSceneInspectorState(adTokenText(), SCENE).horizontalAlignment,
    "left",
  );
  const justified = clone(SCENE);
  const node = justified.nodes.text_headline;
  if (node.kind.kind === "text") node.kind.align = "justify";
  assert.equal(
    hydrateSceneInspectorState(node, justified).horizontalAlignment,
    "justify",
  );
});

it("§1.2: valign `center` is the dummy's `middle`; an absent valign is `top`", () => {
  assert.equal(
    hydrateSceneInspectorState(adTokenText(), SCENE).verticalAlignment,
    "middle",
  );
  assert.equal(
    hydrateSceneInspectorState(adPlainText(), SCENE).verticalAlignment,
    "top",
  );
});

it("§1.2: V-alignment is disabled when the height mode is hug", () => {
  assert.equal(hydrateSceneInspectorState(adTokenText(), SCENE).valignDisabled, true);
  assert.equal(hydrateSceneInspectorState(adGroup(), SCENE).valignDisabled, false);
});

// ── §1.3 Image ─────────────────────────────────────────────────────────────

it("§1.3: asset_placement.fit `cover` is the dummy's `Fill`", () => {
  assert.equal(hydrateSceneInspectorState(adImage(), SCENE).fillMode, "Fill");
});

it("§1.3: the radii read CornerRadii — BR before BL, the serialized-order trap", () => {
  assert.deepEqual(hydrateSceneInspectorState(adImage(), SCENE).radius, {
    all: "",
    bottomLeft: "96",
    bottomRight: "32",
    topLeft: "32",
    topRight: "32",
  });
});

it("§1.3: four equal corners fill the `all` box", () => {
  assert.deepEqual(hydrateSceneInspectorState(adRect(), SCENE).radius, {
    all: "5",
    bottomLeft: "5",
    bottomRight: "5",
    topLeft: "5",
    topRight: "5",
  });
});

// ── AD4.A: the two §1.3 rows the WRITE half binds (`scene-apply.ts`) ────────
//
// The read side existed before the write did; these prove it over the whole
// vocabulary rather than the one value the harvest happens to carry, because
// the write is now the exact inverse of it. Derived cases DEEP-COPY first: the
// fixture accessors hand out live references into the shared frozen
// `HARVESTED_AD_PAGE`, which every test file in the run imports as one module.

/** The harvested image with ONE field of a DEEP copy replaced. */
function imageWith(patch: Partial<Node>): Node {
  return { ...clone(SCENE).nodes.image_hero, ...patch };
}

it("§1.3 Mode: all three engine behaviours read as the dummy's three labels", () => {
  // `cover` is the harvest's own; the other two are the same real node with
  // one field changed. The dummy offers exactly these three (`FILL_MODES`).
  assert.equal(hydrateSceneInspectorState(adImage(), SCENE).fillMode, "Fill");
  assert.equal(
    hydrateSceneInspectorState(
      imageWith({ asset_placement: { ...adImage().asset_placement, fit: "contain" } }),
      SCENE,
    ).fillMode,
    "Fit",
  );
  assert.equal(
    hydrateSceneInspectorState(
      imageWith({ asset_placement: { ...adImage().asset_placement, fit: "crop" } }),
      SCENE,
    ).fillMode,
    "Crop",
  );
});

it("§1.3 Mode: an image with NO asset_placement states no mode, and the dummy's own default is the truth", () => {
  // `asset_placement` is `Option` + `skip_serializing_if` in the core
  // (`lumen-core/src/scene.rs:291`), so a placement-less image really is
  // absent on the wire. Only facts hydrate, so nothing is stated — and the
  // shared default that then stands (`DEFAULT_STATE.fillMode === "Fit"`) is
  // exactly what such a node RENDERS: the exporter maps `Some(Contain) | None`
  // onto the same `xMidYMid meet` (`lumen-export/src/svg.rs:1759-1770`), and
  // the rasterizer's `(_, Some(ratio))` arm agrees. The write half refuses a
  // "Fit" pick on such a node for that same reason.
  const node = imageWith({});
  delete node.asset_placement;
  assert.equal(hydrateSceneInspectorState(node, SCENE).fillMode, undefined);
});

it("§1.3 Radius: a corner TOKEN does not change what the five boxes read", () => {
  // UNCOVERED by the harvest: no harvested node carries `corner.token`. The
  // panel states the stored NUMBERS either way — upstream's own Radius fields
  // read `selectedNode.corner.top_left` and never the token
  // (`RawStyleSection.tsx:56-96`), and it is the same posture the stroke row
  // takes with `width_token`. RECORDED GAP: the renderer PREFERS a resolved
  // token over the four numbers (`renderAdapter.ts:270-301`), so a token-bound
  // node can paint a radius these boxes do not show; resolving it needs the
  // kit's radii, which `ScenePalette` (colours only) does not carry.
  const node = imageWith({});
  node.corner = { ...node.corner, token: "radius.card" };
  assert.deepEqual(hydrateSceneInspectorState(node, SCENE).radius, {
    all: "",
    bottomLeft: "96",
    bottomRight: "32",
    topLeft: "32",
    topRight: "32",
  });
});

it("only facts hydrate: a stored value that names an Object.prototype member states NOTHING", () => {
  // The read side has the same inherited-lookup hole as the write side, and it
  // is reachable from DATA rather than from a select: the label tables are keyed
  // on compile-time unions, but a stored document is JSON, so `fit:
  // "constructor"` would put a FUNCTION into inspector state (and, through the
  // spread that merges hydration over the defaults, an explicit `undefined`
  // would beat the default rather than fall back to it — which is why these
  // omit rather than assign).
  for (const key of ["constructor", "toString", "valueOf", "hasOwnProperty"]) {
    const image = { ...clone(SCENE).nodes.image_hero };
    image.asset_placement = { ...adImage().asset_placement, fit: key as never };
    assert.equal(
      hydrateSceneInspectorState(image, SCENE).fillMode,
      undefined,
      `fit ${key}`,
    );

    const text = { ...clone(SCENE).nodes.text_headline };
    text.kind = { ...adTokenText().kind, valign: key as never } as Node["kind"];
    assert.equal(
      hydrateSceneInspectorState(text, SCENE).verticalAlignment,
      undefined,
      `valign ${key}`,
    );

    // The align row differs from its three neighbours here, deliberately: it is
    // a BOUND row on a section that renders for every auto-layout node, so it
    // states the engine's default rather than nothing (see the L10 cases
    // below). The prototype key is still never SERVED as a label — which is
    // what this loop guards — it just resolves to "Start".
    const row = { ...clone(SCENE).nodes.auto_row_copy };
    row.layout = { ...adAutoLayout().layout!, align_x: key as never };
    assert.equal(
      hydrateSceneInspectorState(row, SCENE).alignX,
      "Start",
      `align_x ${key}`,
    );

    const weighted = { ...clone(SCENE).nodes.text_headline };
    weighted.kind = { ...adTokenText().kind, font_weight: key as never } as Node["kind"];
    assert.equal(
      hydrateSceneInspectorState(weighted, SCENE).fontWeight,
      undefined,
      `font_weight ${key}`,
    );
  }
});

it("RULING A28: `radiusCommit` IS the radius row's acceptance rule, and its text is what a box must read", () => {
  // ONE rule with two callers: `scene-apply.ts`'s `radius.*` row takes the
  // number, `RadiusControls`'s scene branch takes the text. They cannot
  // disagree about what a commit does, which is the whole reason it is here
  // rather than restated in the component.
  for (const refused of ["", " ", "abc", "-1", "-0.5", "1e", "24px", "NaN", "Infinity"]) {
    assert.equal(radiusCommit(refused), null, JSON.stringify(refused));
    assert.equal(radiusCommitText(refused), null, JSON.stringify(refused));
  }
  // Accepted, and CANONICAL: the text is what the document will hold, not the
  // spelling the user typed — `numberText` of the written number, i.e. exactly
  // what hydration states for that corner on the next read.
  const written: [string, number, string][] = [
    ["24", 24, "24"],
    ["12.5", 12.5, "12.5"],
    ["0", 0, "0"],
    ["007", 7, "7"],
    ["1e2", 100, "100"],
    [" 8 ", 8, "8"],
    // Upstream's own rounding (`roundForEditor`), applied by the same rule the
    // write applies, so the box cannot state a precision the document lost.
    ["12.3456789", 12.346, "12.346"],
  ];
  for (const [raw, value, text] of written) {
    assert.equal(radiusCommit(raw), value, raw);
    assert.equal(radiusCommitText(raw), text, raw);
  }
});

it("§1.3 Radius: an unrounded node reads the honest 0 — and no node reads an ABSENT corner", () => {
  // `corner` is REQUIRED on both sides of the wire — `pub corner: CornerRadii`
  // with no `#[serde(default)]` (`lumen-core/src/scene.rs:284`) and
  // non-optional in `contracts.ts:176` — so "no radius" is four zeroes, never
  // a missing block, and hydration carries no absent-corner branch to test.
  for (const node of Object.values(SCENE.nodes)) {
    assert.ok(node.corner, `harvested node ${node.id} carries no corner block`);
  }
  assert.deepEqual(hydrateSceneInspectorState(adGroup(), SCENE).radius, {
    all: "0",
    bottomLeft: "0",
    bottomRight: "0",
    topLeft: "0",
    topRight: "0",
  });
});

// ── §1.4 Auto Layout section ───────────────────────────────────────────────

it("§1.4: direction `row` is the dummy's horizontal; wrap reads the node kind", () => {
  const state = hydrateSceneInspectorState(adAutoLayout(), SCENE);
  assert.equal(state.direction, "horizontal");
  assert.equal(state.wrap, false);
});

it("§1.4: Gap and Grow read Node.layout", () => {
  const state = hydrateSceneInspectorState(adAutoLayout(), SCENE);
  assert.equal(state.gap, "32");
  assert.equal(state.grow, "0");
});

it("§1.4: padding [T,R,B,L] maps to the four Pad boxes", () => {
  assert.deepEqual(hydrateSceneInspectorState(adAutoLayout(), SCENE).padding, {
    bottom: "40",
    left: "44",
    right: "44",
    top: "40",
  });
});

it("§1.4: align_x/align_y hydrate the Start|Center|End|Space between|Stretch labels", () => {
  const state = hydrateSceneInspectorState(adAutoLayout(), SCENE);
  assert.equal(state.alignX, "Start");
  assert.equal(state.alignY, "Center");
  const spread = clone(SCENE);
  const node = spread.nodes.auto_row_copy;
  if (node.layout) {
    node.layout.align_x = "space_between";
    node.layout.align_y = "stretch";
  }
  const spreadState = hydrateSceneInspectorState(node, spread);
  assert.equal(spreadState.alignX, "Space between");
  assert.equal(spreadState.alignY, "Stretch");
});

it("§1.4: a node with no auto-layout props hydrates no Auto Layout values", () => {
  const state = hydrateSceneInspectorState(adRect(), SCENE);
  assert.equal(state.gap, undefined);
  assert.equal(state.grow, undefined);
  assert.equal(state.alignX, undefined);
  assert.equal(state.direction, undefined);
});

it("§1.4/L10: an AUTO-LAYOUT node with no `Node.layout` states the engine's own defaults", () => {
  // RULING L10 (AD4.B step 2): the Auto Layout section renders for every
  // `auto_layout` node, so every one of its rows must be STATED for every one
  // of them — the AD4.R "state every bound key" rule. `Node.layout` is
  // genuinely optional in the wire format (`contracts.ts`), and an auto-layout
  // node that carries none really does lay out at the engine's own
  // `defaultLayoutProps()`, so those are the honest values. Leaving them absent
  // let `DEFAULT_STATE`'s scaffolding seeds ("Space between"/"Center", the
  // dummy's invented anchors) stand over a real document.
  //
  // The harvest has exactly one auto-layout node and it DOES carry a layout, so
  // the field is cloned away — the AD2.4/AD2.5 derived-fixture technique.
  const scene = clone(SCENE);
  const node = scene.nodes.auto_row_copy;
  node.layout = null;
  const state = hydrateSceneInspectorState(node, scene);
  assert.equal(state.gap, "0");
  assert.equal(state.grow, "0");
  assert.deepEqual(state.padding, {
    bottom: "0",
    left: "0",
    right: "0",
    top: "0",
  });
  // `defaultLayoutProps()` anchors BOTH axes at `start` — not the dummy's
  // "Space between"/"Center" pair, which is what this row exists to displace.
  assert.equal(state.alignX, "Start");
  assert.equal(state.alignY, "Start");
  // Direction/wrap live on the node KIND and were already unconditional there.
  assert.equal(state.direction, "horizontal");
  assert.equal(state.wrap, false);
});

it("§1.4/L10: a layout that OMITS an anchor still states one — the same `start` the write half carries", () => {
  // The review finding this case exists for: `align_x`/`align_y` are optional
  // in the wire format (`contracts.ts:470-471`), so a node can carry a real
  // `Node.layout` — gap, padding, grow all present — and no anchors. While the
  // assignment was conditional, that node displayed `DEFAULT_STATE`'s invented
  // "Space between"/"Center" while `scene-apply.ts::storedAnchor` restated the
  // untouched axis as `start` on the very next commit: the panel and the
  // document disagreeing about the same node. Both halves now read the
  // engine's `defaultLayoutProps()`, so they cannot.
  const scene = clone(SCENE);
  const node = scene.nodes.auto_row_copy;
  assert.ok(node.layout, "fixture precondition: the node carries a layout");
  delete node.layout.align_x;
  delete node.layout.align_y;
  const state = hydrateSceneInspectorState(node, scene);
  assert.equal(state.alignX, "Start");
  assert.equal(state.alignY, "Start");
  // The layout's OTHER members are untouched by the fallback — this is an
  // anchor rule, not a whole-layout reset.
  assert.equal(state.gap, "32");
  assert.deepEqual(state.padding, {
    bottom: "40",
    left: "44",
    right: "44",
    top: "40",
  });

  // A garbled anchor (unreachable through the type system; reachable from a
  // malformed payload) resolves the same way rather than leaving the bound row
  // unstated — `vocabulary` refuses the value, the row still states one.
  const garbled = clone(SCENE);
  const other = garbled.nodes.auto_row_copy;
  if (other.layout) {
    other.layout.align_x = "middle" as never;
    other.layout.align_y = "justify" as never;
  }
  const garbledState = hydrateSceneInspectorState(other, garbled);
  assert.equal(garbledState.alignX, "Start");
  assert.equal(garbledState.alignY, "Start");
});

// ── §1.1 Canvas schema ─────────────────────────────────────────────────────

it("§1.1: a 1200x1200 page is an exact match for the LinkedIn square preset", () => {
  assert.equal(
    hydrateSceneCanvasState(SCENE, AD_PAGE_ID).sizePreset,
    "Linkedin square (1:1) - 1200x1200",
  );
});

it("§1.1: the other two ratified presets match on their size numbers", () => {
  assert.equal(
    hydrateSceneCanvasState(withPageSize(1080, 1350), AD_PAGE_ID).sizePreset,
    "Instagram portrait (4:5) - 1080x1350",
  );
  assert.equal(
    hydrateSceneCanvasState(withPageSize(1080, 1920), AD_PAGE_ID).sizePreset,
    "Story (9:16) - 1080x1920",
  );
});

it("§1.1: a non-preset page is Custom, with its W/H in px", () => {
  const state = hydrateSceneCanvasState(withPageSize(1200, 628), AD_PAGE_ID);
  assert.equal(state.sizePreset, "Custom");
  assert.equal(state.customWidth, "1200");
  assert.equal(state.customHeight, "628");
});

it("§1.1: a PRESET-matching page hydrates its real W/H too — the Custom boxes never open on a number the page does not have", () => {
  // AD4.0 review finding: the boxes appear the moment the user picks "Custom"
  // from the select, on a page that until that instant matched a preset. While
  // these two fields were filled only in the no-preset case, that reveal
  // showed the shared DEFAULT_STATE seed (1200x1200) — proven in the browser on
  // a 1080x1920 page — and the user then edited from a fabricated basis. The
  // write is the exact inverse of this function, so this function may not
  // display a size the page does not have.
  const square = hydrateSceneCanvasState(SCENE, AD_PAGE_ID);
  assert.equal(square.sizePreset, "Linkedin square (1:1) - 1200x1200");
  assert.equal(square.customWidth, "1200");
  assert.equal(square.customHeight, "1200");
  const story = hydrateSceneCanvasState(withPageSize(1080, 1920), AD_PAGE_ID);
  assert.equal(story.sizePreset, "Story (9:16) - 1080x1920");
  assert.equal(story.customWidth, "1080");
  assert.equal(story.customHeight, "1920");
});

// ── genad2 Task 6: pages that are not px ────────────────────────────────────
//
// The design agent now authors pages in ANY unit (px for digital, mm/in for
// print — `open_design_leg@4` births zero pages and the agent sets the page up
// itself). This panel was built for the seeded px ad and read every page as
// pixels, so an A4 page showed its `pt` canonical box (595x842) as if those
// numbers were pixels. `pageDisplaySize` is the unit-aware read that replaced
// it (the px-only `pagePixelSize` was deleted in the Task-7 close-out sweep —
// zero production consumers, and a px-named read is a hazard on a mm page).

/** A page authored in a real unit, minted by the engine's own constructor
 * (`pageGeometry.ts` — a verbatim upstream port), so every fixture below is a
 * shape the engine actually produces rather than one this test invented. */
function withAuthoredPageSize(
  width: number,
  height: number,
  unit: "in" | "mm" | "pt" | "px",
  preset: "a4" | "custom" | "envelope_dl" | "linkedin_ad" | "us_letter" = "custom",
): Scene {
  const scene = clone(SCENE);
  scene.pages[AD_PAGE_ID].size = normalizePageSize({ height, preset, unit, width });
  return scene;
}

it("Task 6: an A4 page displays 210x297 MM, not its 595x842 pt box", () => {
  const scene = withAuthoredPageSize(210, 297, "mm", "a4");
  const page = scene.pages[AD_PAGE_ID];
  // The canonical box really is the misleading number this panel used to show.
  assert.equal(Math.round(page.size.width), 595);
  assert.equal(Math.round(page.size.height), 842);
  assert.deepEqual(pageDisplaySize(page), { height: 297, unit: "mm", width: 210 });
  const state = hydrateSceneCanvasState(scene, AD_PAGE_ID);
  assert.equal(state.customWidth, "210");
  assert.equal(state.customHeight, "297");
  assert.equal(state.customSizeUnit, "mm");
});

it("Task 6: an inches page displays inches", () => {
  const scene = withAuthoredPageSize(8.5, 11, "in", "us_letter");
  assert.deepEqual(pageDisplaySize(scene.pages[AD_PAGE_ID]), {
    height: 11,
    unit: "in",
    width: 8.5,
  });
  const state = hydrateSceneCanvasState(scene, AD_PAGE_ID);
  assert.equal(state.customWidth, "8.5");
  assert.equal(state.customHeight, "11");
  assert.equal(state.customSizeUnit, "in");
});

it("Task 6: a px page's display is BYTE-IDENTICAL — the raster still wins, and the unit says px", () => {
  // The whole px half of this contract is "change nothing". The harvested ad
  // and the fractional-authored page (whose raster ROUNDS, so its box and its
  // px differ) are the two shapes the retired px-only read was written for,
  // and `pageDisplaySize` must answer both with the same numbers — which is
  // why deleting that read costs nothing.
  const harvested = SCENE.pages[AD_PAGE_ID];
  assert.deepEqual(pageDisplaySize(harvested), {
    height: 1200,
    unit: "px",
    width: 1200,
  });
  const fractional = withAuthoredPageSize(1200, 628.4, "px").pages[AD_PAGE_ID];
  assert.equal(fractional.size.source?.height, 628.4);
  assert.deepEqual(pageDisplaySize(fractional), {
    height: 628,
    unit: "px",
    width: 1200,
  });
  const state = hydrateSceneCanvasState(SCENE, AD_PAGE_ID);
  assert.equal(state.customWidth, "1200");
  assert.equal(state.customHeight, "1200");
  assert.equal(state.customSizeUnit, "px");
});

it("Task 6: a pt page says pt — the canonical box is a unit, not a pixel count", () => {
  // `pt` mints no `output` at all (`outputForSource`), so this is the `source`
  // arm, and a page with no metadata whatsoever is the box arm below it.
  const authored = withAuthoredPageSize(612, 792, "pt").pages[AD_PAGE_ID];
  assert.equal(authored.size.output, undefined);
  assert.deepEqual(pageDisplaySize(authored), { height: 792, unit: "pt", width: 612 });
  const bare = clone(SCENE);
  bare.pages[AD_PAGE_ID].size = {
    ...bare.pages[AD_PAGE_ID].size,
    output: undefined,
    source: undefined,
  };
  assert.deepEqual(pageDisplaySize(bare.pages[AD_PAGE_ID]), {
    height: 1200,
    unit: "pt",
    width: 1200,
  });
  assert.equal(hydrateSceneCanvasState(bare, AD_PAGE_ID).customSizeUnit, "pt");
});

it("Task 6: the px preset labels are matched on PIXELS only — a 1200x1200 mm page is Custom", () => {
  // The three ratified labels spell px sizes ("...1200x1200"), so a page whose
  // 1200x1200 are millimetres may not claim one: the select would then name a
  // size the page does not have, and picking it would resize the document.
  const millimetres = withAuthoredPageSize(1200, 1200, "mm");
  const state = hydrateSceneCanvasState(millimetres, AD_PAGE_ID);
  assert.equal(state.sizePreset, CUSTOM_SIZE_PRESET);
  assert.equal(state.customSizeUnit, "mm");
  // ...and the px page it mirrors still matches, unchanged.
  assert.equal(
    hydrateSceneCanvasState(SCENE, AD_PAGE_ID).sizePreset,
    "Linkedin square (1:1) - 1200x1200",
  );
});

it("Task 6: the Custom W/H inputs render the hydrated unit as inert text", () => {
  // Presentation-minimal (the binding presentation-truth rule): the unit rides
  // the `InspectorInput` `suffix` the Rotation (°) and Opacity (%) rows already
  // use — no unit selector, no new control, no new styling. The dummy fixture
  // path passes no `hydrated`, so it renders exactly what it always did.
  const width = AD_INSPECTOR_SOURCE.indexOf('ariaLabel="Custom width"');
  const height = AD_INSPECTOR_SOURCE.indexOf('ariaLabel="Custom height"');
  assert.notEqual(width, -1, "the canvas Custom-size rows moved");
  assert.notEqual(height, -1, "the canvas Custom-size rows moved");
  for (const start of [width, height]) {
    const row = AD_INSPECTOR_SOURCE.slice(start, AD_INSPECTOR_SOURCE.indexOf("/>", start));
    assert.ok(
      row.includes("suffix={hydrated?.customSizeUnit}"),
      "the W/H inputs must show the page's authored unit beside the number",
    );
  }
});

it("§1.1: the preset vocabulary is ONE list — the dummy's options are hydrate's labels plus Custom", () => {
  // The three labels live in the dummy (`SIZE_PRESETS` in `image-inspector.tsx`)
  // and their sizes live in the table above, which AD4.0's WRITE also reads. A
  // relabel on one side alone breaks hydration's match AND makes the write
  // silently return null, with nothing saying so — so the two lists are
  // cross-checked against the dummy's actual source text, the same technique
  // `scene-engine-banners.test.ts` uses to pin upstream banner copy.
  const literal = /const SIZE_PRESETS = \[([\s\S]*?)\] as const;/.exec(
    AD_INSPECTOR_SOURCE,
  );
  assert.ok(literal, "image-inspector.tsx no longer declares a SIZE_PRESETS literal");
  const options = [...literal[1].matchAll(/"([^"]*)"/g)].map((match) => match[1]);
  assert.deepEqual(options, [
    ...SIZE_PRESETS.map((preset) => preset.label),
    CUSTOM_SIZE_PRESET,
  ]);
});

it("§1.1: the canvas Background is the ROOT FRAME's fill, not the page background", () => {
  assert.deepEqual(SCENE.pages[AD_PAGE_ID].background, []);
  const state = hydrateSceneCanvasState(SCENE, AD_PAGE_ID);
  assert.equal(state.backgroundColor, "#0E0B2E");
  assert.equal(state.backgroundFill?.type, "solid");
});

it("§1.1: with no root frame the Background falls back to the none state", () => {
  const rootless = clone(SCENE);
  rootless.pages[AD_PAGE_ID].children = [];
  const state = hydrateSceneCanvasState(rootless, AD_PAGE_ID);
  assert.equal(state.backgroundColor, "none");
  // The honest empty state, whole: the fill control's own solid default, and
  // no token claim. Its writes are no-ops (the AD4.0 null contract).
  assert.deepEqual(state.backgroundFill, {
    angle: 0,
    stops: [
      { color: "#000000", position: 0 },
      { color: "#000000", position: 100 },
    ],
    type: "solid",
  });
  assert.equal(state.tokenBackgroundColor, undefined);
});

it("§1.1: a LINEAR gradient root frame hydrates its angle and its stops as percents", () => {
  // The harvested 3-stop gradient from `rect_accent_bar` (angle 90, engine
  // positions 0 / 0.5 / 1), moved onto the root frame — one field, a real
  // paint. The harvest has no gradient-filled FRAME of its own.
  assert.deepEqual(
    hydrateSceneCanvasState(withRootFills([...adRect().fills]), AD_PAGE_ID)
      .backgroundFill,
    {
      angle: 90,
      stops: [
        { color: "#533AFD", position: 0 },
        { color: "#8B5CF6", position: 50 },
        { color: "#EA2261", position: 100 },
      ],
      type: "linear-gradient",
    },
  );
});

it("§1.1: a RADIAL gradient root frame hydrates angle 0 — the engine stores none", () => {
  // `Paint::RadialGradient { stops }` has no angle field, so the control's
  // (always-present) angle reads 0. The same harvested stops, with the one
  // field the two paint kinds differ by edited.
  const scene = withRootFills([...adRect().fills]);
  const paint = scene.nodes[AD_ROOT_FRAME_ID].fills[0].paint;
  assert.equal(paint.kind, "linear_gradient");
  scene.nodes[AD_ROOT_FRAME_ID].fills[0].paint = {
    kind: "radial_gradient",
    stops: paint.kind === "linear_gradient" ? paint.stops : [],
  };
  assert.deepEqual(hydrateSceneCanvasState(scene, AD_PAGE_ID).backgroundFill, {
    angle: 0,
    stops: [
      { color: "#533AFD", position: 0 },
      { color: "#8B5CF6", position: 50 },
      { color: "#EA2261", position: 100 },
    ],
    type: "radial-gradient",
  });
});

it("§1.1: a TOKEN-filled root frame hydrates its token name, and states it in the swatch", () => {
  // The harvested `$text.inverse` token paint on the root frame. Ruling A15.1:
  // the swatch states the token NAME — the fact the document carries — exactly
  // as §1.2's stroke row already does for a token stroke. Leaving it unstated
  // showed the shared `DEFAULT_STATE` seed, a colour of the dummy's.
  const state = hydrateSceneCanvasState(
    withRootFills([...adTokenText().fills]),
    AD_PAGE_ID,
  );
  assert.equal(state.tokenBackgroundColor, "$text.inverse");
  assert.equal(state.backgroundColor, "$text.inverse");
});

it("A15.1: a GRADIENT-filled root frame states its FIRST STOP in the swatch, never a fixture", () => {
  // Browser-proven defect: with a radial gradient on the frame, picking
  // "Solid" left the select saying "Solid", the swatch saying a colour from
  // two edits earlier, and the artboard rendering the gradient — three answers
  // at once. The first stop is a colour the document really has, and it is the
  // exact inverse of `solidFill`, which already seeds a gradient's stops from
  // the solid colour.
  const gradient = withRootFills([...adRect().fills]);
  assert.equal(
    hydrateSceneCanvasState(gradient, AD_PAGE_ID).backgroundColor,
    "#533AFD",
  );
  // And identically through the NODE hydrator, which is what the same panel
  // uses when the artboard itself is the selection — the two ways of opening
  // the canvas schema may not disagree.
  assert.equal(
    hydrateSceneInspectorState(gradient.nodes[AD_ROOT_FRAME_ID], gradient)
      .backgroundColor,
    "#533AFD",
  );
});

it("A15.1: a fill-less root frame still states the honest none, through both hydrators", () => {
  const bare = withRootFills([]);
  assert.equal(hydrateSceneCanvasState(bare, AD_PAGE_ID).backgroundColor, "none");
  assert.equal(
    hydrateSceneInspectorState(bare.nodes[AD_ROOT_FRAME_ID], bare).backgroundColor,
    "none",
  );
});

// ── §1.1 row 2 / Ruling A15.2: what one Background fill change commits ──────

/** The control's state for a gradient, as `BackgroundFillControl` holds it. */
const GRADIENT: InspectorBackgroundFill = {
  angle: 90,
  stops: [
    { color: "#533AFD", position: 0 },
    { color: "#8B5CF6", position: 50 },
    { color: "#EA2261", position: 100 },
  ],
  type: "linear-gradient",
};
const SOLID: InspectorBackgroundFill = {
  angle: 0,
  stops: [
    { color: "#0E0B2E", position: 0 },
    { color: "#0E0B2E", position: 100 },
  ],
  type: "solid",
};

it("A15.2: SOLID → gradient carries the colour the user just set, not the mount-time seed", () => {
  // Browser-proven defect 1: setting the background to #2E7D32 (the document
  // really became green) then picking "Linear gradient" wrote
  // `stops:[#0e0b2e,#0e0b2e]` — the colour from BEFORE the green edit — and
  // the artboard visibly reverted. The swatch's current value is what is on
  // screen, so it is what the gradient starts from.
  assert.deepEqual(
    backgroundFillCommits(SOLID, { ...SOLID, type: "linear-gradient" }, "#2E7D32"),
    [
      {
        property: "backgroundFill",
        value: {
          angle: 0,
          stops: [
            { color: "#2E7D32", position: 0 },
            { color: "#2E7D32", position: 100 },
          ],
          type: "linear-gradient",
        },
      },
    ],
  );
});

it("A15.2: gradient → SOLID commits the outgoing paint's first stop, so one click is a real solid", () => {
  // Browser-proven defect 2: it wrote nothing at all. The colour committed is
  // one the document HAS (the first stop), never the swatch's stale value.
  assert.deepEqual(
    backgroundFillCommits(GRADIENT, { ...GRADIENT, type: "solid" }, "#2E7D32"),
    [
      { property: "backgroundFill", value: { ...GRADIENT, type: "solid" } },
      { property: "backgroundColor", value: "#533AFD" },
    ],
  );
});

it("A15.2: linear ↔ radial re-seeds nothing — both stop lists are already on screen", () => {
  assert.deepEqual(
    backgroundFillCommits(GRADIENT, { ...GRADIENT, type: "radial-gradient" }, "#2E7D32"),
    [{ property: "backgroundFill", value: { ...GRADIENT, type: "radial-gradient" } }],
  );
});

it("A15.2: a stop or angle edit is ONE commit, verbatim — it is not a mode switch", () => {
  const edited = {
    ...GRADIENT,
    angle: 45,
    stops: [...GRADIENT.stops.slice(0, 1), { color: "#FF6B00", position: 50 }, ...GRADIENT.stops.slice(2)],
  };
  assert.deepEqual(backgroundFillCommits(GRADIENT, edited, "#2E7D32"), [
    { property: "backgroundFill", value: edited },
  ]);
});

it("R3b: a stopless gradient → SOLID is REFUSED — there is no colour on screen to become", () => {
  // Unreachable from the control (2–6 stops) but storable, so the rule is
  // total: with no stop to read, the only other colour on screen is the
  // swatch's own — and `paintState` states `none` for a stopless gradient, so
  // `none` is the ONLY value this fallback can be handed.
  //
  // Step 2 committed it anyway; `normalizeHex` then refused the write while
  // the SELECT had already flipped to "Solid", leaving the panel claiming a
  // solid over an artboard still rendering the gradient. Committing nothing
  // keeps the two agreeing: no write, and no mode switch either.
  const stopless = { ...GRADIENT, stops: [] };
  assert.equal(
    hydrateSceneCanvasState(withRootFills([stoplessGradientFill()]), AD_PAGE_ID)
      .backgroundColor,
    COLOR_NONE,
  );
  assert.deepEqual(
    backgroundFillCommits(stopless, { ...stopless, type: "solid" }, COLOR_NONE),
    [],
  );
});

/** The harvested gradient paint with its stops emptied — the stored shape the
 * test above hydrates from, derived rather than hand-authored. */
function stoplessGradientFill() {
  const [fill] = adRect().fills;
  const paint = fill.paint;
  assert.equal(paint.kind, "linear_gradient");
  return {
    ...fill,
    paint: { ...paint, stops: [] } as typeof paint,
  };
}

/** The harvested scene with the ROOT FRAME's fills replaced — the one field
 * §1.1's Background row reads.
 *
 * The fills are DEEP-copied: callers hand it paints lifted off other harvested
 * nodes (`adRect().fills`), and a shallow copy would alias the frozen fixture's
 * own objects — a derived scene that then edits one paint would rewrite
 * `HARVESTED_AD_PAGE` for every later test in the file. */
function withRootFills(fills: Scene["nodes"][string]["fills"]): Scene {
  const scene = clone(SCENE);
  scene.nodes[AD_ROOT_FRAME_ID].fills = JSON.parse(
    JSON.stringify(fills),
  ) as Scene["nodes"][string]["fills"];
  return scene;
}

// ── AD4.0 step 2: the canvas schema's TWO entry states hydrate alike ────────

it("§1.1: a selected ROOT FRAME hydrates the PAGE's rows too — the Size select may not show a fixture", () => {
  // `sceneSelectionFor` routes the root frame to the canvas schema, so this
  // panel shows §1.1's size rows while being hydrated from a NODE, which has
  // no answer for them: the select fell back to the dummy's default preset on
  // any page that was not 1200x1200. Same rule the review applied twice
  // already — a field may not display a number the document does not have.
  const story = withPageSize(1080, 1920);
  const state = hydrateSceneSelectionState(
    story,
    AD_PAGE_ID,
    story.nodes[AD_ROOT_FRAME_ID],
  );
  assert.equal(state?.sizePreset, "Story (9:16) - 1080x1920");
  assert.equal(state?.customWidth, "1080");
  assert.equal(state?.customHeight, "1920");
  // The NODE still wins every field they share — its own title and lock.
  assert.equal(state?.title, "Ad artboard");
  assert.equal(state?.locked, false);
  // …and the two entry states agree on the Background.
  const empty = hydrateSceneSelectionState(story, AD_PAGE_ID, null);
  assert.equal(state?.backgroundColor, empty?.backgroundColor);
  assert.deepEqual(state?.backgroundFill, empty?.backgroundFill);
});

it("§1.1: any OTHER selected node hydrates as a node, with no page rows bolted on", () => {
  const state = hydrateSceneSelectionState(SCENE, AD_PAGE_ID, adTokenText());
  assert.equal(state?.sizePreset, undefined);
  assert.equal(state?.customWidth, undefined);
  assert.equal(state?.title, "Headline");
});

// ── R3b (AD4.0 step 3): a token swatch resolves where a hex is required ─────
//
// Step 2's review found the stuck state these close. A TOKEN-filled root frame
// truthfully shows its token name as the swatch value, and `paintState` is
// right to — but the gradient re-seed treats that value as a COLOUR, so
// switching to a gradient produced stops of `$text.inverse`, which the write
// adapter correctly refuses. The panel flipped to gradient mode showing
// `$TEXT.INVERSE` stop rows over an artboard that was still token-filled, with
// no way back short of a remount. With the palette in hand the token resolves
// to the colour it really paints; without one, the switch is refused.

/** The document's real brand vocabulary (`__fixtures__/brand-kit-colors`). */
const AD_PALETTE = buildScenePalette(adBrandKit());

/** What the panel is showing for the seeded ad's own token paint — read from
 * the hydrator rather than restated, so this is the value the user sees. */
function tokenSwatch(): string {
  const state = hydrateSceneCanvasState(
    withRootFills([...adTokenText().fills]),
    AD_PAGE_ID,
  );
  assert.equal(state.backgroundColor, "$text.inverse");
  return state.backgroundColor;
}

it("R3b: a TOKEN-filled frame → gradient seeds the stops with the colour the token paints", () => {
  assert.deepEqual(
    backgroundFillCommits(
      SOLID,
      { ...SOLID, type: "linear-gradient" },
      tokenSwatch(),
      AD_PALETTE,
    ),
    [
      {
        property: "backgroundFill",
        value: {
          angle: 0,
          // `$text.inverse` is #FFFFFF in this kit. Stop positions and count
          // ride through untouched, exactly as for a hex swatch.
          stops: [
            { color: "#FFFFFF", position: 0 },
            { color: "#FFFFFF", position: 100 },
          ],
          type: "linear-gradient",
        },
      },
    ],
  );
});

it("R3b: a token the palette cannot resolve REFUSES the switch rather than seeding a name", () => {
  // No palette at all (no kit attached, or a kit fetch that failed) and an
  // unknown token are the same fact: nothing on screen states a colour this
  // control can write, so the mode switch does not happen.
  assert.deepEqual(
    backgroundFillCommits(SOLID, { ...SOLID, type: "linear-gradient" }, tokenSwatch()),
    [],
  );
  assert.deepEqual(
    backgroundFillCommits(
      SOLID,
      { ...SOLID, type: "linear-gradient" },
      "$text.nope",
      AD_PALETTE,
    ),
    [],
  );
});

it("R3b: a gradient of TOKEN stops → solid commits the colour its first stop paints", () => {
  // The mirror case: `colorText` states a token stop as its name, so the
  // outgoing first stop is not a hex either. Same resolution, same refusal.
  const tokenStops: InspectorBackgroundFill = {
    ...GRADIENT,
    stops: [
      { color: "$text.inverse", position: 0 },
      { color: "$surface.brand", position: 100 },
    ],
  };
  assert.deepEqual(
    backgroundFillCommits(
      tokenStops,
      { ...tokenStops, type: "solid" },
      "$text.inverse",
      AD_PALETTE,
    ),
    [
      { property: "backgroundFill", value: { ...tokenStops, type: "solid" } },
      { property: "backgroundColor", value: "#FFFFFF" },
    ],
  );
  assert.deepEqual(
    backgroundFillCommits(tokenStops, { ...tokenStops, type: "solid" }, "$text.inverse"),
    [],
  );
});

it("R3b: a HEX swatch is unchanged by the palette — same commits, same casing", () => {
  // The regression guard for every non-token document: resolution only ever
  // fires on a value that names a token.
  assert.deepEqual(
    backgroundFillCommits(SOLID, { ...SOLID, type: "linear-gradient" }, "#2E7D32", AD_PALETTE),
    backgroundFillCommits(SOLID, { ...SOLID, type: "linear-gradient" }, "#2E7D32"),
  );
  assert.deepEqual(
    backgroundFillCommits(GRADIENT, { ...GRADIENT, type: "solid" }, "#2E7D32", AD_PALETTE),
    backgroundFillCommits(GRADIENT, { ...GRADIENT, type: "solid" }, "#2E7D32"),
  );
});

// ── RULING A9 (review) — the Stroke row's two fields move together ──────────
//
// A9 makes a colour or a width MINT a stroke on a node that has none, so the
// field the user did not touch must stop stating the old "no stroke" fact. A
// successful write does not remount the inspector, so nothing else re-reads
// them — the same sibling-re-seed rule step 1 settled for the Custom W/H boxes.

/** The stroke COLOUR one node hydrates, asserted rather than defaulted: every
 * `SceneInspectorState` field is optional, and a `?? ""` here would quietly
 * pass the day the stroke mapping stopped stating one. */
function statedStrokeColor(node: Node, scene: Scene = SCENE): string {
  const state = hydrateSceneInspectorState(node, scene);
  const color = state.strokeColor;
  assert.ok(color !== undefined, `${node.id} hydrates no strokeColor`);
  return color;
}

it("A9: after a colour lands on a STROKELESS row, the width box reads the minted 1", () => {
  // The row a strokeless node hydrates — read from the hydrator, not restated.
  const state = hydrateSceneInspectorState(adPlainText(), SCENE);
  assert.equal(state.strokeColor, COLOR_NONE);
  assert.equal(state.strokeWidth, "0");
  assert.equal(mintedStrokeWidth(statedStrokeColor(adPlainText())), "1");
});

it("A9: a row that already HAS a stroke re-seeds nothing — the write keeps its width", () => {
  assert.equal(hydrateSceneInspectorState(adAutoLayout(), SCENE).strokeWidth, "2");
  assert.equal(mintedStrokeWidth(statedStrokeColor(adAutoLayout())), null);
  // A stored ZERO-width stroke is the case that must not be mistaken for a
  // strokeless one: the write CLEARS it, so the row re-seeds nothing. Its
  // hydrated colour is the paint's, never `none`, which is what tells them
  // apart. Derived by DEEP-copying the harvest and editing one field.
  const zeroWidth = clone(SCENE);
  zeroWidth.nodes.auto_row_copy.strokes[0].width = 0;
  const zeroNode = zeroWidth.nodes.auto_row_copy;
  assert.equal(
    hydrateSceneInspectorState(zeroNode, zeroWidth).strokeWidth,
    "0",
  );
  const zeroColor = statedStrokeColor(zeroNode, zeroWidth);
  assert.notEqual(zeroColor, COLOR_NONE);
  assert.equal(mintedStrokeWidth(zeroColor), null);
});

it("A9 mirror: after a width lands on a COLOURLESS row, the swatch reads the minted teal", () => {
  const bare = statedStrokeColor(adPlainText());
  assert.equal(mintedStrokeColor(bare, "4"), "#256c70");
  // A width that clears or is refused mints nothing, exactly as the write does
  // nothing with it.
  for (const width of ["0", "", "  ", "abc", "-2"]) {
    assert.equal(mintedStrokeColor(bare, width), null, width);
  }
  // A row that already has a colour keeps it — a width edit is not a colour
  // edit, and the write carries the stored paint through verbatim.
  assert.equal(mintedStrokeColor(statedStrokeColor(adAutoLayout()), "4"), null);
});

// ══ AD4.A step 2 / §1.3 row 1 — the Fill section's preview ══════════════════

it("§1.3 Replace image: the preview states THIS node's asset, not the dummy's stock png", () => {
  const state = hydrateSceneInspectorState(adImage(), HARVESTED_AD_PAGE);
  // The canvas's own resolver — the public, content-addressed passthrough the
  // artboard paints from, so the two can never show different bytes.
  assert.equal(
    state.imagePreviewSrc,
    "/api/clue/design-public/asset-store/2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a",
  );
});

it("§1.3 Replace image: an unresolvable asset states NOTHING, so the dummy default stands", () => {
  // UNCOVERED by the harvest (its one asset resolves): the scene is cloned and
  // exactly one field — the asset's digest — is dropped.
  const scene = clone(HARVESTED_AD_PAGE);
  const asset = scene.assets?.asset_ing_2b0928ca4f3a3c70;
  assert.ok(asset, "fixture asset missing");
  asset.media = { ...asset.media, digest: null };
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  assert.ok(
    !("imagePreviewSrc" in hydrateSceneInspectorState(node, scene)),
    "an unresolvable asset hydrates no preview at all",
  );
});

it("§1.3 Replace image: a NON-image node hydrates no preview — the row is image-only", () => {
  assert.ok(
    !("imagePreviewSrc" in hydrateSceneInspectorState(adTokenText(), HARVESTED_AD_PAGE)),
    "a text node has no image preview",
  );
  assert.ok(
    !("imagePreviewSrc" in hydrateSceneInspectorState(adRect(), HARVESTED_AD_PAGE)),
    "a rectangle has no image preview",
  );
});

it("FIX 2: the Fill preview reads the LIVE document value", () => {
  // A `.tsx` cannot be imported under this runner, so the binding is pinned
  // against the dummy's own source text — the technique this file already uses
  // for the SIZE_PRESETS vocabulary.
  //
  // FIX 2's original form read the `hydrated` PROP over the state
  // (`hydrated?.imagePreviewSrc ?? state.imagePreviewSrc`), because the
  // controller seeded `state.imagePreviewSrc` ONCE at mount: a placement
  // landing after a mid-upload reload had already remounted the panel would
  // otherwise leave the thumbnail on the previous asset while the artboard
  // showed the new one.
  //
  // AD4.R Task 7 collapsed that special case (plan
  // `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`,
  // §"Rulings superseded"). Its premise — mount-frozen controller state — died
  // with AD4.R Task 4's live hydration: `state.imagePreviewSrc` now IS the
  // hydrated value, re-derived every render, so there is no longer a
  // mount-frozen copy for the prop to have to out-rank. The FACT this test
  // guards is unchanged and now structural rather than patched: the preview
  // states the document's asset, not a stale one.
  const upload = /<InspectorImageUpload[\s\S]*?\/>/.exec(AD_INSPECTOR_SOURCE);
  assert.ok(upload, "image-inspector.tsx no longer renders InspectorImageUpload");
  assert.match(upload[0], /src=\{state\.imagePreviewSrc\}/);
  assert.match(upload[0], /onFileSelect=\{onReplaceImage\}/);
});

// ══ AD4.A step 3 / §1.3 row 2 — Alt text ════════════════════════════════════

it("§1.3 Alt text: an image states the description its PLACEMENT carries", () => {
  assert.equal(
    hydrateSceneInspectorState(adImage(), HARVESTED_AD_PAGE).altText,
    "Brand gradient backdrop",
  );
});

it("§1.3 Alt text: with no stored alt_text the node's OWN `alt` is stated", () => {
  // Upstream's `placement.alt_text ?? node.kind.alt ?? ""` — two genuinely
  // different fields, read in that order. UNCOVERED by the harvest, whose
  // image carries both.
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement?.alt_text;
  assert.equal(
    hydrateSceneInspectorState(node, scene).altText,
    "Brand gradient backdrop",
  );
});

it("§1.3 Alt text: an image with NO description at all states the honest empty string", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement;
  if (node.kind.kind === "image") node.kind.alt = null;
  assert.equal(hydrateSceneInspectorState(node, scene).altText, "");
});

it("§1.3 Alt text: a NON-image node hydrates no description — the row is image-only", () => {
  assert.ok(
    !("altText" in hydrateSceneInspectorState(adTokenText(), HARVESTED_AD_PAGE)),
    "a text node has no image alt text",
  );
  assert.ok(
    !("altText" in hydrateSceneInspectorState(adRect(), HARVESTED_AD_PAGE)),
    "a rectangle has no image alt text",
  );
});
