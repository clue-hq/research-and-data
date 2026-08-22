import assert from "node:assert/strict";
import { it } from "node:test";
import type { Node, Scene } from "../engine/scene/contracts";
import { isNodeFreezableOnGesture } from "../engine/scene/sceneQueries";
import { HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  PANEL_GEOMETRY_PROPERTIES,
  panelWriteIntent,
} from "./scene-panel-freeze";

/**
 * C-9 PANEL PARITY — the panel's half of the founder's ruling, as the pure
 * decision it is.
 *
 * Ruling C-9 (Lane C, already shipped on the canvas): the human is a marketer,
 * auto-layout is the agent's tool, and a human manipulating a node must NEVER
 * be refused by the solver. On the canvas the grab freezes the document's
 * layout first. This module is the same physics for a PANEL commit: a geometry
 * row typed on a solver-managed node freezes first and then writes, instead of
 * evaporating (position/rotation, which `scene-apply.ts` refuses outright) or
 * reflowing the row under the user (width/height, Ruling L12's no-gate).
 *
 * Every case runs over the HARVESTED page (real seeded bytes,
 * `doc_ad22linkedinsquare00000000001`), whose shape is what the cases lean on:
 *   `frame_ad_root` (a PLAIN frame) → `[auto_row_copy, rect_accent_bar,
 *   line_divider, image_hero]` — none solver-managed;
 *   `auto_row_copy` (an `auto_layout` with no `layout_mode`, i.e. a Stack) →
 *   `[text_headline, group_proof]` — both SOLVER-MANAGED.
 */

const SCENE = HARVESTED_AD_PAGE;
/** The managed child the AD4 signature defect was found on. */
const MANAGED = "text_headline";
/** The other managed child — a container, so the same rule must not be
 * text-shaped by accident. */
const MANAGED_GROUP = "group_proof";
/** A child of the PLAIN frame: unmanaged, so today's path is already correct. */
const UNMANAGED = "rect_accent_bar";
const CONTAINER = "auto_row_copy";

const GEOMETRY = [
  "position.x",
  "position.y",
  "rotation",
  "width",
  "height",
] as const;

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** One field of one node replaced — the AD2.4/AD2.5 derived-fixture technique
 * (`scene-apply.test.ts`'s `withNodeField`), so a locked or frozen case is
 * still harvested bytes. */
function withNodeField<Field extends keyof Node>(
  nodeId: string,
  field: Field,
  value: Node[Field],
  base: Scene = SCENE,
): Scene {
  const scene = clone(base);
  const node = scene.nodes[nodeId];
  assert.ok(node, `fixture node ${nodeId} missing`);
  node[field] = value;
  return scene;
}

/** The POST-freeze scene, by the recipe Lane C's own tests use
 * (`scene-arrange.test.ts:434`): `build_freeze_layout` sets the container's
 * `layout_mode` to `"free"` and preserves every other layout member verbatim
 * (`editing.rs:1968-1976`), which is exactly this one-field edit. */
function frozen(base: Scene = SCENE): Scene {
  const stack = base.nodes[CONTAINER]!;
  return withNodeField(
    CONTAINER,
    "layout",
    { ...stack.layout!, layout_mode: "free" },
    base,
  );
}

// ── The ruling ──────────────────────────────────────────────────────────────

it("C-9 panel: every geometry row on a SOLVER-MANAGED node freezes first, then writes", () => {
  for (const property of GEOMETRY) {
    assert.equal(
      panelWriteIntent(SCENE, MANAGED, property),
      "freeze-then-write",
      `${MANAGED} / ${property}`,
    );
    assert.equal(
      panelWriteIntent(SCENE, MANAGED_GROUP, property),
      "freeze-then-write",
      `${MANAGED_GROUP} / ${property}`,
    );
  }
});

it("C-9 panel: W/H is in the set by founder ruling — a DISCLOSED behaviour change, not a repair", () => {
  // Position and Rotation die in `positionOperation` / the rotation arm
  // (`scene-apply.ts:615, 943`): typed, accepted by the input, and silently
  // dropped. W/H is different and the difference is deliberate: Ruling L12
  // leaves the W/H arm ungated, so today a size typed on a managed child DOES
  // write — and the solver then re-flows its siblings under the user's cursor.
  // C-9 replaces that with the same freeze-first physics, so after the freeze
  // nothing but the edited node moves.
  assert.equal(panelWriteIntent(SCENE, MANAGED, "width"), "freeze-then-write");
  assert.equal(panelWriteIntent(SCENE, MANAGED, "height"), "freeze-then-write");
  assert.deepEqual([...PANEL_GEOMETRY_PROPERTIES].sort(), [...GEOMETRY].sort());
});

it("C-9 panel: an UNMANAGED node keeps today's path exactly — no freeze for a node with nothing to gain", () => {
  for (const property of GEOMETRY) {
    assert.equal(
      panelWriteIntent(SCENE, UNMANAGED, property),
      "write",
      `${UNMANAGED} / ${property}`,
    );
  }
  // The artboard and its container siblings are page/frame children too.
  assert.equal(panelWriteIntent(SCENE, "frame_ad_root", "position.x"), "write");
  assert.equal(panelWriteIntent(SCENE, CONTAINER, "width"), "write");
});

it("C-9 panel: a NON-GEOMETRY row is never this slice's business, on any node", () => {
  // The solver owns geometry, not paint or type. These rows already write on a
  // managed node and must not start firing freezes for it.
  for (const property of ["fillColor", "opacity", "fontSize", "text", "gap"]) {
    assert.equal(
      panelWriteIntent(SCENE, MANAGED, property),
      "write",
      `${MANAGED} / ${property}`,
    );
  }
});

it("C-9 panel: the LOCK still gates geometry — a freeze never fires for a locked node", () => {
  // The canvas's posture, kept: C-9 removed the MANAGED refusal and left the
  // lock exactly where it was. `isNodeFreezableOnGesture` refuses a locked node
  // itself, and `scene-apply.ts:667` refuses every row for one.
  const lockedManaged = withNodeField(MANAGED, "locked", true);
  const lockedPlain = withNodeField(UNMANAGED, "locked", true);
  for (const property of GEOMETRY) {
    assert.equal(
      panelWriteIntent(lockedManaged, MANAGED, property),
      "refuse",
      `locked managed / ${property}`,
    );
    assert.equal(
      panelWriteIntent(lockedPlain, UNMANAGED, property),
      "refuse",
      `locked plain / ${property}`,
    );
  }
});

it("C-9 panel: §1.0's LOCK ROW is not geometry — a locked node can still be unlocked", () => {
  // The one row `scene-apply.ts` decides BEFORE its own lock gate, for this
  // exact reason: gating the unlock would make a locked node permanently
  // locked. Ordering the property test ahead of the lock test is what keeps
  // that true here.
  const lockedManaged = withNodeField(MANAGED, "locked", true);
  assert.equal(panelWriteIntent(lockedManaged, MANAGED, "locked"), "write");
  assert.equal(panelWriteIntent(lockedManaged, MANAGED, "fillColor"), "write");
});

it("C-9 panel: a node the scene does not carry refuses geometry rather than freezing the document for it", () => {
  assert.equal(panelWriteIntent(SCENE, "node_does_not_exist", "width"), "refuse");
  assert.equal(panelWriteIntent(SCENE, null, "position.x"), "refuse");
});

// ── The post-freeze re-ask (the hook's second question) ─────────────────────

it("C-9 panel: on the POST-FREEZE scene the same row is a plain WRITE — the freeze is not asked for twice", () => {
  // This is the contract the hook's post-freeze gate leans on: after the
  // freeze the child is FREEHAND (`isNodeFreehand`'s Free-container arm), so
  // the adapter takes it naturally and the answer here is `"write"`. Re-asking
  // is also the c81cd209 pattern — ask the NODE on the post-freeze scene, never
  // the size of the freeze's operation batch.
  const free = frozen();
  for (const property of GEOMETRY) {
    assert.equal(
      panelWriteIntent(free, MANAGED, property),
      "write",
      `frozen / ${property}`,
    );
  }
});

it("C-9 panel: a managed child of a LOCKED CONTAINER still asks for a freeze it cannot get (Lane C's R3)", () => {
  // `isNodeFreezableOnGesture` inspects the NODE, not its parent's lock, so it
  // answers true here while `build_freeze_layout` skips locked containers and
  // frees nothing for it. The decision is honest about that — it says
  // "freeze-then-write" — and the hook then re-asks this very function against
  // the POST-freeze scene, where the node is STILL managed, and refuses to
  // write. That is the canvas's "refuse to arm", one surface over.
  const lockedContainer = withNodeField(CONTAINER, "locked", true);
  assert.equal(
    panelWriteIntent(lockedContainer, MANAGED, "position.x"),
    "freeze-then-write",
  );
  // The freeze cannot free it, so the re-ask on the (unchanged) post-freeze
  // scene is not "write" — no operation is built and nothing is claimed.
  assert.notEqual(
    panelWriteIntent(lockedContainer, MANAGED, "position.x"),
    "write",
  );
});

// ── The predicate is the canvas's, never a second opinion ──────────────────

it("C-9 panel: freeze-then-write is EXACTLY the canvas's own predicate, not a re-implementation", () => {
  // Same allow-list, same node set: whatever the canvas grab would freeze for,
  // the panel freezes for, and nothing else. If `isNodeFreezableOnGesture`
  // gains or loses a case upstream, both surfaces move together.
  for (const nodeId of Object.keys(SCENE.nodes)) {
    assert.equal(
      panelWriteIntent(SCENE, nodeId, "position.x") === "freeze-then-write",
      isNodeFreezableOnGesture(SCENE, nodeId),
      nodeId,
    );
  }
});
