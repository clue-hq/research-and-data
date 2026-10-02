import assert from "node:assert/strict";
import { it, mock } from "node:test";
import { JSDOM } from "jsdom";
import type { NodeId, Operation, Scene, TextSpan } from "../engine/scene/contracts";
import { minimalScene } from "../engine/scene/__tests__/__fixtures__/minimalScene";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import type { PastePlacement } from "./scene-clipboard-placement";
import type { ClipboardMaterialization } from "./scene-clipboard";
import {
  CLIPBOARD_ENVELOPE_MAX_BYTES,
  SCENE_CLIPBOARD_KIND,
  SCENE_CLIPBOARD_MIME,
  decodeClipboardHtml,
  encodeClipboardHtml,
  extractReadableText,
  materializeClipboardPayload,
  rasterToPngBlob,
  remintSubtree,
  serializeSubtree,
  validateClipboardPayload,
} from "./scene-clipboard";

// The codec's decode side reads the envelope through the browser's DOMParser.
// node:test has no DOM, so the suite installs jsdom's — the same inert,
// non-executing parser contract as the browser's (parsed documents run no
// scripts), which is exactly the property the security cases below pin.
const DOM = new JSDOM("");
(globalThis as { DOMParser?: unknown }).DOMParser = DOM.window.DOMParser;

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

// ── Task 2: envelope codec ─────────────────────────────────────────────────

function groupPayload() {
  const payload = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof");
  assert.ok(payload);
  return payload;
}

it("round-trips a payload through the html envelope identically", () => {
  const payload = groupPayload();
  const html = encodeClipboardHtml(payload);
  assert.ok(html);
  assert.deepEqual(decodeClipboardHtml(html), payload);
});

it("round-trips non-ascii text content byte-faithfully", () => {
  // The envelope is base64 over UTF-8; a latin1-only encode path (bare btoa)
  // would throw or mangle here.
  const scene = structuredClone(HARVESTED_AD_PAGE) as Scene;
  const kind = scene.nodes["text_proof_stat"].kind;
  assert.equal(kind.kind, "text");
  kind.content = "3,4× schnellere Sichtung — 🚑 „Praxis“";
  const payload = serializeSubtree(scene, AD_PAGE_ID, "group_proof");
  assert.ok(payload);
  const html = encodeClipboardHtml(payload);
  assert.ok(html);
  const decoded = decodeClipboardHtml(html);
  assert.ok(decoded);
  const statNode = decoded.nodes.find((node) => node.id === "text_proof_stat");
  assert.ok(statNode && statNode.kind.kind === "text");
  assert.equal(statNode.kind.content, "3,4× schnellere Sichtung — 🚑 „Praxis“");
});

it("decodes parse-only — script-bearing wrapper html executes nothing", () => {
  const payload = groupPayload();
  const envelope = encodeClipboardHtml(payload);
  assert.ok(envelope);
  const marker = "__scene_clipboard_pwned" as const;
  const hostile =
    `<div><script>globalThis.${marker} = true;</script>` +
    `<img src="x" onerror="globalThis.${marker} = true;">${envelope}</div>`;
  const decoded = decodeClipboardHtml(hostile);
  assert.deepEqual(decoded, payload);
  assert.equal((globalThis as Record<string, unknown>)[marker], undefined);
});

it("returns null for foreign html with no envelope attribute", () => {
  assert.equal(decodeClipboardHtml("<p>hello from figma</p>"), null);
  assert.equal(decodeClipboardHtml(""), null);
});

it("returns null for base64 garbage in the attribute — without throwing", () => {
  assert.equal(
    decodeClipboardHtml('<span data-clue-scene="!!!not-base64@@@"></span>'),
    null,
  );
});

it("returns null for valid base64 that is not JSON", () => {
  const encoded = Buffer.from("not json at all", "utf8").toString("base64");
  assert.equal(decodeClipboardHtml(`<span data-clue-scene="${encoded}"></span>`), null);
});

it("refuses a payload with the wrong kind or version", () => {
  const payload = groupPayload();
  assert.equal(validateClipboardPayload({ ...payload, kind: "someone.else/clipboard" }), null);
  assert.equal(validateClipboardPayload({ ...payload, version: 2 }), null);
});

it("refuses extra unknown top-level keys (strict envelope)", () => {
  const payload = groupPayload();
  assert.equal(validateClipboardPayload({ ...payload, surprise: true }), null);
});

it("refuses shape violations field by field", () => {
  const payload = groupPayload();
  assert.equal(validateClipboardPayload(null), null);
  assert.equal(validateClipboardPayload("string"), null);
  assert.equal(validateClipboardPayload({ ...payload, roots: "group_proof" }), null);
  assert.equal(validateClipboardPayload({ ...payload, roots: [] }), null);
  assert.equal(validateClipboardPayload({ ...payload, roots: ["a", "b"] }), null);
  assert.equal(validateClipboardPayload({ ...payload, nodes: {} }), null);
  assert.equal(validateClipboardPayload({ ...payload, assetIds: [7] }), null);
  assert.equal(validateClipboardPayload({ ...payload, workspaceHint: 42 }), null);
  assert.equal(validateClipboardPayload({ ...payload, readableText: null }), null);
  assert.equal(
    validateClipboardPayload({ ...payload, bounds: { x: 0, y: 0, width: "wide", height: 1 } }),
    null,
  );
  assert.equal(
    validateClipboardPayload({ ...payload, bounds: { x: Number.NaN, y: 0, width: 1, height: 1 } }),
    null,
  );
  // A missing key is as foreign as an extra one.
  const missingKey: Record<string, unknown> = { ...payload };
  delete missingKey.readableText;
  assert.equal(validateClipboardPayload(missingKey), null);
});

it("refuses payloads whose node graph is not self-contained", () => {
  const payload = groupPayload();
  // Root not among the nodes.
  assert.equal(
    validateClipboardPayload({ ...payload, roots: ["node_not_carried"] }),
    null,
  );
  // A child id that resolves to nothing in the payload (paste would insert a
  // subtree with a dangling reference).
  const dangling = structuredClone(payload);
  dangling.nodes[0].children.push("node_missing");
  assert.equal(validateClipboardPayload(dangling), null);
  // Duplicate node ids.
  const doubled = structuredClone(payload);
  doubled.nodes.push(structuredClone(doubled.nodes[1]));
  assert.equal(validateClipboardPayload(doubled), null);
});

it("accepts its own serializer's payload verbatim", () => {
  const payload = groupPayload();
  assert.deepEqual(validateClipboardPayload(structuredClone(payload)), payload);
});

it("refuses to encode an oversized payload — copy must not silently truncate", () => {
  const payload = groupPayload();
  const oversized = {
    ...payload,
    readableText: "x".repeat(CLIPBOARD_ENVELOPE_MAX_BYTES + 1),
  };
  assert.equal(encodeClipboardHtml(oversized), null);
});

// ── Task 3: subtree re-mint ────────────────────────────────────────────────

it("re-mints every node with a fresh node-XXXXXXXX id absent from existingIds", () => {
  const payload = groupPayload();
  const existingIds = new Set(Object.keys(HARVESTED_AD_PAGE.nodes));
  const { nodes, rootId } = remintSubtree(payload, existingIds, new Set());
  assert.equal(nodes.length, payload.nodes.length);
  const freshIds = nodes.map((node) => node.id);
  for (const id of freshIds) {
    assert.match(id, /^node-[0-9a-f]{8}$/);
    assert.ok(!existingIds.has(id), `minted id ${id} already exists in the scene`);
  }
  assert.equal(new Set(freshIds).size, freshIds.length, "minted ids must be batch-unique");
  assert.equal(rootId, freshIds[0]);
});

it("rewrites children arrays through the old→new map — no old id survives", () => {
  const payload = groupPayload();
  const { nodes } = remintSubtree(payload, new Set(), new Set());
  const [root, childA, childB] = nodes;
  assert.deepEqual(root.children, [childA.id, childB.id]);
  const oldIds = new Set(payload.nodes.map((node) => node.id));
  for (const node of nodes) {
    for (const child of node.children) {
      assert.ok(!oldIds.has(child), `child ref ${child} still points at a payload id`);
    }
  }
});

it("preserves structure deterministically — same shape and content, new ids only", () => {
  const payload = groupPayload();
  const { nodes } = remintSubtree(payload, new Set(), new Set());
  assert.deepEqual(
    nodes.map((node) => node.kind.kind),
    payload.nodes.map((node) => node.kind.kind),
  );
  // Everything except id/children (and the root's collision-suffixed name)
  // is carried verbatim — transform, size, fills, text content, spans.
  nodes.forEach((node, index) => {
    const source = payload.nodes[index];
    assert.deepEqual(node.transform, source.transform);
    assert.deepEqual(node.size, source.size);
    assert.deepEqual(node.kind, source.kind);
  });
  // And the input payload was not mutated.
  assert.deepEqual(
    payload.nodes.map((node) => node.id),
    ["group_proof", "ellipse_proof_dot", "text_proof_stat"],
  );
});

it("suffixes the root name against sibling names — descendants keep theirs", () => {
  const payload = groupPayload();
  assert.equal(payload.nodes[0].name, "Proof point");

  const noCollision = remintSubtree(payload, new Set(), new Set(["Other"]));
  assert.equal(noCollision.nodes[0].name, "Proof point");

  const collision = remintSubtree(payload, new Set(), new Set(["Proof point"]));
  assert.equal(collision.nodes[0].name, "Proof point_2");

  const chained = remintSubtree(
    payload,
    new Set(),
    new Set(["Proof point", "Proof point_2"]),
  );
  assert.equal(chained.nodes[0].name, "Proof point_3");

  // Descendants keep their names verbatim even when THEY collide.
  const childCollision = remintSubtree(payload, new Set(), new Set(["Proof stat"]));
  assert.equal(childCollision.nodes[2].name, "Proof stat");
});

// ── W1: a pasted node keeps a readable layer label ─────────────────────────
//
// The Task-3 case this replaces asserted that a null name STAYS null. That was
// the defect the live walk found: the layer tree labels a node
// `node.name ?? `${kind} ${id}`` (`sceneQueries.ts::nodeDisplayName`), and
// agent-authored nodes carry `name: null` with a READABLE id ("headline"), so a
// copy that kept the null re-minted to `node-a345153a` and the layer read
// "text node-a345153a". W1's ruling: a null-named copy inherits the SOURCE
// NODE'S ID — the identity the user already sees in the tree.

it("gives a null-named root the source node's id as its name (W1)", () => {
  const payload = groupPayload();
  const anonymous = structuredClone(payload);
  anonymous.nodes[0].name = null;
  const { nodes } = remintSubtree(anonymous, new Set(), new Set(["Proof point"]));
  assert.equal(nodes[0].name, "group_proof");
});

it("suffixes the inherited id when a sibling already shows it (W1)", () => {
  const payload = groupPayload();
  const anonymous = structuredClone(payload);
  anonymous.nodes[0].name = null;
  // The sibling set is DISPLAY identities, so a sibling whose own label is
  // `group_proof` — by name or by id — collides with the inherited one.
  const { nodes } = remintSubtree(anonymous, new Set(), new Set(["group_proof"]));
  assert.equal(nodes[0].name, "group_proof_2");
});

it("gives a null-named DESCENDANT the source id too — never node-XXXXXXXX (W1)", () => {
  const payload = groupPayload();
  const anonymous = structuredClone(payload);
  anonymous.nodes[1].name = null;
  anonymous.nodes[2].name = null;
  const { nodes } = remintSubtree(anonymous, new Set(), new Set());
  assert.equal(nodes[1].name, "ellipse_proof_dot");
  assert.equal(nodes[2].name, "text_proof_stat");
  // …and the id it inherited is NOT the minted one: the label is the source
  // identity, the id is fresh.
  assert.notEqual(nodes[1].name, nodes[1].id);
});

it("retries on id collision — with existing ids and within the batch", () => {
  const payload = groupPayload();
  // Colliding-first fake randomUUID (the structuredEdits-test pattern): the
  // first draw collides with an existing id, the second repeats itself (a
  // batch self-collision), later draws are fresh.
  const draws = [
    "deadbeef-0000-0000-0000-000000000000", // collides with existingIds
    "aaaaaaaa-0000-0000-0000-000000000000",
    "aaaaaaaa-1111-1111-1111-111111111111", // slice repeats aaaaaaaa → retry
    "bbbbbbbb-0000-0000-0000-000000000000",
    "cccccccc-0000-0000-0000-000000000000",
  ];
  const fake = mock.method(crypto, "randomUUID", () => {
    const next = draws.shift();
    assert.ok(next, "ran out of scripted uuids");
    return next as `${string}-${string}-${string}-${string}-${string}`;
  });
  try {
    const { nodes } = remintSubtree(payload, new Set(["node-deadbeef"]), new Set());
    assert.deepEqual(
      nodes.map((node) => node.id),
      ["node-aaaaaaaa", "node-bbbbbbbb", "node-cccccccc"],
    );
  } finally {
    fake.mock.restore();
  }
});

it("measures the cap in UTF-8 bytes, not UTF-16 code units", () => {
  const payload = groupPayload();
  // Each "🚑" is 2 UTF-16 code units but 4 UTF-8 bytes: a code-unit measure
  // would pass this payload, a byte measure must refuse it.
  const emojiCount = Math.floor(CLIPBOARD_ENVELOPE_MAX_BYTES / 4);
  const nearCap = { ...payload, readableText: "🚑".repeat(emojiCount) };
  assert.equal(encodeClipboardHtml(nearCap), null);
});

// ── Task 5: materialization ────────────────────────────────────────────────

/** A freehand placement onto the harvested page (origin (0,0), so the
 * transform IS the page-space target). */
function freehandOntoPage(x = 200, y = 300): PastePlacement {
  return {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: { x, y, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false },
  };
}

function intoCopyRow(index = 2): PastePlacement {
  return { kind: "into-layout", parent: { kind: "node", id: "auto_row_copy" }, index };
}

function expectOps(result: ClipboardMaterialization): { ops: Operation[]; rootId: NodeId } {
  if ("refusal" in result) {
    assert.fail(`expected an op batch, got refusal: ${result.refusal}`);
  }
  return result;
}

function expectRefusal(result: ClipboardMaterialization): string {
  if (!("refusal" in result)) {
    assert.fail(`expected a refusal, got ${result.ops.length} ops`);
  }
  return result.refusal;
}

/** The batch, narrowed — a materialization that emits anything but
 * `insert_node` has already broken its contract. */
function insertOps(ops: readonly Operation[]): Array<Extract<Operation, { kind: "insert_node" }>> {
  return ops.map((op) => {
    if (op.kind !== "insert_node") {
      assert.fail(`expected insert_node, got ${op.kind}`);
    }
    return op;
  });
}

/** The batch's FIRST `insert_node` — W2 may lead with `upsert_asset` ops, so
 * the root's insert is no longer always `ops[0]`. */
function firstInsert(ops: readonly Operation[]): Extract<Operation, { kind: "insert_node" }> {
  const insert = ops.find((op) => op.kind === "insert_node");
  if (!insert || insert.kind !== "insert_node") {
    assert.fail("expected at least one insert_node op");
  }
  return insert;
}

/** The one-image payload — the W2 cases' subject: an image node plus the
 * record that describes its asset. */
function imagePayload() {
  const payload = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "image_hero");
  assert.ok(payload);
  return payload;
}

it("materializes a subtree as one insertNode op per node, parents before children", () => {
  const payload = groupPayload();
  const result = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
  );
  const ops = insertOps(result.ops);
  assert.equal(ops.length, 3);

  // The tree is expressed by the SEATING — a parent ref plus an index per op —
  // and by nothing else. The root lands in the placement's parent; each
  // descendant lands under its own re-minted parent, at its position in that
  // parent's children array.
  assert.deepEqual(ops[0].parent, { kind: "page", id: AD_PAGE_ID });
  assert.equal(ops[0].node.id, result.rootId);
  assert.deepEqual(ops[1].parent, { kind: "node", id: result.rootId });
  assert.equal(ops[1].index, 0);
  assert.deepEqual(ops[2].parent, { kind: "node", id: result.rootId });
  assert.equal(ops[2].index, 1);

  // Parents-before-children as a rule, not a coincidence: an op that names a
  // node parent must find it already inserted by an earlier op.
  const inserted = new Set<string>();
  for (const op of ops) {
    if (op.parent.kind === "node") {
      assert.ok(inserted.has(op.parent.id), `${op.parent.id} inserted after its child`);
    }
    inserted.add(op.node.id);
  }
});

it("inserts every node CHILDLESS — a populated children array is op.child_missing", () => {
  // lumen-core's `insert_node` refuses a node whose children name nodes not yet
  // in the scene (`op.child_missing`, operations.rs), and a batch applies to a
  // draft clone — so ONE such op discards the whole paste. The engine's own
  // subtree-clone path inserts each node with an empty child list, top-down,
  // and lets each child's own InsertNode seat it under its parent
  // (editing.rs `clone.children.clear()`; the reconcile.rs insert invariant).
  const payload = groupPayload();
  const { ops } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
  );
  for (const op of insertOps(ops)) {
    assert.deepEqual(op.node.children, [], `${op.node.id} was inserted with children`);
  }
});

it("re-mints against the target scene's ids — no pasted id collides", () => {
  const payload = groupPayload();
  const { ops, rootId } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
  );
  const inserts = insertOps(ops);
  for (const op of inserts) {
    assert.match(op.node.id, /^node-[0-9a-f]{8}$/);
    assert.ok(!(op.node.id in HARVESTED_AD_PAGE.nodes), `${op.node.id} already in the scene`);
  }
  assert.equal(inserts[0].node.id, rootId);
});

it("appends a freehand root at the end of its parent's children", () => {
  const payload = groupPayload();
  const ontoPage = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
  );
  assert.equal(
    insertOps(ontoPage.ops)[0].index,
    HARVESTED_AD_PAGE.pages[AD_PAGE_ID].children.length,
  );

  const intoFrame = expectOps(
    materializeClipboardPayload(
      HARVESTED_AD_PAGE,
      payload,
      {
        kind: "freehand",
        parent: { kind: "node", id: "frame_ad_root" },
        transform: { x: 10, y: 20, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false },
      },
      new Set(),
    ),
  );
  const frameOps = insertOps(intoFrame.ops);
  assert.deepEqual(frameOps[0].parent, { kind: "node", id: "frame_ad_root" });
  assert.equal(frameOps[0].index, HARVESTED_AD_PAGE.nodes["frame_ad_root"].children.length);
});

it("overrides the root's POSITION only — a paste never restyles the content (R7)", () => {
  const payload = structuredClone(groupPayload());
  payload.nodes[0].transform = {
    x: 40,
    y: 60,
    rotation: 15,
    skew_x: 2,
    skew_y: 3,
    flip_x: true,
    flip_y: false,
  };
  const { ops } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(200, 300), new Set()),
  );
  const inserts = insertOps(ops);
  assert.deepEqual(inserts[0].node.transform, {
    x: 200,
    y: 300,
    rotation: 15,
    skew_x: 2,
    skew_y: 3,
    flip_x: true,
    flip_y: false,
  });
  // Descendants are parent-relative: their transforms ride along untouched.
  assert.deepEqual(inserts[1].node.transform, payload.nodes[1].transform);
});

it("an into-layout root names the container and index and authors NO transform", () => {
  const payload = groupPayload();
  const { ops } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, intoCopyRow(2), new Set()),
  );
  const root = insertOps(ops)[0];
  assert.deepEqual(root.parent, { kind: "node", id: "auto_row_copy" });
  assert.equal(root.index, 2);
  // The solver owns a managed child's position, so the paste writes no
  // geometry it would immediately overwrite.
  assert.deepEqual(root.node.transform, payload.nodes[0].transform);
});

it("suffixes the root name against the placement parent's existing children", () => {
  const payload = groupPayload();
  // auto_row_copy already holds "Proof point" — the very node being pasted
  // back beside itself.
  const intoRow = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, intoCopyRow(2), new Set()),
  );
  assert.equal(insertOps(intoRow.ops)[0].node.name, "Proof point_2");

  // The page's only child is "Ad artboard", so a page paste collides with
  // nothing — the sibling set is the PARENT's children, not the scene's.
  const ontoPage = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
  );
  assert.equal(insertOps(ontoPage.ops)[0].node.name, "Proof point");
});

it("inserts every node with computed: null — stale solved geometry never rides along (R8)", () => {
  const payload = structuredClone(groupPayload());
  for (const node of payload.nodes) {
    node.computed = {
      layout_bounds: { x: 1, y: 2, width: 3, height: 4 },
      render_bounds: { x: 1, y: 2, width: 3, height: 4 },
    };
  }
  const { ops } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
  );
  for (const op of insertOps(ops)) {
    assert.equal(op.node.computed, null);
  }
});

it("shifts every absolute_box by the freehand paste delta (R8)", () => {
  const payload = structuredClone(groupPayload());
  payload.nodes[0].transform.x = 40;
  payload.nodes[0].transform.y = 60;
  payload.nodes[0].absolute_box = { x: 40, y: 60, width: 100, height: 20 };
  payload.nodes[1].absolute_box = { x: 50, y: 70, width: 10, height: 10 };
  const { ops } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(200, 300), new Set()),
  );
  const inserts = insertOps(ops);
  // delta = (200 − 40, 300 − 60) = (160, 240).
  assert.deepEqual(inserts[0].node.absolute_box, { x: 200, y: 300, width: 100, height: 20 });
  assert.deepEqual(inserts[1].node.absolute_box, { x: 210, y: 310, width: 10, height: 10 });
  assert.equal(inserts[2].node.absolute_box, undefined);
});

it("leaves absolute_box untouched for an into-layout paste (R8)", () => {
  const payload = structuredClone(groupPayload());
  payload.nodes[0].absolute_box = { x: 40, y: 60, width: 100, height: 20 };
  const { ops } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, intoCopyRow(2), new Set()),
  );
  // The solver re-places managed children; shifting here would be a guess.
  assert.deepEqual(insertOps(ops)[0].node.absolute_box, { x: 40, y: 60, width: 100, height: 20 });
});

// ── W1 + W2 at the materializer ────────────────────────────────────────────

it("collides the pasted root against sibling DISPLAY identities, not names (W1)", () => {
  // The page's one child is `frame_ad_root`; nulling its name makes its layer
  // label its ID. A null-named paste of the same subtree inherits that same id
  // as its label, so the two collide and the copy must be suffixed. Reading
  // `name` only (the pre-W1 sibling set) sees an EMPTY set here and suffixes
  // nothing — two layers both reading "frame_ad_root".
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes["frame_ad_root"].name = null;
  const payload = serializeSubtree(scene, AD_PAGE_ID, "frame_ad_root");
  assert.ok(payload);
  const { ops } = expectOps(
    materializeClipboardPayload(scene, payload, freehandOntoPage(), new Set()),
  );
  assert.equal(firstInsert(ops).node.name, "frame_ad_root_2");
});

it("carries the referenced asset records verbatim — and only them (W2)", () => {
  const payload = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "image_hero");
  assert.ok(payload);
  assert.deepEqual(
    payload.assets.map((record) => record.id),
    ["asset_ing_2b0928ca4f3a3c70"],
  );
  // Verbatim: the whole record, not a summary — the target document upserts
  // exactly what the source document held.
  assert.deepEqual(
    payload.assets[0],
    HARVESTED_AD_PAGE.assets["asset_ing_2b0928ca4f3a3c70"],
  );
  // A snapshot, like the nodes: a later edit to the live registry must not
  // reach into an already-captured payload.
  const scene = clone(HARVESTED_AD_PAGE);
  const live = serializeSubtree(scene, AD_PAGE_ID, "image_hero");
  assert.ok(live);
  scene.assets["asset_ing_2b0928ca4f3a3c70"].label = "renamed after copy";
  assert.equal(live.assets[0].label, "payment-bento-background.jpg");
  // A subtree with no image carries no records at all.
  const group = serializeSubtree(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof");
  assert.ok(group);
  assert.deepEqual(group.assets, []);
});

it("refuses a payload whose assets key is missing, wrong, or incomplete (W2)", () => {
  const payload = imagePayload();
  const missingKey: Record<string, unknown> = { ...payload };
  delete missingKey.assets;
  assert.equal(validateClipboardPayload(missingKey), null);
  assert.equal(validateClipboardPayload({ ...payload, assets: {} }), null);
  assert.equal(validateClipboardPayload({ ...payload, assets: "asset_one" }), null);
  assert.equal(validateClipboardPayload({ ...payload, assets: [null] }), null);
  assert.equal(validateClipboardPayload({ ...payload, assets: [{ label: "no id" }] }), null);
  assert.equal(validateClipboardPayload({ ...payload, assets: [{ id: "" }] }), null);
  // A payload that NAMES an asset it cannot describe is malformed: the target
  // document would have nothing to upsert and would paint a blank box.
  assert.equal(validateClipboardPayload({ ...payload, assets: [] }), null);
  // …and its own serializer's payload still passes verbatim.
  assert.deepEqual(validateClipboardPayload(structuredClone(payload)), payload);
});

it("upserts a foreign document's asset record BEFORE the inserts, in one batch (W2)", () => {
  // The live-walk defect: `scene.assets` is PER-DOCUMENT, so a same-workspace
  // cross-document paste found the id unknown and refused. The payload now
  // carries the record, so the batch registers it and then inserts.
  const payload = imagePayload();
  const { ops } = expectOps(
    materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
  );
  assert.deepEqual(
    ops.map((op) => op.kind),
    ["upsert_asset", "insert_node"],
  );
  assert.deepEqual(
    (ops[0] as Extract<Operation, { kind: "upsert_asset" }>).asset,
    payload.assets[0],
  );
});

it("upserts NOTHING for a record the target document already holds (W2)", () => {
  const payload = imagePayload();
  const { ops } = expectOps(
    materializeClipboardPayload(
      HARVESTED_AD_PAGE,
      payload,
      freehandOntoPage(),
      new Set(payload.assetIds),
    ),
  );
  assert.deepEqual(
    ops.map((op) => op.kind),
    ["insert_node"],
  );
});

it("refuses an assetIds entry the payload cannot describe — naming the count (W2)", () => {
  // DEFENSIVE ONLY after W2: `validateClipboardPayload` already refuses a
  // payload that names an asset it carries no record for, so this fires just
  // for a hand-built one. The SENTENCE changed with the meaning — an id with
  // no record and no local registration is another workspace's asset, not a
  // gap in this one.
  const payload = structuredClone(imagePayload());
  payload.assets = [];
  assert.equal(
    expectRefusal(
      materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
    ),
    "1 image in this clipboard belongs to another workspace",
  );
  // …and the same paste goes through once the target document holds the asset.
  const allowed = materializeClipboardPayload(
    HARVESTED_AD_PAGE,
    payload,
    freehandOntoPage(),
    new Set(payload.assetIds),
  );
  assert.equal(expectOps(allowed).ops.length, 1);
});

it("pluralizes the foreign-workspace refusal (W2)", () => {
  const payload = structuredClone(groupPayload());
  payload.assetIds = ["asset_one", "asset_two"];
  assert.equal(
    expectRefusal(
      materializeClipboardPayload(HARVESTED_AD_PAGE, payload, freehandOntoPage(), new Set()),
    ),
    "2 images in this clipboard belong to another workspace",
  );
  assert.equal(
    expectRefusal(
      materializeClipboardPayload(
        HARVESTED_AD_PAGE,
        payload,
        freehandOntoPage(),
        new Set(["asset_one"]),
      ),
    ),
    "1 image in this clipboard belongs to another workspace",
  );
});

it("refuses an empty or malformed payload", () => {
  const payload = groupPayload();
  assert.match(
    expectRefusal(
      materializeClipboardPayload(
        HARVESTED_AD_PAGE,
        { ...payload, nodes: [] },
        freehandOntoPage(),
        new Set(),
      ),
    ),
    /empty/i,
  );
  assert.ok(
    expectRefusal(
      materializeClipboardPayload(
        HARVESTED_AD_PAGE,
        { ...payload, roots: [] },
        freehandOntoPage(),
        new Set(),
      ),
    ).length > 0,
  );
  // A payload whose nodes are not ONE tree (here: an orphaned text node no
  // parent claims) has no honest insert order — refuse rather than guess one.
  const orphaned = structuredClone(payload);
  orphaned.nodes[0].children = ["ellipse_proof_dot"];
  assert.ok(
    expectRefusal(
      materializeClipboardPayload(HARVESTED_AD_PAGE, orphaned, freehandOntoPage(), new Set()),
    ).length > 0,
  );
});

it("mutates neither the payload, the placement, nor the target scene", () => {
  const payload = groupPayload();
  const placement = freehandOntoPage();
  const payloadBefore = JSON.stringify(payload);
  const placementBefore = JSON.stringify(placement);
  const sceneBefore = JSON.stringify(HARVESTED_AD_PAGE);
  expectOps(materializeClipboardPayload(HARVESTED_AD_PAGE, payload, placement, new Set()));
  assert.equal(JSON.stringify(payload), payloadBefore);
  assert.equal(JSON.stringify(placement), placementBefore);
  assert.equal(JSON.stringify(HARVESTED_AD_PAGE), sceneBefore);
});

// ── Task 10: rasterToPngBlob ───────────────────────────────────────────────

/**
 * The export rasterizer — the only new impure function on this lane, and the
 * reason it is here rather than in the hook: it is a pure Blob→Blob transform
 * that the copy path injects, so a browser that cannot do it fails ONE
 * representation instead of the copy.
 *
 * WHAT THIS RUNNER CAN AND CANNOT PIN. `tsx --test` has no canvas and no image
 * decoder — jsdom's `<img>` never loads bytes and its `<canvas>` has no 2D
 * context — so the jpeg/webp/svg branches (decode → drawImage → toBlob) have
 * no honest offline case at all. What IS pinned is every branch that decides
 * WITHOUT decoding: the png passthrough (which must not even look for a DOM,
 * because a png needs no rasterizing) and the no-DOM refusal (which must
 * REJECT rather than resolve some placeholder). The decode branches are
 * verified in a browser — the web-toolbar precedent for a DOM-only path.
 */

it("rasterToPngBlob passes a png through untouched — no decode, no DOM", async () => {
  const png = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
  // Deliberately asserted with `document` absent from this runner: a png that
  // needed a canvas would fail in exactly the environment that has none.
  assert.equal(typeof (globalThis as { document?: unknown }).document, "undefined");
  assert.equal(await rasterToPngBlob(png, "image/png"), png);
});

it("rasterToPngBlob REJECTS without a DOM instead of resolving a placeholder", async () => {
  const jpeg = new Blob([new Uint8Array([255, 216, 255])], { type: "image/jpeg" });
  for (const mime of ["image/jpeg", "image/webp", "image/svg+xml"]) {
    await assert.rejects(rasterToPngBlob(jpeg, mime));
  }
});
