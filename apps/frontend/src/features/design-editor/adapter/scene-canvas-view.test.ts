import assert from "node:assert/strict";
import test from "node:test";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "./__fixtures__/scene-nodes";
import {
  SELECTION_HANDLE_CORNER_RADIUS,
  SELECTION_HANDLE_FILL,
  SELECTION_HANDLE_SIZE,
  SELECTION_HANDLE_STROKE,
  SELECTION_HANDLE_STROKE_WIDTH,
  SELECTION_OUTLINE_COLOR,
  SELECTION_OUTLINE_WIDTH,
  chosenZoomScale,
  sceneArtboardModel,
  sceneAssetPassthroughUrl,
  sceneSelectionOutline,
  sceneViewportModel,
  selectionHandleRects,
  selectionOutlineForBox,
  snapZoomPercent,
  textMeasurementSignature,
} from "./scene-canvas-view";
import { sceneHitPoint } from "./scene-selection";
import type { Scene } from "../engine/scene/contracts";
import {
  screenToWorkspace,
  workspaceToScreen,
} from "../engine/scene/workspaceViewport";

const AD_ASSET_ID = "asset_ing_2b0928ca4f3a3c70";
const AD_ASSET_DIGEST =
  "2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a";

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

test("an image asset resolves through the headerless public passthrough, by digest", () => {
  assert.equal(
    sceneAssetPassthroughUrl(HARVESTED_AD_PAGE.assets, AD_ASSET_ID),
    `/api/clue/design-public/asset-store/${AD_ASSET_DIGEST}`,
  );
});

test("the passthrough URL keeps the BFF path prefix (the new URL trap)", () => {
  const url = sceneAssetPassthroughUrl(HARVESTED_AD_PAGE.assets, AD_ASSET_ID);
  assert.ok(url?.startsWith("/api/clue/design-public/"), url ?? "null");
});

test("an asset the scene does not carry is unfetchable, not a guessed URL", () => {
  assert.equal(
    sceneAssetPassthroughUrl(HARVESTED_AD_PAGE.assets, "asset_missing"),
    null,
  );
  assert.equal(sceneAssetPassthroughUrl(undefined, AD_ASSET_ID), null);
});

test("an unusable digest resolves to null rather than a 404 fetch", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const media = scene.assets[AD_ASSET_ID]?.media;
  assert.ok(media);
  media.digest = { algorithm: "sha256", value: "not-a-sha" };
  assert.equal(sceneAssetPassthroughUrl(scene.assets, AD_ASSET_ID), null);
});

test("fit zoom reports the nearest 5% menu step", () => {
  // 512 available px over a 1200pt page — the real fit for this ad inside the
  // dummy's artboard card.
  assert.equal(snapZoomPercent(512 / 1200), "45%");
  assert.equal(snapZoomPercent(0.25), "25%");
  assert.equal(snapZoomPercent(0.426), "45%");
  assert.equal(snapZoomPercent(0.424), "40%");
});

test("fit zoom clamps into the menu's own range", () => {
  assert.equal(snapZoomPercent(0.02), "10%");
  assert.equal(snapZoomPercent(4), "150%");
});

test("a starved fit reports the minimum step instead of NaN%", () => {
  assert.equal(snapZoomPercent(Number.NaN), "10%");
  assert.equal(snapZoomPercent(0), "10%");
  assert.equal(snapZoomPercent(-1), "10%");
});

// AD2.8: the fit-vs-chosen model. The card in these cases is the dummy's
// square artboard (512px) and the page is the seeded ad (1200×1200pt), so the
// exact fit is 512/1200 = 0.4266… — a scale the 5% menu cannot name.
const AD_RECT = { x: 0, y: 0, width: 1200, height: 1200 };
const CARD = { width: 512, height: 512 };

test("fit-on-open applies the EXACT contain-fit, not the step it displays", () => {
  const model = sceneViewportModel({ rect: AD_RECT, stage: CARD, zoom: null });
  // The label rounds; the transform must not (ruling 17: the ad fills the
  // designed card edge-to-edge — 45% would leave a gap inside it).
  assert.equal(model.fitLabel, "45%");
  assert.equal(model.applied.zoom, 512 / 1200);
  assert.deepEqual(model.applied, model.fit);
  assert.notEqual(model.applied.zoom, 0.45);
});

test("an exact fit fills the card edge to edge", () => {
  const { applied } = sceneViewportModel({
    rect: AD_RECT,
    stage: CARD,
    zoom: null,
  });
  const topLeft = workspaceToScreen({ x: 0, y: 0 }, applied);
  const bottomRight = workspaceToScreen({ x: 1200, y: 1200 }, applied);
  assert.deepEqual(topLeft, { x: 0, y: 0 });
  assert.deepEqual(bottomRight, { x: 512, y: 512 });
});

test("a chosen step is applied at exactly that percentage", () => {
  assert.equal(
    sceneViewportModel({ rect: AD_RECT, stage: CARD, zoom: "50%" }).applied
      .zoom,
    0.5,
  );
  assert.equal(
    sceneViewportModel({ rect: AD_RECT, stage: CARD, zoom: "150%" }).applied
      .zoom,
    1.5,
  );
});

test("a chosen step keeps the artboard centered in the card", () => {
  for (const zoom of ["10%", "50%", "150%"]) {
    const { applied } = sceneViewportModel({
      rect: AD_RECT,
      stage: CARD,
      zoom,
    });
    const center = workspaceToScreen({ x: 600, y: 600 }, applied);
    assert.deepEqual(center, { x: 256, y: 256 }, zoom);
  }
});

test("above the fit the page overflows the card — clipped, never re-panned", () => {
  const { applied } = sceneViewportModel({
    rect: AD_RECT,
    stage: CARD,
    zoom: "150%",
  });
  // 1200 × 1.5 = 1800px of page inside a 512px card: it hangs off both edges
  // symmetrically. The card clips it (there is no designed pan affordance).
  assert.equal(applied.pan.x, 256 - 900);
  assert.equal(workspaceToScreen({ x: 0, y: 0 }, applied).x, -644);
  assert.equal(workspaceToScreen({ x: 1200, y: 0 }, applied).x, 1156);
});

test("choosing a step does not disturb the reported fit", () => {
  const fit = sceneViewportModel({ rect: AD_RECT, stage: CARD, zoom: null });
  const chosen = sceneViewportModel({
    rect: AD_RECT,
    stage: CARD,
    zoom: "150%",
  });
  assert.equal(chosen.fitLabel, fit.fitLabel);
  assert.deepEqual(chosen.fit, fit.fit);
});

test("a chosen zoom rides the engine's own [0.1, 2.0] viewport clamp", () => {
  assert.equal(chosenZoomScale("50%"), 0.5);
  // Every menu option is inside the clamp; a hand-passed value is not trusted.
  assert.equal(chosenZoomScale("400%"), 2);
  assert.equal(chosenZoomScale("1%"), 0.1);
});

test("no choice — and no parsable one — means fit", () => {
  assert.equal(chosenZoomScale(null), null);
  assert.equal(chosenZoomScale(undefined), null);
  assert.equal(chosenZoomScale(""), null);
  assert.equal(chosenZoomScale("Fit"), null);
  assert.equal(chosenZoomScale("0%"), null);
  assert.equal(chosenZoomScale("-25%"), null);
});

test("a fit below the menu's floor is labelled honestly at the floor", () => {
  // A huge page in a small card: the ENGINE clamps the fit at 10% too, so the
  // label and the transform agree — the page simply overflows the card.
  const model = sceneViewportModel({
    rect: { x: 0, y: 0, width: 20000, height: 20000 },
    stage: CARD,
    zoom: null,
  });
  assert.equal(model.fit.zoom, 0.1);
  assert.equal(model.fitLabel, "10%");
});

test("a starved card falls back to the default viewport, chosen zoom or not", () => {
  const starved = { width: 0, height: 0 };
  for (const zoom of [null, "150%"]) {
    const { applied } = sceneViewportModel({
      rect: AD_RECT,
      stage: starved,
      zoom,
    });
    assert.deepEqual(applied, { zoom: 1, pan: { x: 0, y: 0 } }, `${zoom}`);
  }
});

test("the text signature covers only text nodes' measurement inputs", () => {
  const signature = textMeasurementSignature(HARVESTED_AD_PAGE, 0);
  assert.ok(signature.includes("Every inbound fax"), signature.slice(0, 200));
  assert.ok(signature.includes("3.4x faster triage"), signature.slice(0, 400));
  // Two text nodes in the fixture — one line each, plus the generation line.
  assert.equal(signature.split("\n").length, 3);
});

test("moving a non-text node does not re-measure text", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.rect_accent_bar.transform.x += 40;
  assert.equal(
    textMeasurementSignature(scene, 0),
    textMeasurementSignature(HARVESTED_AD_PAGE, 0),
  );
});

test("editing text content re-measures", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const text = scene.nodes.text_proof_stat.kind;
  assert.equal(text.kind, "text");
  if (text.kind === "text") {
    text.content = "4.1x faster triage";
  }
  assert.notEqual(
    textMeasurementSignature(scene, 0),
    textMeasurementSignature(HARVESTED_AD_PAGE, 0),
  );
});

test("a new kit generation re-measures (kit type roles are measurement inputs)", () => {
  assert.notEqual(
    textMeasurementSignature(HARVESTED_AD_PAGE, 1),
    textMeasurementSignature(HARVESTED_AD_PAGE, 0),
  );
});

test("the artboard model is the page box at the workspace origin", () => {
  const model = sceneArtboardModel(HARVESTED_AD_PAGE, AD_PAGE_ID);
  assert.ok(model);
  assert.deepEqual(model.rect, { x: 0, y: 0, width: 1200, height: 1200 });
  assert.equal(model.page.id, AD_PAGE_ID);
  assert.equal(model.page.background, "#ffffff");
});

test("the artboard model carries the page's whole in-flow tree", () => {
  const model = sceneArtboardModel(HARVESTED_AD_PAGE, AD_PAGE_ID);
  assert.ok(model);
  assert.deepEqual(
    model.nodes.map((node) => node.descriptor.id),
    ["frame_ad_root"],
  );
  const frame = model.nodes[0];
  assert.deepEqual(
    frame.children.map((node) => node.descriptor.id),
    ["auto_row_copy", "rect_accent_bar", "line_divider", "image_hero"],
  );
  assert.deepEqual(
    frame.children[0].children.map((node) => node.descriptor.id),
    ["text_headline", "group_proof"],
  );
  assert.deepEqual(
    frame.children[0].children[1].children.map((node) => node.descriptor.id),
    ["ellipse_proof_dot", "text_proof_stat"],
  );
});

test("a pinned node is hoisted out of its parent and painted last", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.line_divider.position_mode = "absolute";
  const model = sceneArtboardModel(scene, AD_PAGE_ID);
  assert.ok(model);
  assert.deepEqual(
    model.nodes.map((node) => node.descriptor.id),
    ["frame_ad_root", "line_divider"],
  );
  assert.deepEqual(
    model.nodes[0].children.map((node) => node.descriptor.id),
    ["auto_row_copy", "rect_accent_bar", "image_hero"],
  );
});

test("an unknown page renders nothing rather than throwing", () => {
  assert.equal(sceneArtboardModel(HARVESTED_AD_PAGE, "page_gone"), null);
  assert.equal(sceneArtboardModel(HARVESTED_AD_PAGE, null), null);
});

/* -------------------------------------------------------------------------
 * Gate G-A — the selection outline's geometry (founder ruling: Variant B)
 * ---------------------------------------------------------------------- */

/**
 * The harvest carries `computed: null` on every node (that IS the at-rest
 * truth), and the engine's relayout is what fills it in — so a test of the
 * outline has to supply the geometry the relayout would.
 *
 * These are not invented boxes. `image_hero` is a fixed-size, absolutely
 * positioned child of `frame_ad_root`, and the frame sits at the page origin,
 * so its laid-out bounds in absolute page space are exactly its authored
 * transform and size: (72, 452) 1056x676. The clone edits that one field on
 * that one node — AD2.4/AD2.5's technique, so the node stays real.
 */
const HERO_BOUNDS = { x: 72, y: 452, width: 1056, height: 676 };

function sceneWithLaidOutHero(rotation = 0): Scene {
  const next = clone(HARVESTED_AD_PAGE);
  next.nodes.image_hero.computed = {
    layout_bounds: { ...HERO_BOUNDS },
    render_bounds: { ...HERO_BOUNDS },
  };
  next.nodes.image_hero.transform.rotation = rotation;
  return next;
}

function heroArtboard(scene: Scene) {
  const artboard = sceneArtboardModel(scene, AD_PAGE_ID);
  assert.ok(artboard);
  return artboard;
}

test("the outline is the selected node's box in stage px at fit-on-open", () => {
  const scene = sceneWithLaidOutHero();
  const artboard = heroArtboard(scene);
  // A 600x600 card fits the 1200x1200 page at exactly 0.5 with no pan, so the
  // expected numbers are readable by hand rather than a restatement of the
  // implementation.
  const model = sceneViewportModel({
    rect: artboard.rect,
    stage: { width: 600, height: 600 },
    zoom: null,
  });
  assert.equal(model.applied.zoom, 0.5);
  assert.deepEqual(model.applied.pan, { x: 0, y: 0 });
  assert.deepEqual(
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "image_hero",
      viewport: model.applied,
    }),
    { nodeId: "image_hero", x: 36, y: 226, width: 528, height: 338, rotation: 0 },
  );
});

test("the outline tracks zoom: doubling the zoom doubles the box", () => {
  const scene = sceneWithLaidOutHero();
  const artboard = heroArtboard(scene);
  const outlineAt = (zoom: string) =>
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "image_hero",
      viewport: sceneViewportModel({
        rect: artboard.rect,
        stage: { width: 600, height: 600 },
        zoom,
      }).applied,
    });
  const quarter = outlineAt("25%");
  const half = outlineAt("50%");
  assert.ok(quarter && half);
  assert.equal(half.width, quarter.width * 2);
  assert.equal(half.height, quarter.height * 2);
  // Re-centering keeps the artboard centred in the card at every step, so the
  // box moves as well as grows — a fixed box would be the bug this catches.
  assert.notEqual(half.x, quarter.x);
});

test("the outline is the exact inverse of AD2.5's hit-test chain", () => {
  const scene = sceneWithLaidOutHero();
  const artboard = heroArtboard(scene);
  const viewport = sceneViewportModel({
    rect: artboard.rect,
    stage: { width: 933, height: 741 },
    zoom: "35%",
  }).applied;
  const outline = sceneSelectionOutline({
    artboard,
    pageId: AD_PAGE_ID,
    scene,
    selectedNodeId: "image_hero",
    viewport,
  });
  assert.ok(outline);
  // Press exactly on the outline's top-left corner: the point the engine would
  // be asked about is the node's own box origin, in scene units.
  const hit = sceneHitPoint(
    screenToWorkspace({ x: outline.x, y: outline.y }, viewport),
    artboard,
  );
  assert.ok(hit);
  assert.ok(Math.abs(hit.x - HERO_BOUNDS.x) < 1e-9, `${hit.x}`);
  assert.ok(Math.abs(hit.y - HERO_BOUNDS.y) < 1e-9, `${hit.y}`);
});

test("a non-identity page unit scales the box (the unitScale trap)", () => {
  const scene = sceneWithLaidOutHero();
  // One field: the page's unit. `in` is unitScale 96, so a box in scene units
  // is 96x larger in descriptor px — the multiply this asserts is the mirror of
  // `sceneHitPoint`'s divide.
  scene.pages[AD_PAGE_ID].size.unit = "in";
  const artboard = heroArtboard(scene);
  assert.equal(artboard.page.unitScale, 96);
  const outline = selectionOutlineForBox({
    artboard,
    box: { x: 1, y: 2, width: 3, height: 4 },
    nodeId: "image_hero",
    rotation: 0,
    viewport: { zoom: 1, pan: { x: 0, y: 0 } },
  });
  assert.deepEqual(outline, {
    nodeId: "image_hero",
    x: 96,
    y: 192,
    width: 288,
    height: 384,
    rotation: 0,
  });
});

test("a rotated node carries its rotation through to the overlay", () => {
  const scene = sceneWithLaidOutHero(30);
  const artboard = heroArtboard(scene);
  const outline = sceneSelectionOutline({
    artboard,
    pageId: AD_PAGE_ID,
    scene,
    selectedNodeId: "image_hero",
    viewport: { zoom: 1, pan: { x: 0, y: 0 } },
  });
  // The box is the UNROTATED laid-out box; the overlay rotates it about its
  // own origin, which is the pivot the draw loop uses.
  assert.deepEqual(outline, {
    nodeId: "image_hero",
    x: 72,
    y: 452,
    width: 1056,
    height: 676,
    rotation: 30,
  });
});

test("a starved box outlines nothing rather than drawing NaN", () => {
  const artboard = heroArtboard(sceneWithLaidOutHero());
  assert.equal(
    selectionOutlineForBox({
      artboard,
      box: { x: Number.NaN, y: 0, width: 10, height: 10 },
      nodeId: "image_hero",
      rotation: 0,
      viewport: { zoom: 1, pan: { x: 0, y: 0 } },
    }),
    null,
  );
});

test("nothing selected, or a node the scene lost, outlines nothing", () => {
  const scene = sceneWithLaidOutHero();
  const artboard = heroArtboard(scene);
  const viewport = { zoom: 1, pan: { x: 0, y: 0 } };
  assert.equal(
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: null,
      viewport,
    }),
    null,
  );
  assert.equal(
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "node_gone",
      viewport,
    }),
    null,
  );
  assert.equal(
    sceneSelectionOutline({
      artboard: null,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "image_hero",
      viewport,
    }),
    null,
  );
});

test("a node with no laid-out geometry outlines nothing, never a guess", () => {
  // The harvest as served: `computed` is null on every node. An outline drawn
  // from `transform` would sit where an auto-laid-out child is NOT.
  const artboard = heroArtboard(HARVESTED_AD_PAGE);
  assert.equal(
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "image_hero",
      viewport: { zoom: 1, pan: { x: 0, y: 0 } },
    }),
    null,
  );
});

test("G-A handles (Lane C): four 8x8 squares centred on the box corners", () => {
  const outline = {
    nodeId: "image_hero",
    x: 100,
    y: 200,
    width: 40,
    height: 20,
    rotation: 0,
  };
  assert.deepEqual(selectionHandleRects(outline), [
    { x: 96, y: 196, size: 8 },
    { x: 136, y: 196, size: 8 },
    { x: 96, y: 216, size: 8 },
    { x: 136, y: 216, size: 8 },
  ]);
});

test("G-A: the approved Variant B stroke is the one the overlay uses", () => {
  assert.equal(SELECTION_OUTLINE_COLOR, "#4F46E5");
  assert.equal(SELECTION_OUTLINE_WIDTH, 1.5);
  assert.equal(SELECTION_HANDLE_SIZE, 8);
  assert.equal(SELECTION_HANDLE_CORNER_RADIUS, 1);
  assert.equal(SELECTION_HANDLE_FILL, "#FFFFFF");
  assert.equal(SELECTION_HANDLE_STROKE, "#4F46E5");
  assert.equal(SELECTION_HANDLE_STROKE_WIDTH, 1.5);
});
