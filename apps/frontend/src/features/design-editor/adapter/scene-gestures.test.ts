import assert from "node:assert/strict";
import test from "node:test";
import type { NodeId, Operation, Scene } from "../engine/scene/contracts";
import {
  dragActionToOperations,
  handleAtPoint,
  resizeActionToOperation,
} from "../engine/scene/canvaskitGestures";
import {
  gestureReducer,
  initialGestureState,
  type GestureEvent,
  type GestureState,
  type PressTarget,
} from "../engine/scene/gestureMachine";
import {
  screenToWorkspace,
  type WorkspaceViewport,
} from "../engine/scene/workspaceViewport";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  sceneArtboardModel,
  sceneSelectionOutline,
  selectionOutlineForBox,
} from "./scene-canvas-view";
import {
  EMPTY_SCENE_PRESS,
  SCENE_PAGE_ORIGIN,
  cornerHandleAtPoint,
  freezeMotionReport,
  freezeOperationsToPersist,
  pressArmedAfterFreeze,
  sceneDescriptorPoint,
  sceneGestureEffect,
  scenePressHandleTarget,
  scenePressModifiers,
  scenePressNodeTarget,
  sceneSelectionHandlesVisible,
  shouldFreezeLayoutOnPress,
} from "./scene-gestures";

/**
 * AD4.C steps 1+2: the pure decisions behind dragging and resizing a rendered
 * ad — where a press landed, what it grabbed, what a reduced action does, and
 * whether the G-A handles are offered at all.
 *
 * Every case runs against AD2.2's harvested bytes (the seeded
 * `doc_ad22linkedinsquare00000000001`), never a hand-written shape. The
 * harvest carries `computed: null` on every node — the honest at-rest state —
 * so a case that needs a laid-out box injects the geometry the engine's
 * relayout would produce, on a CLONE, exactly as the AD2.5/G-A suites do.
 */

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/**
 * `image_hero` is a fixed-size, absolutely positioned child of
 * `frame_ad_root`, and the frame sits at the page origin, so its laid-out
 * bounds in absolute page space are exactly its authored transform and size.
 * The same box the G-A outline suite uses.
 */
const HERO_BOUNDS = { x: 72, y: 452, width: 1056, height: 676 };
/** The four corners of that box, in descriptor px on a `pt` page (scale 1). */
const HERO_TOP_LEFT = { x: HERO_BOUNDS.x, y: HERO_BOUNDS.y };
const HERO_BOTTOM_RIGHT = {
  x: HERO_BOUNDS.x + HERO_BOUNDS.width,
  y: HERO_BOUNDS.y + HERO_BOUNDS.height,
};

/** The headline's laid-out box inside the copy row — the box a managed press
 * starts from, and (zero-motion freeze) the box it still starts from after. */
const HEADLINE_BOX = { x: 44, y: 40, width: 600, height: 120 };

/**
 * `text_headline` is a child of the `auto_row_copy` auto-layout row, so it is
 * solver-managed and non-freehand: the C-9 freezable class exactly. Laid out,
 * because an unsolved node has no box to move and never arms for its own
 * separate reason.
 */
function managedHeadlineScene(): Scene {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_headline.computed = {
    layout_bounds: { ...HEADLINE_BOX },
    render_bounds: { ...HEADLINE_BOX },
  };
  return scene;
}

function sceneWithLaidOutHero(): Scene {
  const next = clone(HARVESTED_AD_PAGE);
  next.nodes.image_hero.computed = {
    layout_bounds: { ...HERO_BOUNDS },
    render_bounds: { ...HERO_BOUNDS },
  };
  return next;
}

function artboardFor(scene: Scene) {
  const artboard = sceneArtboardModel(scene, AD_PAGE_ID);
  assert.ok(artboard);
  return artboard;
}

function pageFor(scene: Scene) {
  const page = scene.pages[AD_PAGE_ID];
  assert.ok(page);
  return page;
}

const UNIT_VIEWPORT: WorkspaceViewport = { zoom: 1, pan: { x: 0, y: 0 } };

/** A handle press against the hero, at `zoom`, with `image_hero` selected. */
function handlePressAt(
  point: { x: number; y: number },
  {
    gesturesEnabled = true,
    scene = sceneWithLaidOutHero(),
    selectedNodeId = "image_hero" as NodeId | null,
    zoom = 1,
  } = {},
): PressTarget | null {
  const artboard = artboardFor(scene);
  return scenePressHandleTarget({
    artboard,
    gesturesEnabled,
    pageId: AD_PAGE_ID,
    point: sceneDescriptorPoint(point, artboard),
    scene,
    selectedNodeId,
    zoom,
  });
}

/* -------------------------------------------------------------------------
 * R1 — the press target
 * ---------------------------------------------------------------------- */

test("a press on a corner handle grabs the handle, not the node under it", () => {
  const target = handlePressAt({ x: HERO_TOP_LEFT.x + 2, y: HERO_TOP_LEFT.y - 2 });
  assert.deepEqual(target, {
    kind: "handle",
    nodeId: "image_hero",
    handle: "top-left",
    box: { ...HERO_BOUNDS },
    rotation: 0,
  });
  // Each corner answers with its own handle name.
  const corners = [
    [HERO_TOP_LEFT, "top-left"],
    [{ x: HERO_BOTTOM_RIGHT.x, y: HERO_TOP_LEFT.y }, "top-right"],
    [{ x: HERO_TOP_LEFT.x, y: HERO_BOTTOM_RIGHT.y }, "bottom-left"],
    [HERO_BOTTOM_RIGHT, "bottom-right"],
  ] as const;
  for (const [point, handle] of corners) {
    const grabbed = handlePressAt(point);
    assert.equal(grabbed?.kind === "handle" ? grabbed.handle : null, handle);
  }
});

test("Ruling C-6: an EDGE handle is not a v1 target — the press falls through", () => {
  // Dead centre of the top edge: `handleAtPoint` would answer "top".
  const target = handlePressAt({
    x: HERO_BOUNDS.x + HERO_BOUNDS.width / 2,
    y: HERO_BOUNDS.y,
  });
  assert.equal(target, null);
  // …and so would "left" at the middle of the left edge.
  assert.equal(
    handlePressAt({
      x: HERO_BOUNDS.x,
      y: HERO_BOUNDS.y + HERO_BOUNDS.height / 2,
    }),
    null,
  );
});

test("Ruling C-6: the rotate handle is not a v1 target — the press falls through", () => {
  // `handleAtPoint` places rotate 22 descriptor px above the top-edge midpoint.
  assert.equal(
    handlePressAt({
      x: HERO_BOUNDS.x + HERO_BOUNDS.width / 2,
      y: HERO_BOUNDS.y - 22,
    }),
    null,
  );
});

/**
 * Review round 1, finding 2. C-6 was first enforced by FILTERING
 * `handleAtPoint`'s answer, and that function answers with the nearest of all
 * eight handles (after testing the rotate hotspot first). On a small or thin
 * selection a non-corner zone wins "nearest" and the corner grab was then
 * thrown away — so the only resize affordance v1 has degraded exactly where
 * nodes are small. `cornerHandleAtPoint` asks the four corners directly and
 * never consults a zone v1 does not offer.
 */
function sceneWithHeroBounds(bounds: {
  x: number;
  y: number;
  width: number;
  height: number;
}): Scene {
  const next = clone(HARVESTED_AD_PAGE);
  next.nodes.image_hero.computed = {
    layout_bounds: { ...bounds },
    render_bounds: { ...bounds },
  };
  return next;
}

test("C-6: a THIN selection's corner still grabs, where the edge zone used to win", () => {
  const bounds = { x: 44, y: 1000, width: 400, height: 6 };
  const scene = sceneWithHeroBounds(bounds);
  // The left-edge midpoint: 0px from the "left" handle, 3px from two corners.
  const press = { x: bounds.x, y: bounds.y + bounds.height / 2 };
  // What the eight-handle helper answers — the edge zone, nearest by 3px.
  assert.equal(handleAtPoint(press, bounds, 0, 1), "left");
  // A corner is well inside the 7px radius, so a corner resize is available.
  assert.equal(cornerHandleAtPoint(press, bounds, 0, 1), "top-left");
  const target = handlePressAt(press, { scene });
  assert.equal(target?.kind === "handle" ? target.handle : null, "top-left");
});

test("C-6: the invisible rotate hotspot cannot swallow a corner at low zoom", () => {
  // The radius is 7 SCREEN px, so at 25% it is 28 descriptor px — wider than
  // the 22px rotate offset over a 20x20 node, which put the (undrawn, and in
  // v1 unreachable) rotate zone on top of the corner the user can see.
  const bounds = { x: 100, y: 100, width: 20, height: 20 };
  const scene = sceneWithHeroBounds(bounds);
  const press = { x: bounds.x, y: bounds.y };
  assert.equal(handleAtPoint(press, bounds, 0, 0.25), "rotate");
  assert.equal(cornerHandleAtPoint(press, bounds, 0, 0.25), "top-left");
  const target = handlePressAt(press, { scene, zoom: 0.25 });
  assert.equal(target?.kind === "handle" ? target.handle : null, "top-left");
});

test("C-6: the corner test keeps the radius and the nearest-wins rule", () => {
  const box = { x: 0, y: 0, width: 100, height: 100 };
  // Outside the radius is still no handle at all.
  assert.equal(cornerHandleAtPoint({ x: 50, y: 50 }, box, 0, 1), null);
  assert.equal(cornerHandleAtPoint({ x: -8, y: 0 }, box, 0, 1), null);
  assert.equal(cornerHandleAtPoint({ x: -6, y: 0 }, box, 0, 1), "top-left");
  // Nearest wins between two in-range corners.
  assert.equal(cornerHandleAtPoint({ x: 97, y: 102 }, box, 0, 1), "bottom-right");
  // Rotation is honoured: at 90° the top-left corner's neighbours move with it.
  assert.equal(cornerHandleAtPoint({ x: 0, y: 100 }, box, 90, 1), "top-right");
});

test("the handle tolerance is 7 SCREEN px, so it tightens as the canvas zooms in", () => {
  const nearTopLeft = { x: HERO_TOP_LEFT.x + 10, y: HERO_TOP_LEFT.y };
  // 10 descriptor px is 5 screen px at 50% — inside the 7px grab radius.
  assert.equal(handlePressAt(nearTopLeft, { zoom: 0.5 })?.kind, "handle");
  // The same 10 descriptor px is 20 screen px at 200% — outside it.
  assert.equal(handlePressAt(nearTopLeft, { zoom: 2 }), null);
  // And 20 descriptor px is 10 screen px at 50% — outside it too.
  assert.equal(
    handlePressAt({ x: HERO_TOP_LEFT.x + 20, y: HERO_TOP_LEFT.y }, { zoom: 0.5 }),
    null,
  );
});

test("the handle tolerance stays 7 screen px on a page whose unit is not `pt`", () => {
  // The `unitScale` trap, the resize twin of AD2.5's: on an `in` page one scene
  // unit is 96 descriptor px, so a grab radius measured in SCENE units would be
  // 96x too generous. Boxes and points are both descriptor space here, so the
  // radius is unaffected by the page unit.
  const scene = sceneWithLaidOutHero();
  scene.pages[AD_PAGE_ID].size.unit = "in";
  const corner = { x: HERO_BOUNDS.x * 96, y: HERO_BOUNDS.y * 96 };
  assert.equal(
    handlePressAt({ x: corner.x + 6, y: corner.y }, { scene })?.kind,
    "handle",
  );
  assert.equal(handlePressAt({ x: corner.x + 8, y: corner.y }, { scene }), null);
});

test("no selection, or a selection with no laid-out box, grabs no handle", () => {
  assert.equal(handlePressAt(HERO_TOP_LEFT, { selectedNodeId: null }), null);
  assert.equal(
    handlePressAt(HERO_TOP_LEFT, { scene: clone(HARVESTED_AD_PAGE) }),
    null,
  );
});

test("a LOCKED selection shows no handles, so its corners grab nothing", () => {
  const scene = sceneWithLaidOutHero();
  scene.nodes.image_hero.locked = true;
  assert.equal(handlePressAt(HERO_TOP_LEFT, { scene }), null);
});

test("R5: `gestureDisabled` grabs no handle at all", () => {
  assert.equal(handlePressAt(HERO_TOP_LEFT, { gesturesEnabled: false }), null);
});

test("a node press carries the hit node's OWN box and may be dragged", () => {
  const scene = sceneWithLaidOutHero();
  assert.deepEqual(
    scenePressNodeTarget({
      artboard: artboardFor(scene),
      gesturesEnabled: true,
      nodeId: "image_hero",
      pageId: AD_PAGE_ID,
      scene,
    }),
    {
      target: {
        kind: "node",
        nodeId: "image_hero",
        box: { ...HERO_BOUNDS },
        rotation: 0,
      },
      armed: true,
    },
  );
});

test("Ruling C-5: a LOCKED node still SELECTS, but the press can never drag", () => {
  const scene = sceneWithLaidOutHero();
  scene.nodes.image_hero.locked = true;
  const press = scenePressNodeTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    nodeId: "image_hero",
    pageId: AD_PAGE_ID,
    scene,
  });
  assert.equal(press.target.kind, "node");
  assert.equal(press.armed, false);
  // The reducer still emits the selection from the press itself.
  assert.deepEqual(
    gestureReducer(initialGestureState, {
      kind: "down",
      point: HERO_TOP_LEFT,
      target: press.target,
      modifiers: {},
    }).action,
    { kind: "select", nodeId: "image_hero", additive: false },
  );
});

// INVERTED by AD4.C-3 (founder ruling C-9). This case used to assert that a
// layout-managed child "selects but cannot drag either". The founder, testing
// live, ruled that wrong: the agent works in auto-layout, the human does not
// know what auto-layout is, and a human drag must never be refused by it. The
// press now ARMS — `shouldFreezeLayoutOnPress` below fires the zero-motion
// freeze first, which makes the same node directly editable for the same
// press's commit.
test("Ruling C-9: a layout-MANAGED child selects AND arms — the grab freezes the layout", () => {
  // `text_headline` is a child of the `auto_row_copy` auto-layout row.
  const scene = managedHeadlineScene();
  const press = scenePressNodeTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    nodeId: "text_headline",
    pageId: AD_PAGE_ID,
    scene,
  });
  assert.equal(press.target.kind, "node");
  assert.equal(press.armed, true);
});

test("Ruling C-9: a LOCKED layout-managed child still selects and never arms", () => {
  const scene = managedHeadlineScene();
  scene.nodes.text_headline.locked = true;
  const press = scenePressNodeTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    nodeId: "text_headline",
    pageId: AD_PAGE_ID,
    scene,
  });
  assert.equal(press.target.kind, "node");
  assert.equal(press.armed, false);
});

test("G-H: a managed child does not arm mid-turn (the freeze it needs is a write)", () => {
  const scene = managedHeadlineScene();
  const press = scenePressNodeTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: false,
    nodeId: "text_headline",
    pageId: AD_PAGE_ID,
    scene,
  });
  assert.equal(press.armed, false);
});

/* -------------------------------------------------------------------------
 * C-9 / C-10 / C-12 — the freeze-on-grab decisions
 * ---------------------------------------------------------------------- */

test("C-9: a press on a managed NODE freezes the layout before the gesture starts", () => {
  const scene = managedHeadlineScene();
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: true,
      scene,
      target: {
        kind: "node",
        nodeId: "text_headline",
        box: HEADLINE_BOX,
        rotation: 0,
      },
    }),
    true,
  );
});

test("C-9: a corner press on a MANAGED selection now grabs the handle", () => {
  // `scenePressHandleTarget` gates every grab on the same `showResizeHandles`
  // oracle the overlay draws from, so widening the chrome makes the drawn
  // handle grabbable with no second decision — which is exactly why C-10 must
  // freeze on a handle press as well as a node press.
  const scene = managedHeadlineScene();
  const artboard = artboardFor(scene);
  const target = scenePressHandleTarget({
    artboard,
    gesturesEnabled: true,
    pageId: AD_PAGE_ID,
    point: sceneDescriptorPoint(
      { x: HEADLINE_BOX.x + HEADLINE_BOX.width, y: HEADLINE_BOX.y + HEADLINE_BOX.height },
      artboard,
    ),
    scene,
    selectedNodeId: "text_headline",
    zoom: 1,
  });
  assert.equal(target?.kind, "handle");
  assert.equal(target?.nodeId, "text_headline");
});

test("C-10: a press on a managed node's HANDLE freezes too", () => {
  // Upstream guards on `node` alone; it never draws handles on a managed node.
  // This platform does (C-9), and a handle that grabs then commits nothing is
  // the exact defect C-5 exists to prevent.
  const scene = managedHeadlineScene();
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: true,
      scene,
      target: {
        kind: "handle",
        nodeId: "text_headline",
        handle: "bottom-right",
        box: HEADLINE_BOX,
        rotation: 0,
      },
    }),
    true,
  );
});

test("no freeze for a LOCKED node — the predicate is an allow-list, not 'not editable'", () => {
  const scene = managedHeadlineScene();
  scene.nodes.text_headline.locked = true;
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: true,
      scene,
      target: {
        kind: "node",
        nodeId: "text_headline",
        box: HEADLINE_BOX,
        rotation: 0,
      },
    }),
    false,
  );
});

test("the managed child of a LOCKED CONTAINER still asks for a freeze it cannot get", () => {
  // The finding this pins (AD4.C-3 R3): `isNodeFreezableOnGesture` inspects the
  // NODE, not its parent's lock, so it answers true here — while the engine's
  // `build_freeze_layout` skips locked containers and produces an empty batch
  // (`wasmEngine.artifact.test.ts`: "freeze_layout leaves a LOCKED container
  // alone"). The two together would be C-5's exact defect — grab, preview,
  // commit nothing — so the HOST refuses to arm when a freeze it asked for
  // delivers no operations. This case is the reason that guard exists; if this
  // assertion ever flips to false, the guard becomes dead code rather than
  // wrong.
  const scene = managedHeadlineScene();
  scene.nodes.auto_row_copy.locked = true;
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: true,
      scene,
      target: {
        kind: "node",
        nodeId: "text_headline",
        box: HEADLINE_BOX,
        rotation: 0,
      },
    }),
    true,
  );
  // …and an empty outcome persists nothing, which is what the host reads as
  // "this press cannot act".
  assert.deepEqual(
    freezeOperationsToPersist({ accepted: true, operations: [] }),
    [],
  );
});

test("no freeze for an ALREADY-editable node — there is nothing to gain", () => {
  const scene = sceneWithLaidOutHero();
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: true,
      scene,
      target: nodeTargetFor(scene),
    }),
    false,
  );
});

test("no freeze for a press on nothing", () => {
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: true,
      scene: managedHeadlineScene(),
      target: EMPTY_SCENE_PRESS.target,
    }),
    false,
  );
});

test("G-H: no freeze fires mid-turn, because a freeze is a write", () => {
  const scene = managedHeadlineScene();
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: false,
      scene,
      target: {
        kind: "node",
        nodeId: "text_headline",
        box: HEADLINE_BOX,
        rotation: 0,
      },
    }),
    false,
  );
});

/* -------------------------------------------------------------------------
 * The post-freeze arm question (review Important 1)
 * ---------------------------------------------------------------------- */

/**
 * The harvested ad after a freeze, with a SECOND auto-layout row added and the
 * ORIGINAL one locked — the shape that makes "was the batch empty?" the wrong
 * question. `auto_row_copy` stays a locked Stack (the engine skips it), while
 * `auto_row_extra` is freed, so the freeze really did emit operations without
 * freeing `text_headline`.
 */
function partiallyFrozenScene(): Scene {
  const scene = managedHeadlineScene();
  scene.nodes.auto_row_copy.locked = true;
  scene.nodes.auto_row_extra = {
    ...scene.nodes.auto_row_copy,
    id: "auto_row_extra",
    name: "Extra row",
    locked: false,
    // What the freeze did to it.
    layout: { ...scene.nodes.auto_row_copy.layout!, layout_mode: "free" },
    children: ["text_extra"],
  };
  scene.nodes.text_extra = {
    ...scene.nodes.text_headline,
    id: "text_extra",
    name: "Extra text",
    children: [],
  };
  scene.pages[AD_PAGE_ID].children = [
    ...scene.pages[AD_PAGE_ID].children,
    "auto_row_extra",
  ];
  return scene;
}

test("Important 1: the child of the LOCKED container does NOT arm, though the freeze emitted operations", () => {
  // The defect this closes: `build_freeze_layout` skips ONLY the locked
  // container and still frees every other Stack, so the batch is non-empty
  // while this node stayed solver-owned. Inferring "freed" from batch size
  // armed it → previewed → committed nothing = the C-5 defect the guard exists
  // to prevent. The question is now asked of the node, on the post-freeze scene.
  const scene = partiallyFrozenScene();
  assert.equal(
    pressArmedAfterFreeze(scene, {
      kind: "node",
      nodeId: "text_headline",
      box: HEADLINE_BOX,
      rotation: 0,
    }),
    false,
  );
});

test("Important 1: a child the freeze DID free arms", () => {
  const scene = partiallyFrozenScene();
  assert.equal(
    pressArmedAfterFreeze(scene, {
      kind: "node",
      nodeId: "text_extra",
      box: HEADLINE_BOX,
      rotation: 0,
    }),
    true,
  );
});

test("Important 1: a HANDLE press on the locked container's child is refused the same way", () => {
  const scene = partiallyFrozenScene();
  assert.equal(
    pressArmedAfterFreeze(scene, {
      kind: "handle",
      nodeId: "text_headline",
      handle: "bottom-right",
      box: HEADLINE_BOX,
      rotation: 0,
    }),
    false,
  );
});

test("the already-frozen node answers true, so the guard is correct by construction", () => {
  // The idempotent path does not REACH this function today: an already-free
  // node is directly editable, so `shouldFreezeLayoutOnPress` is false and the
  // host returns before any freeze is fired. There is therefore no case where
  // the direct ask changes that path's behaviour — but it is worth pinning
  // that if the early return were ever removed, this answer would still be
  // right, which is the whole reason the direct ask beats the batch-size proxy.
  const scene = partiallyFrozenScene();
  assert.equal(
    shouldFreezeLayoutOnPress({
      gesturesEnabled: true,
      scene,
      target: { kind: "node", nodeId: "text_extra", box: HEADLINE_BOX, rotation: 0 },
    }),
    false,
  );
  assert.equal(
    pressArmedAfterFreeze(scene, {
      kind: "node",
      nodeId: "text_extra",
      box: HEADLINE_BOX,
      rotation: 0,
    }),
    true,
  );
});

test("a press on nothing, and a missing scene, never arm", () => {
  assert.equal(
    pressArmedAfterFreeze(partiallyFrozenScene(), EMPTY_SCENE_PRESS.target),
    false,
  );
  assert.equal(
    pressArmedAfterFreeze(null, {
      kind: "node",
      nodeId: "text_headline",
      box: HEADLINE_BOX,
      rotation: 0,
    }),
    false,
  );
});

test("C-12: an accepted freeze persists EXACTLY the operations the engine already applied", () => {
  const operations = [
    { kind: "update_node", node_id: "auto_row_copy", patch: {} },
  ] as unknown as Operation[];
  assert.deepEqual(
    freezeOperationsToPersist({ accepted: true, operations }),
    operations,
  );
});

test("C-12: the idempotent already-frozen outcome persists NOTHING", () => {
  // An empty batch is what `freeze_layout` answers once no Stack container is
  // left — and what the design API's edits route 422s on.
  assert.deepEqual(
    freezeOperationsToPersist({ accepted: true, operations: [] }),
    [],
  );
});

test("C-12: a rejected freeze, and a freeze on a dead engine, persist NOTHING", () => {
  assert.deepEqual(
    freezeOperationsToPersist({
      accepted: false,
      operations: [
        { kind: "update_node", node_id: "auto_row_copy", patch: {} },
      ] as unknown as Operation[],
    }),
    [],
  );
  assert.deepEqual(freezeOperationsToPersist(null), []);
});

test("a node with no laid-out geometry selects but cannot drag", () => {
  // The harvest as served: `computed` is null, so there is no box to move.
  const scene = clone(HARVESTED_AD_PAGE);
  const press = scenePressNodeTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    nodeId: "image_hero",
    pageId: AD_PAGE_ID,
    scene,
  });
  assert.deepEqual(press.target, {
    kind: "node",
    nodeId: "image_hero",
    box: { x: 0, y: 0, width: 0, height: 0 },
    rotation: 0,
  });
  assert.equal(press.armed, false);
});

test("R5: `gestureDisabled` leaves the press selectable but never armed", () => {
  const scene = sceneWithLaidOutHero();
  const press = scenePressNodeTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: false,
    nodeId: "image_hero",
    pageId: AD_PAGE_ID,
    scene,
  });
  assert.equal(press.target.kind, "node");
  assert.equal(press.armed, false);
});

test("a press on nothing is the empty target, and never a gesture", () => {
  // AD2.5's clear-selection semantics, expressed through the reducer.
  assert.deepEqual(EMPTY_SCENE_PRESS, {
    target: { kind: "empty" },
    armed: false,
  });
  assert.deepEqual(
    gestureReducer(initialGestureState, {
      kind: "down",
      point: { x: 5, y: 5 },
      target: EMPTY_SCENE_PRESS.target,
      modifiers: {},
    }).action,
    { kind: "select", nodeId: null, additive: false },
  );
});

test("a press on nothing clears the selection even with a modifier held", () => {
  // Review round 1, finding 1: AD2.5 cleared UNCONDITIONALLY
  // (`commitSelection(null)`), while the reducer preserves the selection on an
  // ADDITIVE empty press (`gestureMachine.ts:96-100`) — because upstream keeps
  // a multi-selection alive under a held modifier. Multi-select is AD4.E's, not
  // v1's, so no modifier is carried into an empty press at all.
  const scene = sceneWithLaidOutHero();
  for (const held of [
    {},
    { shift: true },
    { meta: true },
    { shift: true, meta: true },
  ]) {
    const reduced = gestureReducer(initialGestureState, {
      kind: "down",
      point: { x: 5, y: 5 },
      target: EMPTY_SCENE_PRESS.target,
      modifiers: scenePressModifiers(EMPTY_SCENE_PRESS.target, held),
    });
    assert.deepEqual(sceneGestureEffect(reduced.action, scene, AD_PAGE_ID), {
      kind: "select",
      nodeId: null,
    });
  }
});

test("a modifier still reaches a handle press — Shift is the reducer's aspect lock", () => {
  const scene = sceneWithLaidOutHero();
  const handle = scenePressHandleTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    pageId: AD_PAGE_ID,
    point: HERO_TOP_LEFT,
    scene,
    selectedNodeId: "image_hero",
    zoom: 1,
  });
  assert.ok(handle);
  assert.deepEqual(scenePressModifiers(handle, { shift: true }), {
    shift: true,
  });
  assert.deepEqual(
    scenePressModifiers(nodeTargetFor(scene), { shift: true, meta: true }),
    { shift: true, meta: true },
  );
});

/* -------------------------------------------------------------------------
 * R1 — the coordinate chain
 * ---------------------------------------------------------------------- */

test("the descriptor point round-trips against the outline, panned and zoomed", () => {
  const scene = sceneWithLaidOutHero();
  const artboard = artboardFor(scene);
  const viewport: WorkspaceViewport = { zoom: 0.5, pan: { x: -88, y: 77 } };
  const outline = selectionOutlineForBox({
    artboard,
    box: HERO_BOUNDS,
    nodeId: "image_hero",
    rotation: 0,
    viewport,
  });
  assert.ok(outline);
  // The stage px the overlay strokes, walked backwards, must land exactly on
  // the descriptor box the press target carries — the two are the same corner.
  assert.deepEqual(
    sceneDescriptorPoint(
      screenToWorkspace({ x: outline.x, y: outline.y }, viewport),
      artboard,
    ),
    HERO_TOP_LEFT,
  );
  // And that same stage point grabs the top-left handle.
  const target = scenePressHandleTarget({
    artboard,
    gesturesEnabled: true,
    pageId: AD_PAGE_ID,
    point: sceneDescriptorPoint(
      screenToWorkspace({ x: outline.x, y: outline.y }, viewport),
      artboard,
    ),
    scene,
    selectedNodeId: "image_hero",
    zoom: viewport.zoom,
  });
  assert.equal(target?.kind, "handle");
});

test("descriptor px are scene units times the page's `unitScale`", () => {
  const scene = sceneWithLaidOutHero();
  scene.pages[AD_PAGE_ID].size.unit = "in";
  const artboard = artboardFor(scene);
  assert.equal(artboard.page.unitScale, 96);
  assert.deepEqual(
    sceneDescriptorPoint({ x: 96, y: 192 }, artboard),
    { x: 96, y: 192 },
  );
});

/* -------------------------------------------------------------------------
 * R2 — what a reduced action does
 * ---------------------------------------------------------------------- */

/** Feed a whole pointer sequence through the reducer, collecting the effects
 * the host would apply. */
function drive(
  scene: Scene,
  events: GestureEvent[],
): ReturnType<typeof sceneGestureEffect>[] {
  let state: GestureState = initialGestureState;
  const effects: ReturnType<typeof sceneGestureEffect>[] = [];
  for (const event of events) {
    const reduced = gestureReducer(state, event);
    state = reduced.state;
    effects.push(sceneGestureEffect(reduced.action, scene, AD_PAGE_ID));
  }
  return effects;
}

function nodeTargetFor(scene: Scene): PressTarget {
  return scenePressNodeTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    nodeId: "image_hero",
    pageId: AD_PAGE_ID,
    scene,
  }).target;
}

test("a committed drag emits exactly the builder's operations, as ONE batch", () => {
  const scene = sceneWithLaidOutHero();
  const origin = { x: 500, y: 700 };
  const moved = { x: 540, y: 730 };
  const effects = drive(scene, [
    { kind: "down", point: origin, target: nodeTargetFor(scene), modifiers: {} },
    { kind: "move", point: moved, modifiers: {} },
    { kind: "up", point: moved, modifiers: {} },
  ]);
  assert.deepEqual(effects[0], { kind: "select", nodeId: "image_hero" });
  assert.deepEqual(effects[1], {
    kind: "preview",
    preview: {
      nodeId: "image_hero",
      box: { x: 112, y: 482, width: 1056, height: 676 },
      rotation: 0,
    },
  });
  const commit = effects[2];
  assert.equal(commit.kind, "commit");
  assert.equal(commit.kind === "commit" && commit.intent, "canvas: drag");
  assert.deepEqual(
    commit.kind === "commit" ? commit.operations : null,
    dragActionToOperations(
      { x: 112, y: 482, width: 1056, height: 676 },
      scene,
      scene.nodes.image_hero,
      pageFor(scene),
      SCENE_PAGE_ORIGIN,
    ),
  );
  assert.ok(commit.kind === "commit" && commit.operations.length > 0);
  // The document scene is never touched — the preview is the only movement.
  assert.deepEqual(scene.nodes.image_hero.transform, {
    ...HARVESTED_AD_PAGE.nodes.image_hero.transform,
  });
});

test("a committed corner resize emits exactly ONE operation", () => {
  const scene = sceneWithLaidOutHero();
  const grab = { ...HERO_BOTTOM_RIGHT };
  const dropped = { x: HERO_BOTTOM_RIGHT.x + 120, y: HERO_BOTTOM_RIGHT.y + 60 };
  const target = scenePressHandleTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    pageId: AD_PAGE_ID,
    point: grab,
    scene,
    selectedNodeId: "image_hero",
    zoom: 1,
  });
  assert.ok(target);
  const effects = drive(scene, [
    { kind: "down", point: grab, target, modifiers: {} },
    { kind: "move", point: dropped, modifiers: {} },
    { kind: "up", point: dropped, modifiers: {} },
  ]);
  // A handle press selects nothing new — the node is already the selection.
  assert.deepEqual(effects[0], { kind: "none" });
  assert.deepEqual(effects[1], {
    kind: "preview",
    preview: {
      nodeId: "image_hero",
      box: { x: 72, y: 452, width: 1176, height: 736 },
      rotation: 0,
    },
  });
  const commit = effects[2];
  assert.equal(commit.kind, "commit");
  assert.equal(commit.kind === "commit" && commit.intent, "canvas: resize");
  assert.equal(commit.kind === "commit" && commit.operations.length, 1);
  assert.deepEqual(
    commit.kind === "commit" ? commit.operations[0] : null,
    resizeActionToOperation(
      { x: 72, y: 452, width: 1176, height: 736 },
      0,
      scene,
      scene.nodes.image_hero,
      pageFor(scene),
      SCENE_PAGE_ORIGIN,
    ),
  );
});

test("Shift rides the reducer: a corner resize keeps the aspect ratio", () => {
  const scene = sceneWithLaidOutHero();
  const grab = { ...HERO_BOTTOM_RIGHT };
  const target = scenePressHandleTarget({
    artboard: artboardFor(scene),
    gesturesEnabled: true,
    pageId: AD_PAGE_ID,
    point: grab,
    scene,
    selectedNodeId: "image_hero",
    zoom: 1,
  });
  assert.ok(target);
  const effects = drive(scene, [
    { kind: "down", point: grab, target, modifiers: { shift: true } },
    {
      kind: "move",
      point: { x: grab.x + 264, y: grab.y },
      modifiers: { shift: true },
    },
  ]);
  const preview = effects[1];
  assert.equal(preview.kind, "preview");
  const box = preview.kind === "preview" ? preview.preview?.box : null;
  assert.ok(box);
  assert.equal(
    Math.round((box.width / box.height) * 1000),
    Math.round((HERO_BOUNDS.width / HERO_BOUNDS.height) * 1000),
  );
});

test("a below-threshold press-and-release emits ONLY the selection", () => {
  const scene = sceneWithLaidOutHero();
  const origin = { x: 500, y: 700 };
  const effects = drive(scene, [
    { kind: "down", point: origin, target: nodeTargetFor(scene), modifiers: {} },
    { kind: "move", point: { x: origin.x + 2, y: origin.y }, modifiers: {} },
    { kind: "up", point: { x: origin.x + 2, y: origin.y }, modifiers: {} },
  ]);
  assert.deepEqual(effects, [
    { kind: "select", nodeId: "image_hero" },
    { kind: "none" },
    { kind: "none" },
  ]);
});

test("Ruling C-8: the additive modifier is dropped — multi-select is not v1", () => {
  const scene = sceneWithLaidOutHero();
  const [effect] = drive(scene, [
    {
      kind: "down",
      point: { x: 500, y: 700 },
      target: nodeTargetFor(scene),
      modifiers: { meta: true, shift: true },
    },
  ]);
  assert.deepEqual(effect, { kind: "select", nodeId: "image_hero" });
});

test("Ruling C-2: a hard reset (Escape / pointer-cancel) emits nothing at all", () => {
  const scene = sceneWithLaidOutHero();
  const origin = { x: 500, y: 700 };
  let state: GestureState = initialGestureState;
  state = gestureReducer(state, {
    kind: "down",
    point: origin,
    target: nodeTargetFor(scene),
    modifiers: {},
  }).state;
  state = gestureReducer(state, {
    kind: "move",
    point: { x: origin.x + 40, y: origin.y },
    modifiers: {},
  }).state;
  assert.equal(state.kind, "dragging");
  // The host's hard reset: back to the initial state, preview dropped. A late
  // pointer-up on the reset machine can no longer commit anything.
  state = initialGestureState;
  const late = gestureReducer(state, {
    kind: "up",
    point: { x: origin.x + 40, y: origin.y },
    modifiers: {},
  });
  assert.deepEqual(sceneGestureEffect(late.action, scene, AD_PAGE_ID), {
    kind: "none",
  });
});

test("a refused node (locked) commits NO operations — an empty write is no write", () => {
  const scene = sceneWithLaidOutHero();
  scene.nodes.image_hero.locked = true;
  const target: PressTarget = {
    kind: "node",
    nodeId: "image_hero",
    box: { ...HERO_BOUNDS },
    rotation: 0,
  };
  const origin = { x: 500, y: 700 };
  const moved = { x: 560, y: 700 };
  const effects = drive(scene, [
    { kind: "down", point: origin, target, modifiers: {} },
    { kind: "move", point: moved, modifiers: {} },
    { kind: "up", point: moved, modifiers: {} },
  ]);
  const commit = effects[2];
  assert.equal(commit.kind, "commit");
  assert.deepEqual(commit.kind === "commit" ? commit.operations : null, []);
});

test("an action for a node the scene no longer carries does nothing", () => {
  const scene = sceneWithLaidOutHero();
  assert.deepEqual(
    sceneGestureEffect(
      { kind: "drag", nodeId: "node_gone", box: HERO_BOUNDS, committed: true },
      scene,
      AD_PAGE_ID,
    ),
    { kind: "none" },
  );
  assert.deepEqual(
    sceneGestureEffect(
      { kind: "drag", nodeId: "image_hero", box: HERO_BOUNDS, committed: true },
      scene,
      null,
    ),
    { kind: "none" },
  );
});

/* -------------------------------------------------------------------------
 * R3 — the preview is a render-time override, never a scene mutation
 * ---------------------------------------------------------------------- */

test("a previewed node draws at the preview box, parent-relative like any other", () => {
  const scene = sceneWithLaidOutHero();
  const preview = {
    nodeId: "image_hero" as NodeId,
    box: { x: 112, y: 482, width: 1056, height: 676 },
    rotation: 0,
  };
  const artboard = artboardFor(scene);
  const previewed = sceneArtboardModel(scene, AD_PAGE_ID, preview);
  assert.ok(previewed);
  const hero = (model: typeof artboard) =>
    model.nodes[0].children.find((child) => child.descriptor.id === "image_hero");
  const before = hero(artboard);
  const after = hero(previewed);
  assert.ok(before && after);
  // `frame_ad_root` has no computed origin in the harvest, so the child's
  // descriptor is page-absolute — the preview box lands verbatim.
  assert.deepEqual(
    { x: after.descriptor.x, y: after.descriptor.y },
    { x: 112, y: 482 },
  );
  assert.deepEqual(
    { x: before.descriptor.x, y: before.descriptor.y },
    { x: 72, y: 452 },
  );
  // Every other node is untouched, and so is the scene.
  assert.deepEqual(
    previewed.nodes[0].children.map((child) => child.descriptor.id),
    artboard.nodes[0].children.map((child) => child.descriptor.id),
  );
  assert.deepEqual(scene.nodes.image_hero.computed?.layout_bounds, HERO_BOUNDS);
});

test("a previewed node inside a laid-out parent keeps the parent's offset", () => {
  const scene = sceneWithLaidOutHero();
  const frameBounds = { x: 0, y: 100, width: 1200, height: 1100 };
  scene.nodes.frame_ad_root.computed = {
    layout_bounds: { ...frameBounds },
    render_bounds: { ...frameBounds },
  };
  const previewed = sceneArtboardModel(scene, AD_PAGE_ID, {
    nodeId: "image_hero" as NodeId,
    box: { x: 112, y: 482, width: 1056, height: 676 },
    rotation: 0,
  });
  assert.ok(previewed);
  const hero = previewed.nodes[0].children.find(
    (child) => child.descriptor.id === "image_hero",
  );
  assert.ok(hero);
  assert.deepEqual(
    { x: hero.descriptor.x, y: hero.descriptor.y },
    { x: 112, y: 382 },
  );
});

test("the selection outline follows the preview box while a gesture runs", () => {
  const scene = sceneWithLaidOutHero();
  const artboard = artboardFor(scene);
  const at = (preview?: {
    nodeId: NodeId;
    box: { x: number; y: number; width: number; height: number };
    rotation: number;
  }) =>
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      preview,
      scene,
      selectedNodeId: "image_hero",
      viewport: UNIT_VIEWPORT,
    });
  assert.deepEqual(at(), {
    nodeId: "image_hero",
    x: 72,
    y: 452,
    width: 1056,
    height: 676,
    rotation: 0,
    frame: null,
  });
  assert.deepEqual(
    at({
      nodeId: "image_hero" as NodeId,
      box: { x: 112, y: 482, width: 1056, height: 676 },
      rotation: 0,
    }),
    {
      nodeId: "image_hero",
      x: 112,
      y: 482,
      width: 1056,
      height: 676,
      rotation: 0,
      frame: null,
    },
  );
  // A preview for some OTHER node never moves this outline.
  assert.deepEqual(
    at({
      nodeId: "rect_accent_bar" as NodeId,
      box: { x: 0, y: 0, width: 10, height: 10 },
      rotation: 0,
    }),
    {
      nodeId: "image_hero",
      x: 72,
      y: 452,
      width: 1056,
      height: 676,
      rotation: 0,
      frame: null,
    },
  );
});

test("the preview outline honours `unitScale` the same way the document box does", () => {
  const scene = sceneWithLaidOutHero();
  scene.pages[AD_PAGE_ID].size.unit = "in";
  const artboard = artboardFor(scene);
  assert.deepEqual(
    sceneSelectionOutline({
      artboard,
      pageId: AD_PAGE_ID,
      preview: {
        nodeId: "image_hero" as NodeId,
        // Descriptor px: the scene-unit box times 96.
        box: { x: 96, y: 192, width: 960, height: 480 },
        rotation: 0,
      },
      scene,
      selectedNodeId: "image_hero",
      viewport: UNIT_VIEWPORT,
    }),
    {
      nodeId: "image_hero",
      x: 96,
      y: 192,
      width: 960,
      height: 480,
      rotation: 0,
      frame: null,
    },
  );
});

/* -------------------------------------------------------------------------
 * R6 — when the G-A handles are offered
 * ---------------------------------------------------------------------- */

test("R6: handles render for an editable selection on a live engine", () => {
  const scene = sceneWithLaidOutHero();
  assert.equal(
    sceneSelectionHandlesVisible({
      engineDisabled: false,
      gestureDisabled: false,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "image_hero",
    }),
    true,
  );
});

test("R6: no handles with no selection, a disabled engine, or G-H in flight", () => {
  const scene = sceneWithLaidOutHero();
  const visible = (options: {
    engineDisabled?: boolean;
    gestureDisabled?: boolean;
    selectedNodeId?: NodeId | null;
  }) =>
    sceneSelectionHandlesVisible({
      engineDisabled: options.engineDisabled ?? false,
      gestureDisabled: options.gestureDisabled ?? false,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId:
        options.selectedNodeId === undefined
          ? "image_hero"
          : options.selectedNodeId,
    });
  assert.equal(visible({ selectedNodeId: null }), false);
  assert.equal(visible({ engineDisabled: true }), false);
  assert.equal(visible({ gestureDisabled: true }), false);
});

// REWRITTEN by AD4.C-3 (founder ruling C-9, ledgered C-13). The LOCKED half is
// byte-identical — a lock is a lock, and no freeze can free it. The
// layout-managed half asserted the rule the founder overturned: a managed node
// now DOES get handles, because the grab freezes the layout before the gesture
// starts and the same press then drags freely.
test("R6: a LOCKED selection is outlined, never handled", () => {
  const locked = sceneWithLaidOutHero();
  locked.nodes.image_hero.locked = true;
  assert.equal(
    sceneSelectionHandlesVisible({
      engineDisabled: false,
      gestureDisabled: false,
      pageId: AD_PAGE_ID,
      scene: locked,
      selectedNodeId: "image_hero",
    }),
    false,
  );
});

test("C-9: a layout-MANAGED selection IS handled — the grab freezes the layout first", () => {
  assert.equal(
    sceneSelectionHandlesVisible({
      engineDisabled: false,
      gestureDisabled: false,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "text_headline",
    }),
    true,
  );
});

test("C-9: a LOCKED layout-managed selection is still refused (a freeze cannot free it)", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_headline.locked = true;
  assert.equal(
    sceneSelectionHandlesVisible({
      engineDisabled: false,
      gestureDisabled: false,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "text_headline",
    }),
    false,
  );
});

test("G-H still hides a freezable node's handles mid-turn — a freeze is a write", () => {
  assert.equal(
    sceneSelectionHandlesVisible({
      engineDisabled: false,
      gestureDisabled: true,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "text_headline",
    }),
    false,
  );
});

/* -------------------------------------------------------------------------
 * The runtime zero-motion report (Task 5)
 * ---------------------------------------------------------------------- */

/** The harvested ad with THREE solved boxes — a text node, an image and the
 * auto-layout row — so a case can move each class independently. */
function solvedFreezeScene(): Scene {
  const scene = managedHeadlineScene();
  scene.nodes.image_hero.computed = {
    layout_bounds: { ...HERO_BOUNDS },
    render_bounds: { ...HERO_BOUNDS },
  };
  scene.nodes.auto_row_copy.computed = {
    layout_bounds: { ...ROW_BOX },
    render_bounds: { ...ROW_BOX },
  };
  return scene;
}

/** The copy row's solved box — a container, so NO height tolerance. */
const ROW_BOX = { x: 44, y: 40, width: 600, height: 200 };

/** The same scene with one node's solved box nudged. */
function movedBy(
  nodeId: string,
  delta: { x?: number; y?: number; width?: number; height?: number },
): Scene {
  const scene = solvedFreezeScene();
  const was = scene.nodes[nodeId].computed!.layout_bounds;
  const now = {
    x: was.x + (delta.x ?? 0),
    y: was.y + (delta.y ?? 0),
    width: was.width + (delta.width ?? 0),
    height: was.height + (delta.height ?? 0),
  };
  scene.nodes[nodeId].computed = { layout_bounds: now, render_bounds: now };
  return scene;
}

test("a freeze that moved nothing reports nothing", () => {
  // The contract the engine's own real-ad tests pin offline: post-freeze
  // geometry is the pre-freeze geometry, box for box.
  assert.deepEqual(
    freezeMotionReport(solvedFreezeScene(), solvedFreezeScene()).moved,
    [],
  );
});

test("a freeze that moved ONE node names it, with both boxes", () => {
  // The 2026-09-20 defect's shape: the bake snapped a row to the artboard
  // edge, so the ad jumped under the finger that fired the freeze.
  const report = freezeMotionReport(
    solvedFreezeScene(),
    movedBy("auto_row_copy", { x: 28 }),
  );
  assert.deepEqual(report.moved, [
    {
      id: "auto_row_copy",
      before: { ...ROW_BOX },
      after: { ...ROW_BOX, x: ROW_BOX.x + 28 },
    },
  ]);
});

test("every axis of every class is watched to 1e-6 — x, y and width on a text node too", () => {
  for (const axis of ["x", "y", "width"] as const) {
    const report = freezeMotionReport(
      solvedFreezeScene(),
      movedBy("text_headline", { [axis]: 0.001 }),
    );
    assert.deepEqual(
      report.moved.map((entry) => entry.id),
      ["text_headline"],
      `a ${axis} drift on a text node is motion`,
    );
  }
  // …and a drift under the floating-point floor is not motion at all.
  assert.deepEqual(
    freezeMotionReport(solvedFreezeScene(), movedBy("image_hero", { x: 1e-9 }))
      .moved,
    [],
  );
});

test("only a TEXT node's height gets the 1px slack — the hug the freeze deliberately leaves un-baked", () => {
  // A hug-height text node re-measures within a pixel of its whole-pixel-
  // rounded Stack height (the engine's documented rounding residual), so a
  // sub-pixel height difference there is not a defect…
  assert.deepEqual(
    freezeMotionReport(solvedFreezeScene(), movedBy("text_headline", { height: 0.71 }))
      .moved,
    [],
  );
  // …but a whole pixel and a half is.
  assert.deepEqual(
    freezeMotionReport(solvedFreezeScene(), movedBy("text_headline", { height: 1.5 }))
      .moved.map((entry) => entry.id),
    ["text_headline"],
  );
  // The slack is the TEXT class's alone: a container's or an image's height is
  // a baked Fixed extent, so the same 0.71px there is a real regression.
  assert.deepEqual(
    freezeMotionReport(solvedFreezeScene(), movedBy("auto_row_copy", { height: 0.71 }))
      .moved.map((entry) => entry.id),
    ["auto_row_copy"],
  );
  assert.deepEqual(
    freezeMotionReport(solvedFreezeScene(), movedBy("image_hero", { height: 0.71 }))
      .moved.map((entry) => entry.id),
    ["image_hero"],
  );
});

test("a node with no solved box on either side is ignored, not reported", () => {
  // The harvest carries `computed: null` on most nodes, and the freeze does
  // not place a node it never solved — an absent box is not a moved one.
  const before = solvedFreezeScene();
  const after = solvedFreezeScene();
  delete after.nodes.image_hero;
  after.nodes.text_headline.computed = null;
  assert.deepEqual(freezeMotionReport(before, after).moved, []);
  // Symmetrically, a node the AFTER scene has and the BEFORE one does not.
  const born = solvedFreezeScene();
  born.nodes.text_born = { ...born.nodes.text_headline, id: "text_born" };
  delete before.nodes.text_born;
  assert.deepEqual(freezeMotionReport(before, born).moved, []);
});
