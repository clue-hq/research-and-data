import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DESIGN_GENERATION_WAIT_NOTICE,
  DESIGN_LEG_EVENT_TYPES,
  designLegNotice,
  designRefreshForEvent,
  designTurnFailureNotice,
  isDesignLegEvent,
} from "./design-leg";

test("every leg lifecycle frame has a system line, and nothing else does", () => {
  for (const type of DESIGN_LEG_EVENT_TYPES) {
    assert.notEqual(
      designLegNotice({ type, reason: null }),
      null,
      `${type} has no system line`,
    );
  }
  assert.equal(designLegNotice({ type: "turn.completed", reason: null }), null);
  assert.equal(designLegNotice({ type: "text.delta", reason: null }), null);
});

test("the close line names the exit the agent recorded", () => {
  assert.equal(
    designLegNotice({ type: "leg.closed", reason: "locked" }),
    "Design session closed — the page is locked in.",
  );
  assert.equal(
    designLegNotice({ type: "leg.closed", reason: "out_of_scope" }),
    "Design session closed — back to strategy.",
  );
  assert.equal(
    designLegNotice({ type: "leg.closed", reason: "abandoned" }),
    "Design session closed.",
  );
  // A reason this build has not been taught falls back to the plain close
  // sentence rather than rendering the raw code at the user.
  assert.equal(
    designLegNotice({ type: "leg.closed", reason: "some_future_reason" }),
    "Design session closed.",
  );
  assert.equal(
    designLegNotice({ type: "leg.closed", reason: null }),
    "Design session closed.",
  );
});

test("opening and reopening both say the thread now talks to Design", () => {
  assert.equal(
    designLegNotice({ type: "leg.opened", reason: null }),
    "Design session opened — your next message goes to Design.",
  );
  assert.equal(
    designLegNotice({ type: "leg.reopened", reason: null }),
    "Design session reopened — your next message goes to Design.",
  );
  assert.equal(
    designLegNotice({ type: "leg.awaiting_user", reason: null }),
    "Design is ready for your next message.",
  );
});

test("the honest wait copy carries no percentage and no ETA", () => {
  assert.equal(
    DESIGN_GENERATION_WAIT_NOTICE,
    "Website generation often takes 5–15 minutes.",
  );
  assert.equal(/%|\bETA\b|\bat \d/.test(DESIGN_GENERATION_WAIT_NOTICE), false);
});

test("each typed leg refusal renders a sentence, never its code", () => {
  assert.equal(
    designTurnFailureNotice("design_leg_document_finalized"),
    "This page is finalized; revising it needs a new draft revision.",
  );
  assert.equal(
    designTurnFailureNotice("design_leg_account_unresolved"),
    "This page's target account could not be resolved, so the turn was refused. Nothing was generated.",
  );
  assert.equal(
    designTurnFailureNotice("design_leg_turn_failed"),
    "Design couldn't finish this page. Nothing was saved — send another message to try again.",
  );
  assert.equal(
    designTurnFailureNotice("design_leg_turn_crashed"),
    "The design turn stopped unexpectedly. Nothing was saved — send another message to try again.",
  );
});

test("an unknown failure code is reported as-is rather than guessed at", () => {
  assert.equal(designTurnFailureNotice("some_new_code"), "some_new_code");
  assert.equal(designTurnFailureNotice(null), null);
});

test("isDesignLegEvent recognizes exactly the four lifecycle frames", () => {
  assert.equal(isDesignLegEvent("leg.opened"), true);
  assert.equal(isDesignLegEvent("leg.awaiting_user"), true);
  assert.equal(isDesignLegEvent("leg.closed"), true);
  assert.equal(isDesignLegEvent("leg.reopened"), true);
  assert.equal(isDesignLegEvent("turn.completed"), false);
  assert.equal(isDesignLegEvent("leg.something_new"), false);
});

// --- the refresh decision -------------------------------------------------

const activeThread = { activeThreadId: "thr-1" };

test("a design turn's durable hand-back refreshes the feed AND the canvas", () => {
  assert.deepEqual(
    designRefreshForEvent(
      { type: "leg.awaiting_user", threadId: "thr-1" },
      activeThread,
    ),
    { refetchFeed: true, reloadCanvas: true },
  );
  assert.deepEqual(
    designRefreshForEvent({ type: "leg.closed", threadId: "thr-1" }, activeThread),
    { refetchFeed: true, reloadCanvas: true },
  );
});

test("leg birth adds a card but opens nothing (founder ruling F2 = option a)", () => {
  assert.deepEqual(
    designRefreshForEvent({ type: "leg.opened", threadId: "thr-1" }, activeThread),
    { refetchFeed: true, reloadCanvas: false },
  );
  assert.deepEqual(
    designRefreshForEvent(
      { type: "leg.reopened", threadId: "thr-1" },
      activeThread,
    ),
    { refetchFeed: true, reloadCanvas: false },
  );
});

test("ordinary conversation frames never touch the gallery or the canvas", () => {
  for (const type of [
    "turn.completed",
    "turn.failed",
    "turn.started",
    "text.delta",
    "part.created",
    "stream.reset",
  ]) {
    assert.deepEqual(
      designRefreshForEvent({ type, threadId: "thr-1" }, activeThread),
      { refetchFeed: false, reloadCanvas: false },
      `${type} must not refresh`,
    );
  }
});

test("a frame for another thread refreshes nothing", () => {
  assert.deepEqual(
    designRefreshForEvent(
      { type: "leg.awaiting_user", threadId: "thr-2" },
      activeThread,
    ),
    { refetchFeed: false, reloadCanvas: false },
  );
  assert.deepEqual(
    designRefreshForEvent(
      { type: "leg.awaiting_user", threadId: "thr-1" },
      { activeThreadId: null },
    ),
    { refetchFeed: false, reloadCanvas: false },
  );
});
