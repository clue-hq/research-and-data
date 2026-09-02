import assert from "node:assert/strict";
import test from "node:test";
import {
  NO_SCENE_STREAM,
  SCENE_STREAM_ACTION_LOG_LIMIT,
  advanceSceneStreamCursor,
  applySceneStreamFrame,
  newSceneStreamCursor,
  operationsFromStreamFrame,
  type SceneStreamFrame,
} from "./scene-stream-cursor";

/**
 * The §B-3 matrix, case by case (scene live-streaming rung B, task 8).
 *
 * Everything under test is pure: a cursor in, a frame in, a cursor and one
 * action out. That is deliberate — the decision "may this batch be applied to
 * the canvas?" is the one place a live stream can silently corrupt a document
 * (an op applied twice, or applied on top of a version that already contains
 * it), so it is decided by arithmetic that can be exhausted in a test rather
 * than by a component's timing.
 */

const DOC = "doc-1";
const OTHER = "doc-2";

/** One well-formed streamed operation. Only its shape matters here. */
function op(id: string) {
  return { kind: "remove_node", node_id: id };
}

function opBatch(batch: {
  documentId?: string | null;
  operations?: unknown;
  operationsTotal?: number | null;
  iteration?: number | null;
}): SceneStreamFrame {
  return {
    type: "design.op_batch",
    batch: {
      documentId: batch.documentId === undefined ? DOC : batch.documentId,
      operations:
        batch.operations === undefined ? [op("a"), op("b")] : batch.operations,
      operationsTotal:
        batch.operationsTotal === undefined ? 2 : batch.operationsTotal,
      iteration: batch.iteration ?? 1,
    },
  };
}

function checkpoint(mark: {
  documentId?: string | null;
  version?: number | null;
  operations?: number | null;
}): SceneStreamFrame {
  return {
    type: "design.checkpoint",
    checkpoint: {
      documentId: mark.documentId === undefined ? DOC : mark.documentId,
      version: mark.version === undefined ? 7 : mark.version,
      operations: mark.operations === undefined ? 0 : mark.operations,
    },
  };
}

// --- contiguity -----------------------------------------------------------

test("a contiguous batch applies and advances the cursor to its ledger position", () => {
  const start = newSceneStreamCursor(DOC);
  const { cursor, action } = advanceSceneStreamCursor(
    start,
    opBatch({ operations: [op("a"), op("b")], operationsTotal: 2 }),
  );
  assert.deepEqual(action, {
    action: "apply",
    operations: [op("a"), op("b")],
  });
  assert.deepEqual(cursor, { documentId: DOC, position: 2, dirty: false });
});

test("a second contiguous batch applies from the advanced cursor", () => {
  const first = advanceSceneStreamCursor(
    newSceneStreamCursor(DOC),
    opBatch({ operations: [op("a"), op("b")], operationsTotal: 2 }),
  ).cursor;
  const { cursor, action } = advanceSceneStreamCursor(
    first,
    opBatch({ operations: [op("c")], operationsTotal: 3 }),
  );
  assert.equal(action.action, "apply");
  assert.equal(cursor.position, 3);
  assert.equal(cursor.dirty, false);
});

test("contiguity is measured against the ledger POSITION, not the batch size", () => {
  // `operations_total` counts ledger entries that were never streamed (asset
  // and library registrations), so a batch of 2 landing at position 9 is
  // contiguous only when the cursor already stands at 7.
  const seated = { documentId: DOC, position: 7, dirty: false };
  assert.equal(
    advanceSceneStreamCursor(
      seated,
      opBatch({ operations: [op("a"), op("b")], operationsTotal: 9 }),
    ).action.action,
    "apply",
  );
  assert.equal(
    advanceSceneStreamCursor(
      seated,
      opBatch({ operations: [op("a"), op("b")], operationsTotal: 10 }),
    ).action.action,
    "dirty",
  );
});

// --- already reflected ----------------------------------------------------

test("a frame whose total is behind the cursor drops", () => {
  const seated = { documentId: DOC, position: 6, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operations: [op("a")], operationsTotal: 4 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

test("a frame whose total equals the cursor drops — it is already reflected", () => {
  const seated = { documentId: DOC, position: 6, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operations: [op("a")], operationsTotal: 6 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

// --- gaps and unreadable payloads → dirty ---------------------------------

test("a gap marks the cursor dirty and carries the position forward", () => {
  const seated = { documentId: DOC, position: 3, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operations: [op("a")], operationsTotal: 9 }),
  );
  assert.deepEqual(action, { action: "dirty" });
  assert.deepEqual(cursor, { documentId: DOC, position: 9, dirty: true });
});

test("a POSITION-ONLY frame (an oversize batch) marks the cursor dirty", () => {
  // The forwarder drops `operations` past 256 KiB and keeps the position, so
  // this frame is contiguous by its numbers and still unapplicable: there is
  // nothing to apply. Dirty is the honest answer — wait for the checkpoint.
  const seated = { documentId: DOC, position: 3, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(seated, {
    type: "design.op_batch",
    batch: {
      documentId: DOC,
      operations: null,
      operationsTotal: 4,
      iteration: 4,
    },
  });
  assert.deepEqual(action, { action: "dirty" });
  assert.deepEqual(cursor, { documentId: DOC, position: 4, dirty: true });
});

test("a frame with no readable total marks the cursor dirty and moves nothing", () => {
  const seated = { documentId: DOC, position: 3, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operationsTotal: null }),
  );
  assert.deepEqual(action, { action: "dirty" });
  assert.deepEqual(cursor, { documentId: DOC, position: 3, dirty: true });
});

test("malformed operations mark the cursor dirty and never throw", () => {
  const seated = { documentId: DOC, position: 0, dirty: false };
  for (const operations of [
    "not-a-list",
    42,
    {},
    { length: 2 },
    [],
    [null],
    [{}],
    [op("a"), "b"],
    [op("a"), { node_id: "b" }],
  ]) {
    const { action } = advanceSceneStreamCursor(
      seated,
      opBatch({ operations, operationsTotal: 2 }),
    );
    assert.deepEqual(
      action,
      { action: "dirty" },
      `expected dirty for ${JSON.stringify(operations)}`,
    );
  }
});

// --- the dirty state ------------------------------------------------------

test("a dirty cursor drops every op frame until an anchor", () => {
  let cursor = { documentId: DOC, position: 9, dirty: true };
  for (const total of [10, 11, 12]) {
    const step = advanceSceneStreamCursor(
      cursor,
      opBatch({ operations: [op("a")], operationsTotal: total }),
    );
    assert.deepEqual(step.action, { action: "drop" });
    assert.equal(step.cursor, cursor, "a dropped frame moves nothing");
    cursor = step.cursor;
  }
});

test("a stale frame arriving after a gap still drops", () => {
  const gapped = advanceSceneStreamCursor(
    { documentId: DOC, position: 3, dirty: false },
    opBatch({ operations: [op("a")], operationsTotal: 9 }),
  ).cursor;
  // The anchor clears dirty; the in-flight frame behind it is now stale.
  const anchored = advanceSceneStreamCursor(
    gapped,
    checkpoint({ operations: 9, version: 4 }),
  ).cursor;
  const { action } = advanceSceneStreamCursor(
    anchored,
    opBatch({ operations: [op("a")], operationsTotal: 5 }),
  );
  assert.deepEqual(action, { action: "drop" });
});

test("an anchor lets applies resume after a dirty spell", () => {
  const dirty = advanceSceneStreamCursor(
    { documentId: DOC, position: 3, dirty: false },
    opBatch({ operations: null, operationsTotal: 9 }),
  ).cursor;
  const anchored = advanceSceneStreamCursor(
    dirty,
    checkpoint({ operations: 9, version: 4 }),
  ).cursor;
  assert.deepEqual(anchored, { documentId: DOC, position: 9, dirty: false });
  const { action } = advanceSceneStreamCursor(
    anchored,
    opBatch({ operations: [op("a")], operationsTotal: 10 }),
  );
  assert.equal(action.action, "apply");
});

// --- anchors --------------------------------------------------------------

test("a checkpoint standing exactly at a clean cursor anchors IN SYNC", () => {
  const seated = { documentId: DOC, position: 9, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: 9, version: 12 }),
  );
  assert.deepEqual(action, { action: "anchor", version: 12, inSync: true });
  assert.deepEqual(cursor, { documentId: DOC, position: 9, dirty: false });
});

test("a checkpoint ahead of the cursor anchors STALE and re-seats the cursor", () => {
  const seated = { documentId: DOC, position: 4, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: 9, version: 12 }),
  );
  assert.deepEqual(action, { action: "anchor", version: 12, inSync: false });
  assert.deepEqual(cursor, { documentId: DOC, position: 9, dirty: false });
});

test("a checkpoint standing at a DIRTY cursor anchors stale, never in sync", () => {
  const seated = { documentId: DOC, position: 9, dirty: true };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: 9, version: 12 }),
  );
  assert.deepEqual(action, { action: "anchor", version: 12, inSync: false });
  assert.deepEqual(cursor, { documentId: DOC, position: 9, dirty: false });
});

test("a checkpoint with no readable position drops rather than re-seating blind", () => {
  const seated = { documentId: DOC, position: 9, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: null, version: 12 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

// --- one cursor, one document --------------------------------------------

test("an op frame naming another document drops and touches nothing", () => {
  const seated = { documentId: DOC, position: 4, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ documentId: OTHER, operations: [op("a")], operationsTotal: 5 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

test("a checkpoint naming another document drops and does not anchor", () => {
  const seated = { documentId: DOC, position: 4, dirty: true };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ documentId: OTHER, operations: 4, version: 3 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

test("a frame naming NO document drops — an unattributable frame is not ours", () => {
  const seated = { documentId: DOC, position: 4, dirty: false };
  assert.deepEqual(
    advanceSceneStreamCursor(
      seated,
      opBatch({ documentId: null, operationsTotal: 5 }),
    ).action,
    { action: "drop" },
  );
  assert.deepEqual(
    advanceSceneStreamCursor(
      seated,
      checkpoint({ documentId: null, operations: 4 }),
    ).action,
    { action: "drop" },
  );
});

// --- the ported strict tolerance -----------------------------------------

test("operationsFromStreamFrame returns null for anything unreadable, and never throws", () => {
  for (const operations of [
    undefined,
    null,
    "x",
    3,
    {},
    { length: 1, 0: op("a") },
    [],
    [null],
    [[op("a")]],
    [{ node_id: "a" }],
    [op("a"), 7],
  ]) {
    assert.equal(
      operationsFromStreamFrame({ operations }),
      null,
      `expected null for ${JSON.stringify(operations) ?? "undefined"}`,
    );
  }
});

test("operationsFromStreamFrame returns the batch when every member is an operation", () => {
  const operations = [op("a"), op("b")];
  assert.deepEqual(operationsFromStreamFrame({ operations }), operations);
});

// --- the per-document fold the controller holds ---------------------------

test("the fold keeps one cursor per document and logs each action in order", () => {
  let state = NO_SCENE_STREAM;
  state = applySceneStreamFrame(
    state,
    opBatch({ operations: [op("a")], operationsTotal: 1 }),
  );
  state = applySceneStreamFrame(
    state,
    opBatch({
      documentId: OTHER,
      operations: [op("z")],
      operationsTotal: 4,
    }),
  );
  state = applySceneStreamFrame(
    state,
    opBatch({ operations: [op("b")], operationsTotal: 2 }),
  );
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    position: 2,
    dirty: false,
  });
  assert.deepEqual(state.cursors.get(OTHER), {
    documentId: OTHER,
    position: 4,
    dirty: true,
  });
  assert.deepEqual(
    state.actions.map((record) => [record.sequence, record.documentId, record.action.action]),
    [
      [1, DOC, "apply"],
      [2, OTHER, "dirty"],
      [3, DOC, "apply"],
    ],
  );
});

test("the fold ignores a frame that names no document", () => {
  const state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ documentId: null, operationsTotal: 3 }),
  );
  assert.equal(state, NO_SCENE_STREAM);
});

test("the action log is bounded, keeping the most recent actions", () => {
  let state = NO_SCENE_STREAM;
  const frames = SCENE_STREAM_ACTION_LOG_LIMIT + 10;
  for (let index = 1; index <= frames; index += 1) {
    state = applySceneStreamFrame(
      state,
      opBatch({ operations: [op(`n${index}`)], operationsTotal: index }),
    );
  }
  assert.equal(state.actions.length, SCENE_STREAM_ACTION_LOG_LIMIT);
  assert.equal(state.actions[0].sequence, frames - SCENE_STREAM_ACTION_LOG_LIMIT + 1);
  assert.equal(state.actions[state.actions.length - 1].sequence, frames);
});

test("a dropped frame leaves the fold's state untouched — no re-render, no log entry", () => {
  const seated = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ operations: [op("a")], operationsTotal: 1 }),
  );
  // NOTE the absent case: a frame for ANOTHER document is not a drop here. The
  // cursor drops it (rule 1), but the FOLD routes by the frame's own document,
  // so `doc-2` simply gets its own cursor — which is exactly how the surface
  // reads the one for the document it has open without the controller ever
  // being told which that is.
  for (const frame of [
    opBatch({ operations: [op("a")], operationsTotal: 1 }), // already reflected
    checkpoint({ operations: null }), // unreadable position
  ]) {
    assert.equal(
      applySceneStreamFrame(seated, frame),
      seated,
      "a drop must return the very same state object",
    );
  }
});

test("every drop path returns the cursor it was given, unchanged by identity", () => {
  // The invariant `applySceneStreamFrame`'s shortcut above rests on.
  const seated = { documentId: DOC, position: 6, dirty: true };
  for (const frame of [
    opBatch({ operationsTotal: 4 }),
    opBatch({ documentId: OTHER }),
    opBatch({ documentId: null }),
    opBatch({ operationsTotal: 9 }),
    checkpoint({ documentId: OTHER }),
    checkpoint({ documentId: null }),
    checkpoint({ operations: null }),
  ]) {
    const step = advanceSceneStreamCursor(seated, frame);
    if (step.action.action !== "drop") continue;
    assert.equal(step.cursor, seated);
  }
});
