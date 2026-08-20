import assert from "node:assert/strict";
import test from "node:test";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "./__fixtures__/scene-nodes";
import {
  sceneArtboardModel,
  sceneAssetPassthroughUrl,
  snapZoomPercent,
  textMeasurementSignature,
} from "./scene-canvas-view";
import type { Scene } from "../engine/scene/contracts";

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
