import assert from "node:assert/strict";
import { it } from "node:test";
import {
  sceneCanvasChangeToOperation,
  sceneChangeToOperation,
} from "../adapter/scene-apply";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
  adAutoLayout,
  adFrame,
} from "../adapter/__fixtures__/scene-nodes";
import type { Scene } from "../engine/scene/contracts";
import { canvasWriteTarget } from "./use-scene-inspector-writes";

/**
 * AD4.0 step 2: the §1.1 canvas gate. It is tested as the pure decision it is
 * (`canvasWriteTarget`, exported for exactly this — a `useEffect` listener
 * cannot be exercised without a DOM, the `createReplaceImageHandler`
 * precedent), against AD2.2's harvested bytes.
 *
 * What is being pinned: the canvas schema reaches the screen in TWO selection
 * states, and BOTH must write. Step 1's gate keyed on `selectionId === null`
 * alone, so with the artboard selected every §1.1 row was routed to the node
 * adapter, which maps none of them — browser-proven at review: the size select
 * displayed a size the document never got.
 */

const SCENE = HARVESTED_AD_PAGE;
const AD_ROOT_FRAME_ID = "frame_ad_root";
const ARTIFACT_ID = "artifact_ad";

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** The session as the hook holds it, with the primary selection varied — the
 * only thing the two entry states differ by. */
function session(primaryNodeId: string | null, scene: Scene = SCENE) {
  return { artifactId: ARTIFACT_ID, pageId: AD_PAGE_ID, primaryNodeId, scene };
}

/** One inspector event's addressing, as `useInspectorController` stamps it. */
function event(selectionId: string | null, selectionType = "canvas") {
  return { artifactId: ARTIFACT_ID, selectionId, selectionType };
}

// ── The two entry states ────────────────────────────────────────────────────

it("§1.1: an EMPTY selection is a canvas write (the state step 1 gated on)", () => {
  assert.deepEqual(canvasWriteTarget(event(null), session(null)), {
    pageId: AD_PAGE_ID,
    scene: SCENE,
    selectionId: null,
  });
});

it("§1.1: the ROOT FRAME selected is a canvas write too — the same panel, the second entry state", () => {
  // `sceneSelectionFor` routes the root frame to the CANVAS schema, so
  // clicking the artboard (AD2.5) or its Layers row renders this very panel
  // with the frame addressed.
  assert.deepEqual(
    canvasWriteTarget(
      event(AD_ROOT_FRAME_ID),
      session(AD_ROOT_FRAME_ID),
    ),
    { pageId: AD_PAGE_ID, scene: SCENE, selectionId: AD_ROOT_FRAME_ID },
  );
});

it("§1.1: both entry states write a SIZE row and a BACKGROUND row alike", () => {
  // The gate's whole point: the same event, under either selection, reaches
  // the same adapter and produces the same operation.
  for (const selection of [null, AD_ROOT_FRAME_ID]) {
    const target = canvasWriteTarget(event(selection), session(selection));
    assert.ok(target, `gate: ${selection}`);
    const write = (property: string, value: unknown) =>
      sceneCanvasChangeToOperation(
        { property, selectionId: target.selectionId, value },
        target.scene,
        target.pageId,
      );
    assert.deepEqual(write("sizePreset", "Story (9:16) - 1080x1920")?.kind, "update_page");
    assert.deepEqual(write("customWidth", "1080")?.kind, "update_page");
    assert.deepEqual(write("backgroundColor", "#FF00AA")?.kind, "update_node");
    assert.deepEqual(
      write("backgroundFill", {
        angle: 90,
        stops: [
          { color: "#533AFD", position: 0 },
          { color: "#EA2261", position: 100 },
        ],
        type: "linear-gradient",
      })?.kind,
      "update_node",
    );
  }
});

it("§1.1: a canvas event this gate accepts is ANSWERED here — a refusal is not retried as a node row", () => {
  // The listener returns whether the canvas adapter maps the event or refuses
  // it. It briefly fell through to the node path on the theory that §1.0's
  // lock could arrive stamped "canvas"; it cannot — `InspectorHeader` renders
  // the lock only inside `elementActions`, and `image-inspector.tsx` passes
  // `elementActions={selection !== "canvas" && …}`, so no lock button exists in
  // either entry state (pinned by the source guard in `scene-hydrate.test.ts`).
  //
  // The fall-through was not merely useless: the node adapter maps
  // `strokeColor` / `strokeWidth` / `position.*` / `rotation` for EVERY kind,
  // so a refused canvas event retried there would have written the ROOT FRAME
  // — the artboard — after the canvas adapter deliberately said no. This pins
  // both halves: the canvas adapter refuses these, and the node adapter would
  // NOT have.
  const target = canvasWriteTarget(event(AD_ROOT_FRAME_ID), session(AD_ROOT_FRAME_ID));
  assert.ok(target, "the gate accepts it");
  const canvasRefuses = ([property, value]: readonly [string, unknown]) =>
    assert.equal(
      sceneCanvasChangeToOperation(
        { property, selectionId: target.selectionId, value },
        target.scene,
        target.pageId,
      ),
      null,
      `canvas: ${property}`,
    );
  const nodeWouldWrite = ([property, value]: readonly [string, unknown]) =>
    assert.ok(
      sceneChangeToOperation(
        { property, selectionId: AD_ROOT_FRAME_ID, value },
        adFrame(),
        SCENE,
      ),
      `node: ${property}`,
    );
  for (const row of [
    ["locked", true],
    ["strokeColor", "#FF00AA"],
    ["position.x", "40"],
    ["rotation", "12"],
  ] as const) {
    canvasRefuses(row);
    // What the retry WOULD have done, and why returning is the fix: each of
    // these maps on the root frame node, with no kind guard between them and
    // the artboard.
    nodeWouldWrite(row);
  }
  // `strokeWidth` is the one that happens to refuse on THIS artboard — not
  // because the row is guarded, but because the harvested frame carries no
  // stroke to keep the colour of (AD3.1's own refusal). Give it one and it
  // writes too, which is the point: nothing about the node path knows the
  // event came from the canvas schema.
  canvasRefuses(["strokeWidth", "4"]);
  const stroked = clone(SCENE);
  stroked.nodes[AD_ROOT_FRAME_ID].strokes = [...adAutoLayout().strokes];
  assert.ok(
    sceneChangeToOperation(
      { property: "strokeWidth", selectionId: AD_ROOT_FRAME_ID, value: "4" },
      stroked.nodes[AD_ROOT_FRAME_ID],
      stroked,
    ),
    "node: strokeWidth",
  );
});

// ── The refusals ────────────────────────────────────────────────────────────

it("§1.1 gate: a NON-ROOT node id never takes the canvas branch", () => {
  // The §5 fallback schema (an unrepresentable kind) also renders the canvas
  // panel, hydrated from that NODE — so writing the page from it would state
  // one thing and change another. Root frame ⇒ canvas schema is exactly one
  // way: no other node legitimately carries `selectionType: "canvas"`.
  for (const nodeId of ["text_headline", "auto_row_copy", "line_divider"]) {
    assert.equal(canvasWriteTarget(event(nodeId), session(nodeId)), null, nodeId);
  }
});

it("§1.1 gate: the event's selection must BE the session's selection", () => {
  // The assertion that keeps the two lanes' listeners apart on one window, and
  // the reason a panel still mounted for the tab the user just left cannot
  // write. Both directions, both entry states.
  assert.equal(canvasWriteTarget(event(null), session(AD_ROOT_FRAME_ID)), null);
  assert.equal(canvasWriteTarget(event(AD_ROOT_FRAME_ID), session(null)), null);
  assert.equal(
    canvasWriteTarget(event("text_headline"), session(AD_ROOT_FRAME_ID)),
    null,
  );
});

it("§1.1 gate: an event with NO addressing at all is refused", () => {
  // The dummy fixture path (`dispatchInspectorEvent` with no third argument)
  // leaves `selectionId`/`artifactId` undefined — never equal to a session's
  // `string | null`.
  assert.equal(canvasWriteTarget({ selectionType: "canvas" }, session(null)), null);
  assert.equal(
    canvasWriteTarget({ artifactId: ARTIFACT_ID, selectionType: "canvas" }, session(null)),
    null,
  );
  assert.equal(canvasWriteTarget({ selectionId: null, selectionType: "canvas" }, session(null)), null);
});

it("§1.1 gate: another schema's event is not a canvas write, whatever it is addressed to", () => {
  // The discriminator is the raising schema naming itself.
  for (const selectionType of ["text", "image", "rectangle"]) {
    assert.equal(
      canvasWriteTarget(event(null, selectionType), session(null)),
      null,
      selectionType,
    );
  }
  // An event that names no schema at all states nothing positive, so it is not
  // a canvas write either (the default is spelled out here rather than left to
  // the `event` helper's, which is `"canvas"`).
  assert.equal(
    canvasWriteTarget({ artifactId: ARTIFACT_ID, selectionId: null }, session(null)),
    null,
  );
});

it("§1.1 gate: another artifact's panel cannot write this session's document", () => {
  assert.equal(
    canvasWriteTarget(
      { artifactId: "artifact_other", selectionId: null, selectionType: "canvas" },
      session(null),
    ),
    null,
  );
  assert.equal(
    canvasWriteTarget(event(null), { ...session(null), artifactId: null }),
    null,
  );
});

it("§1.1 gate: a scene or page the session does not hold is never a write", () => {
  assert.equal(canvasWriteTarget(event(null), { ...session(null), scene: null }), null);
  assert.equal(canvasWriteTarget(event(null), { ...session(null), pageId: null }), null);
  assert.equal(
    canvasWriteTarget(event(null), { ...session(null), pageId: "page_missing" }),
    null,
  );
});

it("§1.1 gate: with NO root frame the empty selection still writes, and no node id does", () => {
  // A page whose children open on nothing (one field edited): the size rows
  // remain writable, the Background rows refuse inside the adapter (AD2.4's
  // null contract), and there is no root frame for a node-addressed canvas
  // event to match.
  const rootless = clone(SCENE);
  rootless.pages[AD_PAGE_ID].children = [];
  assert.ok(canvasWriteTarget(event(null), session(null, rootless)), "empty selection");
  assert.equal(
    canvasWriteTarget(
      event(AD_ROOT_FRAME_ID),
      session(AD_ROOT_FRAME_ID, rootless),
    ),
    null,
  );
});
