import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene, TextSpan } from "../engine/scene/contracts";
import { minimalScene } from "../engine/scene/__tests__/__fixtures__/minimalScene";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  SCENE_CLIPBOARD_KIND,
  SCENE_CLIPBOARD_MIME,
  extractReadableText,
  serializeSubtree,
} from "./scene-clipboard";

/**
 * Clipboard Task 1 — the DTO and the subtree serializer, pure functions over
 * the scene's flat node map.
 *
 * Two fixtures, used for what each actually has:
 *   HARVESTED_AD_PAGE — a real group (`group_proof` → ellipse + text), a real
 *   auto-layout (`auto_row_copy` → headline + group), and a real image node
 *   (`image_hero` → `asset_ing_2b0928ca4f3a3c70`), all with `computed: null`
 *   (harvested bytes, no solve ran);
 *   minimal_scene.json — one page-parented text node with a FIXED transform
 *   and size, the plan's named case for page-space bounds.
 */

function clone(scene: Scene): Scene {
  return structuredClone(scene);
}

it("serializes a group root as the full closure in document order", () => {
  const payload = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof");
  assert.ok(payload);
  assert.deepEqual(payload.roots, ["group_proof"]);
  // DFS preorder over `children` IS document order (flattenPageNodeIds' walk).
  assert.deepEqual(
    payload.nodes.map((node) => node.id),
    ["group_proof", "ellipse_proof_dot", "text_proof_stat"],
  );
  assert.equal(payload.kind, SCENE_CLIPBOARD_KIND);
  assert.equal(payload.version, 1);
  // Display/debug only, NEVER trusted — the serializer has no workspace to
  // name (Scene carries none), so it is born null; a caller may stamp it.
  assert.equal(payload.workspaceHint, null);
});

it("serializes a nested subtree preorder — containers before their children", () => {
  const payload = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "auto_row_copy");
  assert.ok(payload);
  assert.deepEqual(
    payload.nodes.map((node) => node.id),
    ["auto_row_copy", "text_headline", "group_proof", "ellipse_proof_dot", "text_proof_stat"],
  );
});

it("collects an image node's asset_id into assetIds", () => {
  const payload = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "image_hero");
  assert.ok(payload);
  assert.deepEqual(payload.assetIds, ["asset_ing_2b0928ca4f3a3c70"]);
});

it("contributes a shared asset_id exactly once", () => {
  // Two image nodes under one group, both painting the same asset.
  const scene = clone(HARVESTED_AD_PAGE);
  const second = structuredClone(scene.nodes["image_hero"]);
  second.id = "image_hero_2";
  scene.nodes["image_hero_2"] = second;
  scene.nodes["group_proof"].children.push("image_hero_2", "image_hero");
  const payload = serializeSubtree(scene, AD_PAGE_ID, "group_proof");
  assert.ok(payload);
  assert.deepEqual(payload.assetIds, ["asset_ing_2b0928ca4f3a3c70"]);
});

it("serializes text spans byte-identically and independently of the live scene", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const spans: TextSpan[] = [
    { start: 0, end: 4, font_weight: 700 },
    { start: 5, end: 11, fill: { kind: "solid", color: { kind: "hex", value: "#ff0000" } }, italic: true },
  ];
  const statKind = scene.nodes["text_proof_stat"].kind;
  assert.equal(statKind.kind, "text");
  statKind.spans = structuredClone(spans);

  const payload = serializeSubtree(scene, AD_PAGE_ID, "group_proof");
  assert.ok(payload);
  const copied = payload.nodes.find((node) => node.id === "text_proof_stat");
  assert.ok(copied);
  assert.equal(copied.kind.kind, "text");
  assert.equal(JSON.stringify(copied.kind.spans), JSON.stringify(spans));

  // The payload is a snapshot, not a window onto the live store: a later edit
  // to the scene must not reach into an already-captured clipboard payload.
  statKind.spans![0].font_weight = 100;
  scene.nodes["text_proof_stat"].name = "renamed after copy";
  assert.equal(copied.kind.spans![0].font_weight, 700);
  assert.equal(copied.name, "Proof stat");
});

it("joins text-node contents in document order for readableText", () => {
  const payload = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "auto_row_copy");
  assert.ok(payload);
  assert.equal(
    payload.readableText,
    "Every inbound fax, routed to the right EHR queue.\n3.4x faster triage",
  );
});

it("extractReadableText reads only text nodes, in the order given", () => {
  const nodes = [
    HARVESTED_AD_PAGE.nodes["image_hero"],
    HARVESTED_AD_PAGE.nodes["text_proof_stat"],
    HARVESTED_AD_PAGE.nodes["text_headline"],
  ];
  assert.equal(
    extractReadableText(nodes),
    "3.4x faster triage\nEvery inbound fax, routed to the right EHR queue.",
  );
});

it("returns null for a root id that resolves to no node", () => {
  assert.equal(serializeSubtree(minimalScene, "page_a4", "node_missing"), null);
});

it("returns null for a root that lives on a different page", () => {
  // Stricter than "unknown id": a real node named under the WRONG page would
  // serialize bounds against a page it is not on — refuse instead.
  assert.equal(serializeSubtree(minimalScene, "page_other", "node_contact_name"), null);
});

it("bounds equal the root's page-space box (fixed transform fallback)", () => {
  // minimal_scene: node_contact_name is page-parented with computed:null, so
  // its parent origin is (0,0) and the transform IS the page-space position.
  const payload = serializeSubtree(minimalScene, "page_a4", "node_contact_name");
  assert.ok(payload);
  assert.deepEqual(payload.bounds, { x: 24, y: 40, width: 160, height: 28 });
});

it("bounds prefer the engine's solved page-space geometry when present", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const hero = scene.nodes["image_hero"];
  hero.computed = {
    layout_bounds: { x: 72, y: 452, width: 936, height: 556 },
    render_bounds: { x: 72, y: 452, width: 936, height: 556 },
  };
  // Perturb the parent-relative transform to prove the solved box wins.
  hero.transform.x = 999;
  const payload = serializeSubtree(scene, AD_PAGE_ID, "image_hero");
  assert.ok(payload);
  assert.deepEqual(payload.bounds, { x: 72, y: 452, width: 936, height: 556 });
});

it("names the custom clipboard mime", () => {
  assert.equal(SCENE_CLIPBOARD_MIME, "application/vnd.clue.scene+json");
});
