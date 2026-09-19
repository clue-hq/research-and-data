import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene, Transform } from "../engine/scene/contracts";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import type { SceneClipboardPayloadV1 } from "./scene-clipboard";
import { planPastePlacement } from "./scene-clipboard-placement";

/**
 * Clipboard Task 4 — the paste placement planner, a pure decision over the
 * scene's flat node map. No DOM, no transport, no engine solve.
 *
 * THE FIXTURE'S OWN SHAPE, which every case below leans on:
 *   page `page_linkedin_square` → `[frame_ad_root]`;
 *   `frame_ad_root` (frame) → `[auto_row_copy, rect_accent_bar, line_divider,
 *   image_hero]`;
 *   `auto_row_copy` (auto_layout, stack, UNLOCKED) → `[text_headline,
 *   group_proof]` — so `text_headline` and `group_proof` are solver-MANAGED;
 *   `group_proof` (group — NOT layout-managed by the solver) →
 *   `[ellipse_proof_dot, text_proof_stat]`, which are therefore directly
 *   editable under a container whose page-space origin is decidedly non-zero.
 *   EVERY node carries `computed: null` (harvested bytes, no solve ran).
 *
 * ORIGINS ARE INJECTED, NEVER SOLVED. Because `computed` is null everywhere,
 * no page-space origin can be read off these bytes — and the planner is
 * forbidden from reading one anyway. Each case passes a `parentComputedOrigin`
 * accessor (AD4.C-3a style) that returns a REPRESENTATIVE origin for the
 * container it names; the (780, 149) used for `group_proof` is the ballpark of
 * the engine's real solve (the 632-wide headline plus the row's gap and
 * padding precede it in the row), stated here as an injection, not a claim
 * about these bytes.
 *
 * The accessor is keyed by the PARENT container's id — it answers "where does
 * this container sit in page space" — which is deliberately NOT the child-keyed
 * `sceneQueries.parentComputedOrigin(scene, childId)`. A paste target does not
 * exist in the scene yet, so it has no child id to ask about; the planner can
 * only name the parent.
 */

/** An accessor that answers only for the containers a case names, and throws
 * for anything else — so a case that expects NO origin lookup (a page parent)
 * fails loudly if the planner reaches for one anyway. */
function injectOrigins(
  origins: Record<string, { x: number; y: number }>,
): (nodeId: string) => { x: number; y: number } {
  return (nodeId: string) => {
    const origin = origins[nodeId];
    if (!origin) {
      throw new Error(`unexpected parentComputedOrigin lookup: ${nodeId}`);
    }
    return origin;
  };
}

const NO_ORIGINS = injectOrigins({});

/** The `group_proof` container's injected page-space origin (see docblock). */
const GROUP_PROOF_ORIGIN = { x: 780, y: 149 };

function bounds(
  x: number,
  y: number,
  width: number,
  height: number,
): SceneClipboardPayloadV1["bounds"] {
  return { x, y, width, height };
}

/** A position-only transform — the only shape a freehand paste authors. */
function positionOnly(x: number, y: number): Transform {
  return {
    x,
    y,
    rotation: 0,
    skew_x: 0,
    skew_y: 0,
    flip_x: false,
    flip_y: false,
  };
}

function withLocked(nodeId: string, locked: boolean): Scene {
  const scene = structuredClone(HARVESTED_AD_PAGE);
  scene.nodes[nodeId]!.locked = locked;
  return scene;
}

it("pastes INTO a selected auto-layout at the end of its children, with no transform", () => {
  const placement = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: "auto_row_copy",
    payloadBounds: bounds(72, 72, 1056, 184),
    mode: { kind: "paste-cascade", generation: 1 },
    // An index insert into a solver-managed row consults no origin at all.
    parentComputedOrigin: NO_ORIGINS,
  });

  assert.deepEqual(placement, {
    kind: "into-layout",
    parent: { kind: "node", id: "auto_row_copy" },
    // `[text_headline, group_proof]` → appended after both.
    index: 2,
  });
  // Ruling 2/R5: the layout solver owns this child's geometry. The variant
  // carries NO transform, and must not grow one.
  assert.equal("transform" in placement, false);
});

it("pastes INTO a selected auto-layout in viewport-center mode too", () => {
  const placement = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: "auto_row_copy",
    payloadBounds: bounds(72, 72, 1056, 184),
    mode: { kind: "viewport-center", center: { x: 600, y: 600 } },
    parentComputedOrigin: NO_ORIGINS,
  });

  assert.deepEqual(placement, {
    kind: "into-layout",
    parent: { kind: "node", id: "auto_row_copy" },
    index: 2,
  });
});

it("cascades a page-parented paste by +10 per generation under the page", () => {
  const first = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: "frame_ad_root",
    payloadBounds: bounds(0, 0, 1200, 1200),
    mode: { kind: "paste-cascade", generation: 1 },
    // `frame_ad_root` is page-parented: a page origin is (0,0) BY DEFINITION,
    // never a lookup.
    parentComputedOrigin: NO_ORIGINS,
  });

  assert.deepEqual(first, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(10, 10),
  });

  const third = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: "frame_ad_root",
    payloadBounds: bounds(0, 0, 1200, 1200),
    mode: { kind: "paste-cascade", generation: 3 },
    parentComputedOrigin: NO_ORIGINS,
  });

  assert.deepEqual(third, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(30, 30),
  });
});

it("cascades under the SOURCE's parent, and authors the offset PARENT-RELATIVE", () => {
  // `ellipse_proof_dot` sits inside `group_proof` — a plain group, so the node
  // is directly editable and the paste lands beside it, not on the page.
  const placement = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: "ellipse_proof_dot",
    // The copied root's PAGE-space box (what the serializer captures).
    payloadBounds: bounds(780, 189, 40, 40),
    mode: { kind: "paste-cascade", generation: 2 },
    parentComputedOrigin: injectOrigins({ group_proof: GROUP_PROOF_ORIGIN }),
  });

  // Page-space target (800, 209) rebased into `group_proof`'s frame.
  assert.deepEqual(placement, {
    kind: "freehand",
    parent: { kind: "node", id: "group_proof" },
    transform: positionOnly(800 - 780, 209 - 149),
  });
});

it("centers a dropped payload on the pointer, THEN rebases it — the F9 red case", () => {
  // F9 (AD4.C ruling C-11): the v1 gesture builders wrote the PAGE-ABSOLUTE
  // point straight into a PARENT-RELATIVE transform. The founder's repro was
  // exactly this node — the dot inside `group_proof`, whose parent's computed
  // origin is far from zero — so this case pins the rebase AND holds the old
  // page-absolute answer as the explicit wrong one.
  const placement = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: "ellipse_proof_dot",
    payloadBounds: bounds(780, 189, 120, 60),
    mode: { kind: "drop-point", pagePoint: { x: 900, y: 400 } },
    parentComputedOrigin: injectOrigins({ group_proof: GROUP_PROOF_ORIGIN }),
  });

  assert.equal(placement.kind, "freehand");
  assert.deepEqual(placement.parent, { kind: "node", id: "group_proof" });

  // R3: the drop CENTERS the payload on the pointer → page-space (840, 370).
  // R5/F9: the transform is parent-relative → (840-780, 370-149).
  const pageAbsolute = positionOnly(840, 370);
  const parentRelative = positionOnly(60, 221);
  assert.deepEqual(
    placement.kind === "freehand" ? placement.transform : null,
    parentRelative,
  );
  // The RED case: writing the page-space answer into this transform is the F9
  // bug — the dot would fly ~(780, 149) away from where it was dropped.
  assert.notDeepEqual(
    placement.kind === "freehand" ? placement.transform : null,
    pageAbsolute,
  );
});

it("never drops INTO a layout — a pointer drop is explicit placement (R4)", () => {
  const placement = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: "auto_row_copy",
    payloadBounds: bounds(72, 72, 200, 100),
    mode: { kind: "drop-point", pagePoint: { x: 500, y: 300 } },
    // `auto_row_copy`'s own parent is `frame_ad_root`, an ordinary frame.
    parentComputedOrigin: injectOrigins({ frame_ad_root: { x: 0, y: 0 } }),
  });

  assert.deepEqual(placement, {
    kind: "freehand",
    parent: { kind: "node", id: "frame_ad_root" },
    transform: positionOnly(400, 250),
  });
});

it("centers the payload bounds on the viewport center", () => {
  const placement = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: null,
    payloadBounds: bounds(0, 0, 400, 200),
    mode: { kind: "viewport-center", center: { x: 600, y: 600 } },
    parentComputedOrigin: NO_ORIGINS,
  });

  // Centered, not corner-placed: (600 - 400/2, 600 - 200/2). The copied box's
  // own x/y are irrelevant here — only its SIZE is.
  assert.deepEqual(placement, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(400, 500),
  });
});

it("falls through to the page when the selected node is LOCKED", () => {
  const scene = withLocked("rect_accent_bar", true);
  const placement = planPastePlacement({
    scene,
    pageId: AD_PAGE_ID,
    selectedNodeId: "rect_accent_bar",
    payloadBounds: bounds(72, 368, 200, 12),
    mode: { kind: "paste-cascade", generation: 1 },
    parentComputedOrigin: NO_ORIGINS,
  });

  // Unlocked, this selection would place under `frame_ad_root`; locked, the
  // planner refuses to reason about it at all and pastes at page level.
  assert.deepEqual(placement, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(82, 378),
  });
});

it("falls through to the page when the selected auto-layout is LOCKED", () => {
  const scene = withLocked("auto_row_copy", true);
  const placement = planPastePlacement({
    scene,
    pageId: AD_PAGE_ID,
    selectedNodeId: "auto_row_copy",
    payloadBounds: bounds(72, 72, 200, 100),
    mode: { kind: "paste-cascade", generation: 1 },
    parentComputedOrigin: NO_ORIGINS,
  });

  // R2's into-layout clause requires an UNLOCKED container — a locked row is
  // not a paste target, and is not a parent donor either.
  assert.deepEqual(placement, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(82, 82),
  });
});

it("falls through to the page when the selected node is solver-MANAGED", () => {
  const placement = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    // `text_headline` is a child of the auto-layout row: the solver owns its
    // position, so a freehand sibling pasted beside it would be re-flowed.
    selectedNodeId: "text_headline",
    payloadBounds: bounds(116, 112, 632, 104),
    mode: { kind: "paste-cascade", generation: 1 },
    parentComputedOrigin: NO_ORIGINS,
  });

  assert.deepEqual(placement, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(126, 122),
  });
});

it("falls through to the page for a null selection and for an unresolved id", () => {
  const nullSelection = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    selectedNodeId: null,
    payloadBounds: bounds(10, 20, 100, 50),
    mode: { kind: "paste-cascade", generation: 1 },
    parentComputedOrigin: NO_ORIGINS,
  });
  assert.deepEqual(nullSelection, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(20, 30),
  });

  const ghostSelection = planPastePlacement({
    scene: HARVESTED_AD_PAGE,
    pageId: AD_PAGE_ID,
    // A stale selection whose node is already gone — a paste must still land.
    selectedNodeId: "node_deleted_last_turn",
    payloadBounds: bounds(10, 20, 100, 50),
    mode: { kind: "paste-cascade", generation: 1 },
    parentComputedOrigin: NO_ORIGINS,
  });
  assert.deepEqual(ghostSelection, {
    kind: "freehand",
    parent: { kind: "page", id: AD_PAGE_ID },
    transform: positionOnly(20, 30),
  });
});
