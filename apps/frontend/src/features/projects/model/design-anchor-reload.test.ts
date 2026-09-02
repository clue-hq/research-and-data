import assert from "node:assert/strict";
import test from "node:test";
import { anchorReloadDecision } from "./design-anchor-reload";

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
