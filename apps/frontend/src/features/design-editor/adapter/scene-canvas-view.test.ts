import assert from "node:assert/strict";
import test from "node:test";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "./__fixtures__/scene-nodes";
import {
  ARTBOARD_BORDER_WIDTH_PX,
  ARTBOARD_FIT_MARGIN,
  ARTBOARD_SHADOW_BLUR_PX,
  ARTBOARD_SHADOW_OFFSET_PX,
  HOVER_OUTLINE_OPACITY,
  HOVER_OUTLINE_WIDTH,
  SELECTION_HANDLE_CORNER_RADIUS,
  SELECTION_HANDLE_FILL,
  SELECTION_HANDLE_SIZE,
  SELECTION_HANDLE_STROKE,
  SELECTION_HANDLE_STROKE_WIDTH,
  SELECTION_OUTLINE_COLOR,
  SELECTION_OUTLINE_WIDTH,
  WHEEL_ZOOM_STEP,
  WORKSPACE_CANVAS_FALLBACK,
  artboardChromeGeometry,
  chosenZoomScale,
  formatZoomPercent,
  sceneArtboardModel,
  sceneAssetPassthroughUrl,
  sceneDragPanViewport,
  sceneSelectionOutline,
  sceneTextPaintedBox,
  sceneViewportModel,
  sceneWheelViewport,
  selectionHandleRects,
  selectionOutlineForBox,
  snapZoomPercent,
  textMeasurementSignature,
  type SceneArtboardModel,
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

// AD2.8, as amended by AD2.10: the fit-vs-chosen model. The STAGE in these
// cases stands in for the whole neutral output area (512px square, to keep the
// arithmetic readable) and the page is the seeded ad (1200×1200pt). The fit is
// now the stage inset by ARTBOARD_FIT_MARGIN — (512-64)/1200 = 0.3733… — a
// scale the 5% menu cannot name.
const AD_RECT = { x: 0, y: 0, width: 1200, height: 1200 };
const CARD = { width: 512, height: 512 };

test("fit-on-open applies the EXACT contain-fit, not the step it displays", () => {
  const model = sceneViewportModel({ rect: AD_RECT, stage: CARD, zoom: null });
  // The label rounds to a step the menu can check; the transform must not.
  assert.equal(model.fitLabel, "35%");
  assert.equal(model.applied.zoom, (512 - ARTBOARD_FIT_MARGIN) / 1200);
  assert.deepEqual(model.applied, model.fit);
  assert.notEqual(model.applied.zoom, 0.35);
});

test("AD2.10: the fit leaves breathing room — the artboard never touches the stage edge", () => {
  // A stage exactly one margin larger than the page fits it at 1:1, which makes
  // the margin readable by hand: 32px of workspace on every side (ruling 17,
  // which pinned the page to the card's edges, is retired here).
  const { applied } = sceneViewportModel({
    rect: AD_RECT,
    stage: { width: 1264, height: 1264 },
    zoom: null,
  });
  assert.equal(applied.zoom, 1);
  assert.deepEqual(workspaceToScreen({ x: 0, y: 0 }, applied), {
    x: ARTBOARD_FIT_MARGIN / 2,
    y: ARTBOARD_FIT_MARGIN / 2,
  });
  assert.deepEqual(workspaceToScreen({ x: 1200, y: 1200 }, applied), {
    x: 1264 - ARTBOARD_FIT_MARGIN / 2,
    y: 1264 - ARTBOARD_FIT_MARGIN / 2,
  });
});

test("AD2.10: a non-square page is fit by its LONGEST side, not letterboxed into a square", () => {
  // A 1080×1920 Story on a landscape stage: the height binds, and the page is
  // centred with the workspace showing left and right of it. The retired
  // `aspect-ratio: 1` card could not express this at all.
  const story = { x: 0, y: 0, width: 1080, height: 1920 };
  const { applied } = sceneViewportModel({
    rect: story,
    stage: { width: 1200, height: 704 },
    zoom: null,
  });
  assert.equal(applied.zoom, (704 - ARTBOARD_FIT_MARGIN) / 1920);
  const topLeft = workspaceToScreen({ x: 0, y: 0 }, applied);
  const bottomRight = workspaceToScreen({ x: 1080, y: 1920 }, applied);
  assert.equal(topLeft.y, ARTBOARD_FIT_MARGIN / 2);
  assert.equal(bottomRight.y, 704 - ARTBOARD_FIT_MARGIN / 2);
  // Horizontally centred, and well inside the stage.
  assert.ok(topLeft.x > ARTBOARD_FIT_MARGIN / 2, `${topLeft.x}`);
  assert.equal(topLeft.x + bottomRight.x, 1200);
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

test("a chosen step re-centres the artboard on the stage", () => {
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

test("above the fit the artboard overflows the stage — and panning reaches it", () => {
  const { applied } = sceneViewportModel({
    rect: AD_RECT,
    stage: CARD,
    zoom: "150%",
  });
  // 1200 × 1.5 = 1800px of page inside a 512px viewport: it hangs off both
  // edges symmetrically.
  assert.equal(applied.pan.x, 256 - 900);
  assert.equal(workspaceToScreen({ x: 0, y: 0 }, applied).x, -644);
  assert.equal(workspaceToScreen({ x: 1200, y: 0 }, applied).x, 1156);
  // AD2.10: the part hanging off the left is no longer unreachable — a pan
  // brings the page's own origin back onto the stage.
  const panned = sceneDragPanViewport({
    bounds: AD_RECT,
    origin: { point: { x: 0, y: 0 }, pan: applied.pan },
    point: { x: 700, y: 0 },
    stage: CARD,
    viewport: applied,
  });
  assert.equal(workspaceToScreen({ x: 0, y: 0 }, panned).x, 56);
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

/* -------------------------------------------------------------------------
 * AD2.10 — the infinite canvas: the artboard's own chrome, pan and wheel-zoom
 * ---------------------------------------------------------------------- */

test("the workspace paints the design subsystem's own --bg-canvas value", () => {
  // Light and clearly separable from a white page — the platform shell is
  // light, so the source editor's dark workspace is not portable, but its
  // TOKEN value is (subsystems/clue-design/apps/editor/src/app/tokens.css).
  assert.equal(WORKSPACE_CANVAS_FALLBACK, "#f5f5f5");
});

test("artboard chrome is screen-constant: every px constant is divided by the zoom", () => {
  for (const zoom of [0.25, 1, 2]) {
    const chrome = artboardChromeGeometry(AD_RECT, zoom);
    // Multiplying back by the zoom (which the viewport transform does) returns
    // the screen constants — the shadow and hairline look identical at 25% and
    // at 200%.
    assert.equal(chrome.shadowSigma * zoom, ARTBOARD_SHADOW_BLUR_PX, `${zoom}`);
    assert.equal(
      chrome.borderWidth * zoom,
      ARTBOARD_BORDER_WIDTH_PX,
      `${zoom}`,
    );
    assert.equal(
      (chrome.shadow.y - AD_RECT.y) * zoom,
      ARTBOARD_SHADOW_OFFSET_PX,
      `${zoom}`,
    );
  }
});

test("the shadow sits under the artboard, nudged down — never resized", () => {
  const chrome = artboardChromeGeometry(AD_RECT, 1);
  assert.equal(chrome.shadow.x, AD_RECT.x);
  assert.equal(chrome.shadow.width, AD_RECT.width);
  assert.equal(chrome.shadow.height, AD_RECT.height);
  assert.ok(chrome.shadow.y > AD_RECT.y);
});

test("a starved zoom still yields drawable chrome rather than Infinity", () => {
  for (const zoom of [0, Number.NaN, -1]) {
    const chrome = artboardChromeGeometry(AD_RECT, zoom);
    assert.ok(Number.isFinite(chrome.shadowSigma), `${zoom}`);
    assert.ok(Number.isFinite(chrome.borderWidth), `${zoom}`);
    assert.ok(Number.isFinite(chrome.shadow.y), `${zoom}`);
  }
});

test("a plain wheel pans by the inverse of the delta (trackpad two-finger scroll)", () => {
  const viewport = { zoom: 1, pan: { x: 0, y: 0 } };
  const next = sceneWheelViewport({
    bounds: AD_RECT,
    delta: { x: 30, y: 50 },
    point: { x: 100, y: 100 },
    stage: CARD,
    viewport,
    zoomGesture: false,
  });
  assert.equal(next.zoom, 1);
  assert.deepEqual(next.pan, { x: -30, y: -50 });
});

test("a pan cannot lose the artboard: the clamp keeps a slice on screen", () => {
  const viewport = { zoom: 1, pan: { x: 0, y: 0 } };
  const next = sceneWheelViewport({
    bounds: AD_RECT,
    delta: { x: 100000, y: 0 },
    point: { x: 0, y: 0 },
    stage: CARD,
    viewport,
    zoomGesture: false,
  });
  // Some of the 1200px-wide artboard is still inside the 512px stage.
  const left = workspaceToScreen({ x: 0, y: 0 }, next).x;
  const right = workspaceToScreen({ x: 1200, y: 0 }, next).x;
  assert.ok(right > 0 && left < CARD.width, `${left}..${right}`);
});

test("⌘/Ctrl + wheel zooms AT THE POINTER — the pixel under the cursor stays put", () => {
  const viewport = { zoom: 1, pan: { x: 0, y: 0 } };
  const anchor = { x: 300, y: 200 };
  const before = screenToWorkspace(anchor, viewport);
  const zoomedIn = sceneWheelViewport({
    bounds: AD_RECT,
    delta: { x: 0, y: -1 },
    point: anchor,
    stage: CARD,
    viewport,
    zoomGesture: true,
  });
  assert.equal(zoomedIn.zoom, 1 + WHEEL_ZOOM_STEP);
  const after = screenToWorkspace(anchor, zoomedIn);
  assert.ok(Math.abs(after.x - before.x) < 1e-9, `${after.x}`);
  assert.ok(Math.abs(after.y - before.y) < 1e-9, `${after.y}`);
  // And down again, the other way.
  assert.equal(
    sceneWheelViewport({
      bounds: AD_RECT,
      delta: { x: 0, y: 1 },
      point: anchor,
      stage: CARD,
      viewport,
      zoomGesture: true,
    }).zoom,
    1 - WHEEL_ZOOM_STEP,
  );
});

test("wheel-zoom rides the engine's own [0.1, 2.0] clamp", () => {
  const zoomTo = (start: number, direction: number) =>
    sceneWheelViewport({
      bounds: AD_RECT,
      delta: { x: 0, y: direction },
      point: { x: 0, y: 0 },
      stage: CARD,
      viewport: { zoom: start, pan: { x: 0, y: 0 } },
      zoomGesture: true,
    }).zoom;
  assert.equal(zoomTo(1.99, -1), 2);
  assert.equal(zoomTo(0.11, 1), 0.1);
});

test("a zoom gesture with no vertical delta leaves the viewport untouched", () => {
  const viewport = { zoom: 0.5, pan: { x: 3, y: 4 } };
  assert.equal(
    sceneWheelViewport({
      bounds: AD_RECT,
      delta: { x: 20, y: 0 },
      point: { x: 0, y: 0 },
      stage: CARD,
      viewport,
      zoomGesture: true,
    }),
    viewport,
  );
});

test("a drag pan recomputes from the press, so a dropped move cannot drift", () => {
  const viewport = { zoom: 1, pan: { x: 10, y: 10 } };
  const origin = { point: { x: 100, y: 100 }, pan: viewport.pan };
  const halfway = sceneDragPanViewport({
    bounds: AD_RECT,
    origin,
    point: { x: 140, y: 130 },
    stage: CARD,
    viewport,
  });
  const straightThrough = sceneDragPanViewport({
    bounds: AD_RECT,
    origin,
    point: { x: 180, y: 160 },
    stage: CARD,
    viewport: halfway,
  });
  // Skipping the intermediate move lands in exactly the same place.
  assert.deepEqual(
    straightThrough.pan,
    sceneDragPanViewport({
      bounds: AD_RECT,
      origin,
      point: { x: 180, y: 160 },
      stage: CARD,
      viewport,
    }).pan,
  );
  assert.deepEqual(halfway.pan, { x: 50, y: 40 });
});

test("a gesture zoom is labelled honestly, including above the menu's ceiling", () => {
  assert.equal(formatZoomPercent(0.3733), "37%");
  assert.equal(formatZoomPercent(1), "100%");
  // The menu stops at 150%; the engine does not, and a label that said "150%"
  // at 172% would be a lie about where the viewport is.
  assert.equal(formatZoomPercent(1.72), "172%");
  assert.equal(formatZoomPercent(2.4), "200%");
  assert.equal(formatZoomPercent(Number.NaN), "10%");
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

test("swapping type tokens between equal-sized text nodes re-measures", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const first = scene.nodes.text_headline;
  const second = scene.nodes.text_proof_stat;
  assert.equal(first.kind.kind, "text");
  if (first.kind.kind !== "text") throw new Error("expected text fixture");
  first.kind = { ...first.kind, style_token: "type.headline" };
  second.kind = { ...first.kind, style_token: "type.stat" };
  for (const node of [first, second]) {
    node.size = {
      width: { kind: "fixed", value: 300 },
      height: { kind: "fixed", value: 80 },
    };
    node.computed = {
      layout_bounds: { x: 0, y: 0, width: 300, height: 80 },
      render_bounds: { x: 0, y: 0, width: 300, height: 80 },
    };
  }
  const before = textMeasurementSignature(scene, 0);

  // The same styles now belong to different measurement-cache node IDs.
  [first.kind, second.kind] = [second.kind, first.kind];

  assert.notEqual(textMeasurementSignature(scene, 0), before);
});

test("Plan 4: a text node's solved size is part of the measurement signature", () => {
  // The line pass is keyed on the box the engine solved; a resized box must
  // re-measure or its lines go stale (the key misses → heuristic lines).
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_proof_stat.computed = {
    layout_bounds: { x: 0, y: 0, width: 300, height: 120 },
    render_bounds: { x: 0, y: 0, width: 300, height: 120 },
  };
  const before = textMeasurementSignature(scene, 0);
  scene.nodes.text_proof_stat.computed.layout_bounds.width = 280;
  assert.notEqual(textMeasurementSignature(scene, 0), before);
  // A non-text node's size never re-measures.
  const rect = clone(HARVESTED_AD_PAGE);
  rect.nodes.rect_accent_bar.computed = {
    layout_bounds: { x: 0, y: 0, width: 9, height: 9 },
    render_bounds: { x: 0, y: 0, width: 9, height: 9 },
  };
  assert.equal(textMeasurementSignature(rect, 0), textMeasurementSignature(HARVESTED_AD_PAGE, 0));
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

/**
 * Rung B (rich-text plan, 2026-08-24): a text node with an open caret session
 * is drawn with no text payload, so the DOM overlay is the only copy of the
 * string on screen. Same render-time descriptor override AD4.C's gesture
 * preview uses — the draw loop needs no session awareness at all.
 */
function textNodeIn(model: SceneArtboardModel, nodeId: string) {
  const copyRow = model.nodes[0].children[0];
  const found = [
    ...copyRow.children,
    ...copyRow.children.flatMap((child) => child.children),
  ].find((node) => node.descriptor.id === nodeId);
  assert.ok(found);
  return found;
}

test("an open text session suppresses that node's painted text", () => {
  const model = sceneArtboardModel(
    HARVESTED_AD_PAGE,
    AD_PAGE_ID,
    null,
    "text_headline",
  );
  assert.ok(model);
  // The node still draws — its fills, strokes and box are untouched — only the
  // glyphs go, because the overlay is painting them.
  assert.equal(textNodeIn(model, "text_headline").descriptor.text, undefined);
  assert.equal(textNodeIn(model, "text_proof_stat").descriptor.text?.content, "3.4x faster triage");
});

test("no session (or a stale node id) suppresses nothing", () => {
  const model = sceneArtboardModel(HARVESTED_AD_PAGE, AD_PAGE_ID, null, "text_gone");
  assert.ok(model);
  assert.equal(
    textNodeIn(model, "text_headline").descriptor.text?.content,
    "Every inbound fax, routed to the right EHR queue.",
  );
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
  // A 664x664 stage fits the 1200x1200 page at exactly 0.5 once the margin is
  // taken out, and the 32px of breathing room is the pan — so the expected
  // numbers are readable by hand rather than a restatement of the code.
  const model = sceneViewportModel({
    rect: artboard.rect,
    stage: { width: 664, height: 664 },
    zoom: null,
  });
  assert.equal(model.applied.zoom, 0.5);
  assert.deepEqual(model.applied.pan, { x: 32, y: 32 });
  assert.deepEqual(
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "image_hero",
      viewport: model.applied,
    }),
    {
      nodeId: "image_hero",
      x: 68,
      y: 258,
      width: 528,
      height: 338,
      rotation: 0,
      frame: null,
    },
  );
});

test("AD2.10: the outline follows the PAN — a panned stage does not strand it", () => {
  // The overlay is a screen-space sibling of a stage-sized canvas now, so a pan
  // has to move the box by exactly the pan delta and change nothing else. This
  // is the case ruling 17's fixed card could never produce.
  const scene = sceneWithLaidOutHero();
  const artboard = heroArtboard(scene);
  const stage = { width: 664, height: 664 };
  const fit = sceneViewportModel({ rect: artboard.rect, stage, zoom: null })
    .applied;
  const at = (viewport: typeof fit) =>
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "image_hero",
      viewport,
    });
  const before = at(fit);
  const panned = sceneDragPanViewport({
    bounds: artboard.rect,
    origin: { point: { x: 0, y: 0 }, pan: fit.pan },
    point: { x: -120, y: 45 },
    stage,
    viewport: fit,
  });
  assert.deepEqual(panned.pan, { x: -88, y: 77 });
  const after = at(panned);
  assert.ok(before && after);
  assert.equal(after.x, before.x - 120);
  assert.equal(after.y, before.y + 45);
  assert.equal(after.width, before.width);
  assert.equal(after.height, before.height);
});

test("AD2.10: the outline survives a pointer-anchored wheel-zoom, both ways", () => {
  const scene = sceneWithLaidOutHero();
  const artboard = heroArtboard(scene);
  const stage = { width: 664, height: 664 };
  const fit = sceneViewportModel({ rect: artboard.rect, stage, zoom: null })
    .applied;
  const anchor = { x: 500, y: 400 };
  const zoomed = sceneWheelViewport({
    bounds: artboard.rect,
    delta: { x: 0, y: -1 },
    point: anchor,
    stage,
    viewport: fit,
    zoomGesture: true,
  });
  const outline = sceneSelectionOutline({
    artboard,
    pageId: AD_PAGE_ID,
    scene,
    selectedNodeId: "image_hero",
    viewport: zoomed,
  });
  assert.ok(outline);
  // The box is exactly where the hit-test chain would answer from — the same
  // inverse-of-the-input-chain guarantee, now at a gesture-made viewport.
  const hit = sceneHitPoint(
    screenToWorkspace({ x: outline.x, y: outline.y }, zoomed),
    artboard,
  );
  assert.ok(hit);
  assert.ok(Math.abs(hit.x - HERO_BOUNDS.x) < 1e-9, `${hit.x}`);
  assert.ok(Math.abs(hit.y - HERO_BOUNDS.y) < 1e-9, `${hit.y}`);
  assert.equal(outline.width, HERO_BOUNDS.width * zoomed.zoom);
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
    frame: null,
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
    frame: null,
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

test("Plan 3 R4: the hover outline is the selection colour, thinner and translucent", () => {
  assert.equal(HOVER_OUTLINE_WIDTH, 1);
  assert.equal(HOVER_OUTLINE_OPACITY, 0.55);
  assert.ok(HOVER_OUTLINE_WIDTH < SELECTION_OUTLINE_WIDTH);
});

// ══ Editor Quality Plan 4 (item F, ruling R5): the outline is the painted text ══

test("Plan 4: a text node's outline is the union of its painted lines; the layout box is the dashed frame", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  node.computed = {
    layout_bounds: { x: 100, y: 100, width: 300, height: 120 },
    render_bounds: { x: 100, y: 100, width: 300, height: 120 },
    text_lines: [
      { x: 100, y: 100, width: 180, height: 40 },
      { x: 100, y: 140, width: 120, height: 40 },
    ],
  };
  assert.deepEqual(sceneTextPaintedBox(node), {
    x: 100,
    y: 100,
    width: 180,
    height: 80,
  });
  const artboard = heroArtboard(scene);
  const viewport = sceneViewportModel({
    rect: artboard.rect,
    stage: { width: 664, height: 664 },
    zoom: null,
  }).applied;
  const outline = sceneSelectionOutline({
    artboard,
    pageId: AD_PAGE_ID,
    scene,
    selectedNodeId: node.id,
    viewport,
  });
  const painted = selectionOutlineForBox({
    artboard,
    box: { x: 100, y: 100, width: 180, height: 80 },
    nodeId: node.id,
    rotation: 0,
    viewport,
  })!;
  const frame = selectionOutlineForBox({
    artboard,
    box: { x: 100, y: 100, width: 300, height: 120 },
    nodeId: node.id,
    rotation: 0,
    viewport,
  })!;
  assert.deepEqual(outline, {
    ...painted,
    frame: {
      x: frame.x,
      y: frame.y,
      width: frame.width,
      height: frame.height,
    },
  });
});

test("Plan 4: a hug box (lines fill it within the rounding contract) draws no frame", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  node.computed = {
    layout_bounds: { x: 100, y: 100, width: 180, height: 80 },
    render_bounds: { x: 100, y: 100, width: 180, height: 80 },
    text_lines: [
      { x: 100, y: 100, width: 180, height: 40 },
      { x: 100, y: 140, width: 120, height: 40.4 },
    ],
  };
  const artboard = heroArtboard(scene);
  const viewport = sceneViewportModel({
    rect: artboard.rect,
    stage: { width: 664, height: 664 },
    zoom: null,
  }).applied;
  const outline = sceneSelectionOutline({
    artboard,
    pageId: AD_PAGE_ID,
    scene,
    selectedNodeId: node.id,
    viewport,
  });
  assert.ok(outline);
  assert.equal(outline.frame, null);
});

test("Plan 4: a text node without painted lines, and a gesture preview, outline the box with no frame", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  node.computed = {
    layout_bounds: { x: 100, y: 100, width: 300, height: 120 },
    render_bounds: { x: 100, y: 100, width: 300, height: 120 },
  };
  const artboard = heroArtboard(scene);
  const viewport = sceneViewportModel({
    rect: artboard.rect,
    stage: { width: 664, height: 664 },
    zoom: null,
  }).applied;
  const plain = sceneSelectionOutline({
    artboard,
    pageId: AD_PAGE_ID,
    scene,
    selectedNodeId: node.id,
    viewport,
  });
  assert.deepEqual(
    plain,
    selectionOutlineForBox({
      artboard,
      box: { x: 100, y: 100, width: 300, height: 120 },
      nodeId: node.id,
      rotation: 0,
      viewport,
    }),
  );
  assert.equal(plain?.frame, null);
  node.computed.text_lines = [{ x: 100, y: 100, width: 50, height: 40 }];
  const scale = artboard.page.unitScale;
  const previewed = sceneSelectionOutline({
    artboard,
    pageId: AD_PAGE_ID,
    scene,
    selectedNodeId: node.id,
    viewport,
    preview: {
      nodeId: node.id,
      box: {
        x: 100 * scale,
        y: 100 * scale,
        width: 300 * scale,
        height: 120 * scale,
      },
      rotation: 0,
    },
  });
  assert.equal(previewed?.frame, null);
  assert.equal(previewed?.width, plain?.width);
});

test("Plan 4: handles sit on whatever box they are asked for", () => {
  const rects = selectionHandleRects({ x: 10, y: 20, width: 100, height: 50 });
  assert.equal(rects.length, 4);
  assert.deepEqual(
    rects.map((r) => [r.x + r.size / 2, r.y + r.size / 2]),
    [
      [10, 20],
      [110, 20],
      [10, 70],
      [110, 70],
    ],
  );
});
