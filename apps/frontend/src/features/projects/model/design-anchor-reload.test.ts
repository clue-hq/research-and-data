import assert from "node:assert/strict";
import test from "node:test";
import { anchorReloadDecision } from "./design-anchor-reload";
import {
  NO_SCENE_STREAM,
  applySceneStreamFrame,
  seedSceneStreamState,
} from "@/features/design-editor/adapter/scene-stream-cursor";

/**
 * The composite anchor decision (scene live-streaming rung B, task 9 fix 1).
 *
 * Rung A's rule was simple and safe: every `design.checkpoint` reloads the open
 * canvas, rate-limited. Rung B wants ONE exception — do not reload when the
 * canvas is already showing exactly that version, because the reload would
 * replace a picture with an identical one and interrupt a reveal to do it.
 *
 * The trap this function exists to close: the CURSOR's `inSync` is computed
 * from the frames, and says nothing about whether the pump managed to render
 * them. A pump whose engine refused a batch — or which has no engine at all —
 * reports nothing, while the cursor happily goes on saying "in sync". Suppress
 * on the cursor alone and that canvas loses every mid-run reload until the run
 * hands back, which is rung A regressing under exactly the failure rung B
 * introduced.
 *
 * So the suppression needs BOTH facts, and the default when either is unknown
 * is rung A's shipped behaviour: reload.
 */

test("in sync AND the pump is clean — the one case that suppresses", () => {
  const decision = anchorReloadDecision({ cursorInSync: true, pumpClean: true });
  assert.deepEqual(decision, { reloadCanvas: false, anchorInSync: true });
});

test("in sync but the pump is latched dirty — the reload fires and the anchor is stale", () => {
  // The engine refused a batch the cursor cleared, so the picture is missing it
  // and only a reload can repair it. The pump is told `false` so it re-seats
  // from the reloaded document and clears its own latch.
  const decision = anchorReloadDecision({ cursorInSync: true, pumpClean: false });
  assert.deepEqual(decision, { reloadCanvas: true, anchorInSync: false });
});

test("in sync with no pump health published at all — rung A's behaviour", () => {
  // No pump mounted, another tab, the first render before the surface has
  // published anything. Unknown is never treated as healthy.
  const decision = anchorReloadDecision({ cursorInSync: true, pumpClean: null });
  assert.deepEqual(decision, { reloadCanvas: true, anchorInSync: false });
});

test("a stale cursor reloads whatever the pump says", () => {
  for (const pumpClean of [true, false, null] as const) {
    assert.deepEqual(
      anchorReloadDecision({ cursorInSync: false, pumpClean }),
      { reloadCanvas: true, anchorInSync: false },
      `pumpClean=${String(pumpClean)}`,
    );
  }
});

test("the two outputs are always exact opposites", () => {
  for (const cursorInSync of [true, false]) {
    for (const pumpClean of [true, false, null] as const) {
      const decision = anchorReloadDecision({ cursorInSync, pumpClean });
      assert.equal(
        decision.anchorInSync,
        !decision.reloadCanvas,
        "the pump must treat as stale exactly the anchors that reload",
      );
    }
  }
});

/* ---------------------------------------------------------------------------
 * The live late-join walk (task 10, fix round 3).
 *
 * The composed decision, over the frames a controller walk actually saw
 * (`agent_turn_event_stream`, turn 7addaeaf…, document doc_1c35a98d…): a run
 * whose single op batch ended at ledger position 1, a page reload, a document
 * that loaded at v125, and the checkpoint that committed v126 carrying
 * `operations: 1`. The canvas reloaded. It should not have.
 * ------------------------------------------------------------------------ */

test("a canvas that caught up on the join is left alone by the checkpoint behind it", () => {
  const LIVE_TURN = "7addaeaf-75ee-514d-b474-0dd3e42cd312";
  const DOCUMENT = "doc_1c35a98d45435c7bb8d19408bb9e03e8";
  const op = { kind: "update_node", node_id: "cta_label" };

  // The replayed backlog, then the load that joins it, then the checkpoint.
  let state = applySceneStreamFrame(NO_SCENE_STREAM, {
    type: "design.op_batch",
    turnId: LIVE_TURN,
    batch: {
      documentId: DOCUMENT,
      operations: [op],
      operationsTotal: 1,
      iteration: 1,
    },
  });
  state = seedSceneStreamState(state, {
    documentId: DOCUMENT,
    documentVersion: 125,
    turnId: LIVE_TURN,
  });
  state = applySceneStreamFrame(state, {
    type: "design.checkpoint",
    turnId: LIVE_TURN,
    checkpoint: {
      documentId: DOCUMENT,
      version: 126,
      operations: 1,
    },
  });

  const decided = state.actions[state.actions.length - 1]?.action;
  assert.equal(decided?.action, "anchor");
  assert.deepEqual(
    anchorReloadDecision({
      cursorInSync: decided?.action === "anchor" ? decided.inSync : false,
      // The pump applied the join's catch-up and nothing has refused since.
      pumpClean: true,
    }),
    { reloadCanvas: false, anchorInSync: true },
  );
});

test("the same walk, with the seed unable to name the run, still does not reload", () => {
  // Fix round 3: `runningTurn` is null between a replayed `turn.accepted` and
  // the `turn.started` behind it. A load that finished in that window used to
  // seed with no run, undoing the cursor — and this checkpoint then reloaded a
  // canvas that was exactly in sync.
  const LIVE_TURN = "7addaeaf-75ee-514d-b474-0dd3e42cd312";
  const DOCUMENT = "doc_1c35a98d45435c7bb8d19408bb9e03e8";
  const op = { kind: "update_node", node_id: "cta_label" };

  let state = applySceneStreamFrame(NO_SCENE_STREAM, {
    type: "design.op_batch",
    turnId: LIVE_TURN,
    batch: {
      documentId: DOCUMENT,
      operations: [op],
      operationsTotal: 1,
      iteration: 1,
    },
  });
  state = seedSceneStreamState(state, {
    documentId: DOCUMENT,
    documentVersion: 125,
    turnId: null,
  });
  state = applySceneStreamFrame(state, {
    type: "design.checkpoint",
    turnId: LIVE_TURN,
    checkpoint: {
      documentId: DOCUMENT,
      version: 126,
      operations: 1,
    },
  });

  const decided = state.actions[state.actions.length - 1]?.action;
  assert.deepEqual(
    anchorReloadDecision({
      cursorInSync: decided?.action === "anchor" ? decided.inSync : false,
      pumpClean: true,
    }),
    { reloadCanvas: false, anchorInSync: true },
  );
});
