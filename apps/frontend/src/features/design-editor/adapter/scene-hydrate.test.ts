import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import type { Scene } from "../engine/scene/contracts";
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
import {
  CUSTOM_SIZE_PRESET,
  SIZE_PRESETS,
  backgroundFillCommits,
  customSizeForPreset,
  hydrateSceneCanvasState,
  hydrateSceneInspectorState,
  hydrateSceneSelectionState,
  rootFrameId,
  sceneSelectionFor,
} from "./scene-hydrate";

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
  // Leaving `textColor` unstated left the shared `DEFAULT_STATE` seed
  // `#00F59B` on screen — the swatch claiming the headline is mint green while
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

it("§1.2: the font family reads TextNode.font_family", () => {
  assert.equal(hydrateSceneInspectorState(adPlainText(), SCENE).fontFamily, "Inter");
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

it("§1.1: a committed preset re-seeds the Custom W/H boxes with THAT preset's size", () => {
  // AD4.0 review round 2, proven in the browser: a successful write does not
  // remount the inspector, so when the SELECT resizes the page its two sibling
  // boxes kept their mount-time seed — a page taken from Custom 1100x1600 to
  // the LinkedIn square still offered 1100/1600. Same rule as the test above:
  // a field may not display a number the document does not have.
  assert.deepEqual(customSizeForPreset("Linkedin square (1:1) - 1200x1200"), {
    height: "1200",
    width: "1200",
  });
  assert.deepEqual(customSizeForPreset("Instagram portrait (4:5) - 1080x1350"), {
    height: "1350",
    width: "1080",
  });
  assert.deepEqual(customSizeForPreset("Story (9:16) - 1080x1920"), {
    height: "1920",
    width: "1080",
  });
});

it("§1.1: a label that resizes nothing re-seeds nothing", () => {
  // The same null contract the WRITE applies to the same input, off the same
  // table: "Custom" names no size, and a label the select does not offer never
  // reached the document, so neither box may be overwritten.
  for (const label of [
    CUSTOM_SIZE_PRESET,
    "Linkedin square (1:1) - 1024x1024",
    "linkedin_ad",
    "",
  ]) {
    assert.equal(customSizeForPreset(label), null, label);
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
  // showed the shared `DEFAULT_STATE` seed `#00F59B`, a colour of the dummy's.
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

it("A15.2: a stopless gradient → SOLID falls back to the swatch, inventing nothing", () => {
  // Unreachable from the control (2–6 stops) but storable, so the rule is
  // total: with no stop to read, the only other colour on screen is the
  // swatch's own.
  const stopless = { ...GRADIENT, stops: [] };
  assert.deepEqual(
    backgroundFillCommits(stopless, { ...stopless, type: "solid" }, "#2E7D32"),
    [
      { property: "backgroundFill", value: { ...stopless, type: "solid" } },
      { property: "backgroundColor", value: "#2E7D32" },
    ],
  );
});

/** The harvested scene with the ROOT FRAME's fills replaced — the one field
 * §1.1's Background row reads. */
function withRootFills(fills: Scene["nodes"][string]["fills"]): Scene {
  const scene = clone(SCENE);
  scene.nodes[AD_ROOT_FRAME_ID].fills = fills;
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
