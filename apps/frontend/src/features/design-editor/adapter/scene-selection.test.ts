import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene } from "../engine/scene/contracts";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "./__fixtures__/scene-nodes";
import { sceneArtboardModel } from "./scene-canvas-view";
import { representableHit, sceneHitPoint } from "./scene-selection";

/**
 * AD2.5: the two pure decisions behind clicking a rendered ad — which node a
 * hit stack actually SELECTS (§5's representable-ancestor rule) and where the
 * pointer lands in the engine's own units.
 *
 * Every case runs against AD2.2's harvested bytes (the seeded
 * `doc_ad22linkedinsquare00000000001`), never a hand-written node. Where a case
 * needs a shape the harvest cannot have (a line nested INSIDE the group; a page
 * whose unit is not `pt`), it uses a clone of the harvest with exactly one
 * field edited — AD2.4's technique, so the nodes stay real.
 */

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/**
 * The harvest hangs `line_divider` off the root frame. The brief's headline
 * case is a line INSIDE the group, so this reparents that one real line node —
 * one field on the group, one on the frame, nothing else invented.
 */
function sceneWithLineInsideGroup(): Scene {
  const next = clone(HARVESTED_AD_PAGE);
  next.nodes.frame_ad_root.children =
    next.nodes.frame_ad_root.children.filter((id) => id !== "line_divider");
  next.nodes.group_proof.children = [
    ...next.nodes.group_proof.children,
    "line_divider",
  ];
  return next;
}

it("§5: a hit stack ending in the line inside the group resolves to the GROUP", () => {
  const scene = sceneWithLineInsideGroup();
  assert.equal(
    representableHit(
      ["frame_ad_root", "auto_row_copy", "group_proof", "line_divider"],
      scene,
      AD_PAGE_ID,
    ),
    "group_proof",
  );
});

it("§5: an empty hit stack (a click on nothing) resolves to null", () => {
  assert.equal(representableHit([], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
});

it("§5: a stack whose every member is unrepresentable resolves to null", () => {
  // The one real line node, hit with nothing representable under it.
  assert.equal(
    representableHit(["line_divider"], HARVESTED_AD_PAGE, AD_PAGE_ID),
    null,
  );
  // Two of them (the harvested line, cloned) — the walk does not stop at the
  // first unrepresentable member, it keeps descending and still finds nothing.
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.line_divider_2 = {
    ...scene.nodes.line_divider,
    id: "line_divider_2",
  };
  scene.nodes.frame_ad_root.children = [
    ...scene.nodes.frame_ad_root.children,
    "line_divider_2",
  ];
  assert.equal(
    representableHit(
      ["line_divider", "line_divider_2"],
      scene,
      AD_PAGE_ID,
    ),
    null,
  );
});

it("§1.4: a text hit resolves to the text node itself", () => {
  assert.equal(
    representableHit(
      ["frame_ad_root", "auto_row_copy", "text_headline"],
      HARVESTED_AD_PAGE,
      AD_PAGE_ID,
    ),
    "text_headline",
  );
});

it("§1.3: an image hit resolves to the image node itself", () => {
  assert.equal(
    representableHit(
      ["frame_ad_root", "image_hero"],
      HARVESTED_AD_PAGE,
      AD_PAGE_ID,
    ),
    "image_hero",
  );
});

it("§1.1: a hit on the root frame alone resolves to it (the canvas selection)", () => {
  assert.equal(
    representableHit(["frame_ad_root"], HARVESTED_AD_PAGE, AD_PAGE_ID),
    "frame_ad_root",
  );
});

it("§5: the walk is TOP-DOWN — the topmost representable member wins, not the outermost", () => {
  // The stack arrives bottom-to-top (the engine's `HitResult.stack` order), so
  // the last member is the topmost. Every member here is representable; only a
  // top-down walk answers the innermost one.
  assert.equal(
    representableHit(
      ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"],
      HARVESTED_AD_PAGE,
      AD_PAGE_ID,
    ),
    "text_proof_stat",
  );
});

it("§5: a stack member that is not in the scene is skipped, never a crash", () => {
  assert.equal(
    representableHit(
      ["frame_ad_root", "node_that_was_deleted"],
      HARVESTED_AD_PAGE,
      AD_PAGE_ID,
    ),
    "frame_ad_root",
  );
});

it("§1.1: with no resolvable page the root frame is still representable (as a frame, not the canvas)", () => {
  // `rootFrameId` returns null for an unknown page, which only changes WHICH
  // schema the frame routes to — it must never make the frame unselectable.
  assert.equal(
    representableHit(["frame_ad_root"], HARVESTED_AD_PAGE, "page_gone"),
    "frame_ad_root",
  );
});

it("the artboard-local point divides by the page's unitScale (descriptor px → scene units)", () => {
  const artboard = sceneArtboardModel(HARVESTED_AD_PAGE, AD_PAGE_ID);
  assert.ok(artboard);
  // The harvested page is `pt`, whose unitScale is 1 — identity, and the
  // artboard sits at the workspace origin, so the point passes straight
  // through. This is the live case, asserted so a regression in the origin
  // subtraction shows up here.
  assert.deepEqual(sceneHitPoint({ x: 600, y: 480 }, artboard), {
    x: 600,
    y: 480,
  });
});

it("the artboard-local point divides by a NON-identity unitScale", () => {
  // The harvest cannot prove the division (pt → 1), so this clone flips the
  // page unit to `in` (unitScale 96). The descriptor box becomes 96x larger and
  // a workspace point must divide back down into scene units.
  const scene = clone(HARVESTED_AD_PAGE);
  scene.pages[AD_PAGE_ID].size.unit = "in";
  scene.pages[AD_PAGE_ID].size.width = 10;
  scene.pages[AD_PAGE_ID].size.height = 10;
  const artboard = sceneArtboardModel(scene, AD_PAGE_ID);
  assert.ok(artboard);
  assert.equal(artboard.rect.width, 960);
  assert.deepEqual(sceneHitPoint({ x: 480, y: 96 }, artboard), { x: 5, y: 1 });
});

it("a workspace point outside the artboard has NO scene point (a click on empty space)", () => {
  const artboard = sceneArtboardModel(HARVESTED_AD_PAGE, AD_PAGE_ID);
  assert.ok(artboard);
  assert.equal(sceneHitPoint({ x: -1, y: 600 }, artboard), null);
  assert.equal(sceneHitPoint({ x: 600, y: -1 }, artboard), null);
  assert.equal(sceneHitPoint({ x: 1201, y: 600 }, artboard), null);
  assert.equal(sceneHitPoint({ x: 600, y: 1201 }, artboard), null);
  // The edges themselves are inside.
  assert.deepEqual(sceneHitPoint({ x: 0, y: 0 }, artboard), { x: 0, y: 0 });
  assert.deepEqual(sceneHitPoint({ x: 1200, y: 1200 }, artboard), {
    x: 1200,
    y: 1200,
  });
});

it("the artboard origin is subtracted before the unit conversion", () => {
  // A single artboard sits at the workspace origin today, so the subtraction is
  // invisible live. Feed a translated artboard and the order becomes provable:
  // (500-200)/1 = 300, never 500/1 - 200.
  const artboard = sceneArtboardModel(HARVESTED_AD_PAGE, AD_PAGE_ID);
  assert.ok(artboard);
  const moved = { ...artboard, rect: { ...artboard.rect, x: 200, y: 100 } };
  assert.deepEqual(sceneHitPoint({ x: 500, y: 400 }, moved), {
    x: 300,
    y: 300,
  });
});
