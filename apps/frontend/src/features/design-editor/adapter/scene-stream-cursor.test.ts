import assert from "node:assert/strict";
import test from "node:test";
import {
  NO_SCENE_STREAM,
  SCENE_STREAM_ACTION_LOG_LIMIT,
  SCENE_STREAM_CHECKPOINT_LOG_LIMIT,
  advanceSceneStreamCursor,
  applySceneStreamFrame,
  newSceneStreamCursor,
  operationsFromStreamFrame,
  replaySceneStreamJoin,
  seedSceneStreamCursor,
  seedSceneStreamState,
  type SceneCheckpointRecord,
  type SceneStreamActionRecord,
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
  turnId?: string | null;
}): SceneStreamFrame {
  return {
    type: "design.op_batch",
    turnId: batch.turnId ?? null,
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
  turnId?: string | null;
}): SceneStreamFrame {
  return {
    type: "design.checkpoint",
    turnId: mark.turnId ?? null,
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
    operationsTotal: 2,
  });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 2, dirty: false });
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
  const seated = { documentId: DOC, turnId: null, position: 7, dirty: false };
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
  const seated = { documentId: DOC, turnId: null, position: 6, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operations: [op("a")], operationsTotal: 4 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

test("a frame whose total equals the cursor drops — it is already reflected", () => {
  const seated = { documentId: DOC, turnId: null, position: 6, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operations: [op("a")], operationsTotal: 6 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

// --- gaps and unreadable payloads → dirty ---------------------------------

test("a gap marks the cursor dirty and carries the position forward", () => {
  const seated = { documentId: DOC, turnId: null, position: 3, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operations: [op("a")], operationsTotal: 9 }),
  );
  assert.deepEqual(action, { action: "dirty" });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 9, dirty: true });
});

test("a POSITION-ONLY frame (an oversize batch) marks the cursor dirty", () => {
  // The forwarder drops `operations` past 256 KiB and keeps the position, so
  // this frame is contiguous by its numbers and still unapplicable: there is
  // nothing to apply. Dirty is the honest answer — wait for the checkpoint.
  const seated = { documentId: DOC, turnId: null, position: 3, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(seated, {
    type: "design.op_batch",
    turnId: null,
    batch: {
      documentId: DOC,
      operations: null,
      operationsTotal: 4,
      iteration: 4,
    },
  });
  assert.deepEqual(action, { action: "dirty" });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 4, dirty: true });
});

test("a frame with no readable total marks the cursor dirty and moves nothing", () => {
  const seated = { documentId: DOC, turnId: null, position: 3, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ operationsTotal: null }),
  );
  assert.deepEqual(action, { action: "dirty" });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 3, dirty: true });
});

test("malformed operations mark the cursor dirty and never throw", () => {
  const seated = { documentId: DOC, turnId: null, position: 0, dirty: false };
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
  let cursor = { documentId: DOC, turnId: null, position: 9, dirty: true };
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
    { documentId: DOC, turnId: null, position: 3, dirty: false },
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
    { documentId: DOC, turnId: null, position: 3, dirty: false },
    opBatch({ operations: null, operationsTotal: 9 }),
  ).cursor;
  const anchored = advanceSceneStreamCursor(
    dirty,
    checkpoint({ operations: 9, version: 4 }),
  ).cursor;
  assert.deepEqual(anchored, { documentId: DOC, turnId: null, position: 9, dirty: false });
  const { action } = advanceSceneStreamCursor(
    anchored,
    opBatch({ operations: [op("a")], operationsTotal: 10 }),
  );
  assert.equal(action.action, "apply");
});

// --- anchors --------------------------------------------------------------

test("a checkpoint standing exactly at a clean cursor anchors IN SYNC", () => {
  const seated = { documentId: DOC, turnId: null, position: 9, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: 9, version: 12 }),
  );
  assert.deepEqual(action, { action: "anchor", version: 12, inSync: true });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 9, dirty: false });
});

test("a checkpoint ahead of the cursor anchors STALE and re-seats the cursor", () => {
  const seated = { documentId: DOC, turnId: null, position: 4, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: 9, version: 12 }),
  );
  assert.deepEqual(action, { action: "anchor", version: 12, inSync: false });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 9, dirty: false });
});

test("a checkpoint standing at a DIRTY cursor anchors stale, never in sync", () => {
  const seated = { documentId: DOC, turnId: null, position: 9, dirty: true };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: 9, version: 12 }),
  );
  assert.deepEqual(action, { action: "anchor", version: 12, inSync: false });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 9, dirty: false });
});

test("a checkpoint with no readable position drops rather than re-seating blind", () => {
  const seated = { documentId: DOC, turnId: null, position: 9, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ operations: null, version: 12 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

// --- one cursor, one document --------------------------------------------

test("an op frame naming another document drops and touches nothing", () => {
  const seated = { documentId: DOC, turnId: null, position: 4, dirty: false };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    opBatch({ documentId: OTHER, operations: [op("a")], operationsTotal: 5 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

test("a checkpoint naming another document drops and does not anchor", () => {
  const seated = { documentId: DOC, turnId: null, position: 4, dirty: true };
  const { cursor, action } = advanceSceneStreamCursor(
    seated,
    checkpoint({ documentId: OTHER, operations: 4, version: 3 }),
  );
  assert.deepEqual(action, { action: "drop" });
  assert.equal(cursor, seated);
});

test("a frame naming NO document drops — an unattributable frame is not ours", () => {
  const seated = { documentId: DOC, turnId: null, position: 4, dirty: false };
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
    turnId: null,
    position: 2,
    dirty: false,
  });
  assert.deepEqual(state.cursors.get(OTHER), {
    documentId: OTHER,
    turnId: null,
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
  const seated = { documentId: DOC, turnId: null, position: 6, dirty: true };
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

/* ---------------------------------------------------------------------------
 * Late join (task 10) — the seed.
 *
 * Task 8's cursor starts at 0 because nothing has been streamed for it yet.
 * That is right for a canvas opened BEFORE the run and wrong for one opened
 * DURING it: the document it loaded already contains every operation the run
 * committed, so a cursor at 0 either goes dirty on the next frame (best case,
 * no live motion) or — if the run's whole ledger happens to be in the replayed
 * backlog — applies operations the loaded document already holds. The seed is
 * the answer: the loaded VERSION is a position in the same ledger, and the
 * replayed `design.checkpoint` frames are what translate it.
 * ------------------------------------------------------------------------ */

function mark(
  documentId: string | null,
  version: number | null,
  operations: number | null,
  turnId: string | null = null,
): SceneCheckpointRecord {
  return { documentId, turnId, version, operations };
}

test("a late join seeds from the replayed checkpoint that committed the loaded version", () => {
  const cursor = seedSceneStreamCursor({
    documentId: DOC,
    documentVersion: 7,
    turnId: null,
    backlogCheckpoints: [
      mark(DOC, 5, 40),
      mark(DOC, 7, 96),
      // Committed after the version this canvas loaded: the document does NOT
      // contain these operations, so they must not move the cursor.
      mark(DOC, 8, 120),
    ],
  });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 96, dirty: false });
});

test("the seed reads only its own document's checkpoints", () => {
  const cursor = seedSceneStreamCursor({
    documentId: DOC,
    documentVersion: 7,
    turnId: null,
    backlogCheckpoints: [
      mark(OTHER, 7, 500),
      mark(null, 7, 400),
      mark(DOC, 7, 96),
      // Unreadable marks are skipped exactly as the fold declines to re-seat on
      // one: a position that cannot be read is not evidence of anything.
      mark(DOC, null, 300),
      mark(DOC, 9, null),
    ],
  });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 96, dirty: false });
});

test("a version-0 document with no checkpoint in the backlog seeds at 0 — task 8's default", () => {
  const cursor = seedSceneStreamCursor({
    documentId: DOC,
    documentVersion: 0,
    turnId: null,
    backlogCheckpoints: [mark(OTHER, 3, 50)],
  });
  assert.deepEqual(cursor, newSceneStreamCursor(DOC));
});

test("a document AHEAD of every replayed checkpoint seeds dirty at the highest known position", () => {
  // The backlog horizon did not reach the checkpoint that committed version 9.
  // Nothing may be applied until the next anchor — the canvas honestly shows
  // the document it loaded meanwhile.
  const cursor = seedSceneStreamCursor({
    documentId: DOC,
    documentVersion: 9,
    turnId: null,
    backlogCheckpoints: [mark(DOC, 3, 20), mark(DOC, 5, 40)],
  });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 40, dirty: true });
});

test("a version no checkpoint describes seeds dirty, even with marks on both sides of it", () => {
  // The straddle. A mark BELOW the loaded version is a lower bound, not a
  // position: version 6 holds v5's 40 operations plus however many the commit
  // that produced it added, and no replayed frame says how many. Seeding at 40
  // would accept a frame that begins at 40 and re-apply operations the loaded
  // document already contains.
  const cursor = seedSceneStreamCursor({
    documentId: DOC,
    documentVersion: 6,
    turnId: null,
    backlogCheckpoints: [mark(DOC, 5, 40), mark(DOC, 8, 120)],
  });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 120, dirty: true });
});

test("a run with NO checkpoints of its own starts its ledger at 0 on the loaded base", () => {
  // Fix round 1: an empty backlog is not an unknown position, it is a run that
  // has committed nothing — and a run's ledger counts from zero over whatever
  // the document already is. (Before the per-run scoping this seeded dirty,
  // which is what kept the first batch of a fresh run off the canvas.)
  const cursor = seedSceneStreamCursor({
    documentId: DOC,
    documentVersion: 4,
    turnId: null,
    backlogCheckpoints: [],
  });
  assert.deepEqual(cursor, { documentId: DOC, turnId: null, position: 0, dirty: false });
});

test("the fold keeps the readable checkpoint marks the seed reads, bounded", () => {
  let state = NO_SCENE_STREAM;
  assert.deepEqual(state.checkpoints, []);
  state = applySceneStreamFrame(state, checkpoint({ version: 5, operations: 40 }));
  state = applySceneStreamFrame(state, checkpoint({ version: 6, operations: 64 }));
  assert.deepEqual(state.checkpoints, [mark(DOC, 5, 40), mark(DOC, 6, 64)]);

  const total = SCENE_STREAM_CHECKPOINT_LOG_LIMIT + 5;
  for (let index = 1; index <= total; index += 1) {
    state = applySceneStreamFrame(
      state,
      checkpoint({ version: 100 + index, operations: 1000 + index }),
    );
  }
  assert.equal(state.checkpoints.length, SCENE_STREAM_CHECKPOINT_LOG_LIMIT);
  assert.deepEqual(state.checkpoints.at(-1), mark(DOC, 100 + total, 1000 + total));
});

test("seeding the fold re-seats the document's cursor and logs the join", () => {
  // A late joiner's replayed backlog: two checkpoints, then op frames the
  // un-seeded cursor could not place.
  let state = applySceneStreamFrame(NO_SCENE_STREAM, checkpoint({ version: 5, operations: 40 }));
  state = applySceneStreamFrame(state, checkpoint({ version: 7, operations: 96 }));
  const beforeSeed = state.actions.length;

  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 5,
    turnId: null,
  });
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    turnId: null,
    position: 40,
    dirty: false,
  });
  const logged = state.actions.at(-1);
  assert.equal(state.actions.length, beforeSeed + 1);
  assert.deepEqual(logged?.action, { action: "seed", position: 40, dirty: false });
  assert.equal(logged?.documentId, DOC);
  assert.equal(logged?.sequence, state.actions.at(-2)!.sequence + 1);
});

test("the seed re-seats a cursor the stream had already carried past the loaded version", () => {
  // THE CORRUPTION THIS CLOSES. The backlog anchored the cursor at the run's
  // latest checkpoint (position 96), but the canvas loaded version 5 — which
  // holds only 40 operations. Without the seed the next contiguous frame would
  // apply over the 56 operations the canvas does not have.
  let state = applySceneStreamFrame(NO_SCENE_STREAM, checkpoint({ version: 5, operations: 40 }));
  state = applySceneStreamFrame(state, checkpoint({ version: 7, operations: 96 }));
  assert.equal(state.cursors.get(DOC)?.position, 96);

  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 5,
    turnId: null,
  });
  const next = applySceneStreamFrame(
    state,
    opBatch({ operations: [op("a"), op("b")], operationsTotal: 98 }),
  );
  assert.equal(next.actions.at(-1)?.action.action, "dirty");
  assert.equal(
    next.cursors.get(DOC)?.dirty,
    true,
    "a frame beyond the loaded version may not be applied over the hole",
  );
});

test("the seed leaves every other document's cursor alone", () => {
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ documentId: OTHER, operations: [op("a")], operationsTotal: 1 }),
  );
  state = applySceneStreamFrame(state, checkpoint({ version: 5, operations: 40 }));
  const other = state.cursors.get(OTHER);
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 5,
    turnId: null,
  });
  assert.equal(state.cursors.get(OTHER), other);
});

test("a mid-run reload is the same path: the second load re-seats to its own version", () => {
  // The tab reloaded while the run kept going. Nothing was persisted on the
  // client to make this work — the durable version the canvas loaded, and the
  // checkpoints the stream replays on re-attach, are the whole mechanism.
  let state = applySceneStreamFrame(NO_SCENE_STREAM, checkpoint({ version: 5, operations: 40 }));
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 5,
    turnId: null,
  });
  assert.equal(state.cursors.get(DOC)?.position, 40);

  state = applySceneStreamFrame(state, checkpoint({ version: 6, operations: 71 }));
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 6,
    turnId: null,
  });
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    turnId: null,
    position: 71,
    dirty: false,
  });
  // …and the frame that begins exactly there is live motion again.
  const next = applySceneStreamFrame(
    state,
    opBatch({ operations: [op("a")], operationsTotal: 72 }),
  );
  assert.equal(next.actions.at(-1)?.action.action, "apply");
});

/* ---------------------------------------------------------------------------
 * Per-RUN ledgers (task 10, fix round 1).
 *
 * `operations_total` counts a RUN's ledger, not a document's history. A
 * document outlives many runs, so a cursor that carried one turn's position
 * into the next measures the new run's frames against an origin that has
 * nothing to do with them — which is exactly what a live walk caught: a tab
 * open at v122 saw the PREVIOUS turn's replayed checkpoint (v121, 2
 * operations), seeded there, and then dropped the new run's first batch
 * (`operations_total` 1) as "already reflected". The reveal could never start.
 *
 * So the cursor is scoped to `(document, turn)`: a frame from another turn is a
 * new ledger whose base is the document as loaded, and the cursor resets to 0
 * before that frame's own rule runs.
 * ------------------------------------------------------------------------ */

const TURN_A = "turn-a";
const TURN_B = "turn-b";

test("a frame from a NEW turn resets the ledger, and its first batch applies", () => {
  // The live scenario, end to end: the previous run's checkpoint is replayed,
  // the canvas joins at a version that checkpoint does not describe, and the
  // NEW run's first batch must draw rather than be dropped as stale.
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    checkpoint({ turnId: TURN_A, version: 121, operations: 2 }),
  );
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 122,
    turnId: TURN_B,
  });
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    turnId: TURN_B,
    position: 0,
    dirty: false,
  });

  const next = applySceneStreamFrame(
    state,
    opBatch({ turnId: TURN_B, operations: [op("a")], operationsTotal: 1 }),
  );
  assert.deepEqual(next.actions.at(-1)?.action, {
    action: "apply",
    operations: [op("a")],
    operationsTotal: 1,
  });
  assert.deepEqual(next.cursors.get(DOC), {
    documentId: DOC,
    turnId: TURN_B,
    position: 1,
    dirty: false,
  });
});

test("a new turn's frame resets a cursor that was carried far past it", () => {
  const carried = {
    documentId: DOC,
    turnId: TURN_A,
    position: 96,
    dirty: true,
  };
  const { cursor, action } = advanceSceneStreamCursor(
    carried,
    opBatch({ turnId: TURN_B, operations: [op("a"), op("b")], operationsTotal: 2 }),
  );
  assert.equal(action.action, "apply");
  assert.deepEqual(cursor, {
    documentId: DOC,
    turnId: TURN_B,
    position: 2,
    dirty: false,
  });
});

test("the fold announces the turn change before the frame's own action", () => {
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ turnId: TURN_A, operations: [op("a")], operationsTotal: 1 }),
  );
  state = applySceneStreamFrame(
    state,
    opBatch({ turnId: TURN_B, operations: [op("b")], operationsTotal: 1 }),
  );
  assert.deepEqual(
    state.actions.map((entry) => entry.action.action),
    ["rebase", "apply", "rebase", "apply"],
  );
  assert.deepEqual(state.actions.at(-2)?.action, {
    action: "rebase",
    turnId: TURN_B,
  });
});

test("a same-turn frame never rebases — the matrix is untouched", () => {
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ turnId: TURN_A, operations: [op("a")], operationsTotal: 1 }),
  );
  state = applySceneStreamFrame(
    state,
    opBatch({ turnId: TURN_A, operations: [op("b")], operationsTotal: 2 }),
  );
  assert.deepEqual(
    state.actions.map((entry) => entry.action.action),
    ["rebase", "apply", "apply"],
  );
});

test("the seed reads only the in-flight turn's marks", () => {
  // The live case: the backlog holds only the PREVIOUS turn's checkpoint. It
  // says nothing about where the run now in flight stands, so it is ignored and
  // the new run's ledger starts at 0 on the document as loaded.
  const cursor = seedSceneStreamCursor({
    documentId: DOC,
    documentVersion: 122,
    turnId: TURN_B,
    backlogCheckpoints: [
      { documentId: DOC, turnId: TURN_A, version: 121, operations: 2 },
      { documentId: DOC, turnId: TURN_A, version: 122, operations: 9 },
    ],
  });
  assert.deepEqual(cursor, {
    documentId: DOC,
    turnId: TURN_B,
    position: 0,
    dirty: false,
  });
});

test("within the in-flight turn the exact-version rule still stands", () => {
  const marks = [
    { documentId: DOC, turnId: TURN_A, version: 130, operations: 999 },
    { documentId: DOC, turnId: TURN_B, version: 128, operations: 40 },
    { documentId: DOC, turnId: TURN_B, version: 130, operations: 96 },
  ];
  assert.deepEqual(
    seedSceneStreamCursor({
      documentId: DOC,
      documentVersion: 130,
      turnId: TURN_B,
      backlogCheckpoints: marks,
    }),
    { documentId: DOC, turnId: TURN_B, position: 96, dirty: false },
  );
  // A version this turn has marks for but did not commit: still dirty, and the
  // highest position it knows is this TURN's, never another's.
  assert.deepEqual(
    seedSceneStreamCursor({
      documentId: DOC,
      documentVersion: 129,
      turnId: TURN_B,
      backlogCheckpoints: marks,
    }),
    { documentId: DOC, turnId: TURN_B, position: 96, dirty: true },
  );
});

/* ---------------------------------------------------------------------------
 * The join replay (task 10, fix round 2).
 *
 * A mid-run reload loses the race the other way round: the stream re-attaches
 * and replays the run's op frames SECONDS before the document finishes loading.
 * Those frames are folded into the log while no canvas is there to draw them,
 * and a join that seeks past the log to start live throws them away — the tab
 * then shows the committed base until the next checkpoint reloads it, which is
 * exactly the wait rung B exists to remove.
 *
 * So a join replays its own turn's logged applies through the SEEDED position,
 * with the same contiguity arithmetic every live frame goes through.
 * ------------------------------------------------------------------------ */

function loggedApply(
  sequence: number,
  operations: readonly ReturnType<typeof op>[],
  operationsTotal: number,
  documentId = DOC,
): SceneStreamActionRecord {
  return {
    sequence,
    documentId,
    action: { action: "apply", operations: operations as never, operationsTotal },
  };
}

function loggedRebase(
  sequence: number,
  turnId: string | null,
  documentId = DOC,
): SceneStreamActionRecord {
  return { sequence, documentId, action: { action: "rebase", turnId } };
}

test("a join replays the in-flight turn's backlog through the seeded position", () => {
  // THE LIVE DEFECT. The reload's SSE re-attach replayed turn B's first batch
  // before the document had loaded; the canvas showed the base and never drew
  // it. Now the seed replays it.
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ turnId: TURN_B, operations: [op("a")], operationsTotal: 1 }),
  );
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 123,
    turnId: TURN_B,
  });
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    turnId: TURN_B,
    position: 1,
    dirty: false,
  });
  assert.deepEqual(state.actions.at(-2)?.action, {
    action: "seed",
    position: 1,
    dirty: false,
  });
  assert.deepEqual(state.actions.at(-1)?.action, {
    action: "apply",
    operations: [op("a")],
    operationsTotal: 1,
  });
});

test("a reload AT a checkpoint replays nothing — the document already holds it", () => {
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ turnId: TURN_B, operations: [op("a")], operationsTotal: 1 }),
  );
  state = applySceneStreamFrame(
    state,
    opBatch({ turnId: TURN_B, operations: [op("b")], operationsTotal: 2 }),
  );
  state = applySceneStreamFrame(
    state,
    checkpoint({ turnId: TURN_B, version: 123, operations: 2 }),
  );
  const beforeJoin = state.actions.length;

  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 123,
    turnId: TURN_B,
  });
  // Both logged applies are already in the loaded document: dropped, not drawn.
  assert.equal(state.actions.length, beforeJoin + 1, "the seed, and nothing else");
  assert.deepEqual(state.actions.at(-1)?.action, {
    action: "seed",
    position: 2,
    dirty: false,
  });

  // …and the next live batch continues from there.
  const next = applySceneStreamFrame(
    state,
    opBatch({ turnId: TURN_B, operations: [op("c")], operationsTotal: 3 }),
  );
  assert.equal(next.actions.at(-1)?.action.action, "apply");
});

test("the replay is pure arithmetic over the log — contiguous batches, in order", () => {
  const replay = replaySceneStreamJoin({
    actions: [
      loggedRebase(1, TURN_A),
      loggedApply(2, [op("old")], 40),
      loggedRebase(3, TURN_B),
      loggedApply(4, [op("a")], 1),
      loggedApply(5, [op("b"), op("c")], 3),
      loggedApply(6, [op("x")], 9, OTHER),
    ],
    documentId: DOC,
    turnId: TURN_B,
    position: 0,
  });
  assert.deepEqual(replay, {
    operations: [op("a"), op("b"), op("c")],
    position: 3,
    dirty: false,
  });
});

test("the replay drops what the loaded document already holds", () => {
  const replay = replaySceneStreamJoin({
    actions: [
      loggedRebase(1, TURN_B),
      loggedApply(2, [op("a")], 1),
      loggedApply(3, [op("b")], 2),
      loggedApply(4, [op("c")], 3),
    ],
    documentId: DOC,
    turnId: TURN_B,
    position: 2,
  });
  assert.deepEqual(replay, {
    operations: [op("c")],
    position: 3,
    dirty: false,
  });
});

test("a gap in the replayed applies goes dirty, keeping the contiguous prefix", () => {
  const replay = replaySceneStreamJoin({
    actions: [
      loggedRebase(1, TURN_B),
      loggedApply(2, [op("a")], 1),
      loggedApply(3, [op("z")], 5),
    ],
    documentId: DOC,
    turnId: TURN_B,
    position: 0,
  });
  assert.deepEqual(replay, {
    operations: [op("a")],
    position: 5,
    dirty: true,
  });
});

test("an EVICTED turn start is a gap — the replay refuses rather than guesses", () => {
  const replay = replaySceneStreamJoin({
    // The log has been trimmed (it no longer starts at sequence 1), so the
    // turn's own start may be among the entries that were evicted.
    actions: [loggedApply(70, [op("a")], 12)],
    documentId: DOC,
    turnId: TURN_B,
    position: 0,
  });
  assert.deepEqual(replay, { operations: [], position: 0, dirty: true });
});

test("a turn that has streamed nothing yet replays nothing and stays clean", () => {
  // The tab-open-at-run-start path: the join happens BEFORE the run's first
  // frame, and an untrimmed log proves nothing was lost. Live frames then draw
  // themselves in as usual.
  const replay = replaySceneStreamJoin({
    actions: [loggedRebase(1, TURN_A), loggedApply(2, [op("old")], 40)],
    documentId: DOC,
    turnId: TURN_B,
    position: 0,
  });
  assert.deepEqual(replay, { operations: [], position: 0, dirty: false });
});

test("a join into a turn the log has already moved past goes dirty", () => {
  const replay = replaySceneStreamJoin({
    actions: [
      loggedRebase(1, TURN_B),
      loggedApply(2, [op("a")], 1),
      // A newer run began after the one the seed believes is in flight.
      loggedRebase(3, "turn-c"),
      loggedApply(4, [op("c")], 1),
    ],
    documentId: DOC,
    turnId: TURN_B,
    position: 0,
  });
  assert.deepEqual(replay.dirty, true);
});

test("a DIRTY seed replays nothing at all", () => {
  // Nothing may be applied over an unknown position, and the join is no
  // exception to that.
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ turnId: TURN_B, operations: [op("a")], operationsTotal: 1 }),
  );
  state = applySceneStreamFrame(
    state,
    checkpoint({ turnId: TURN_B, version: 120, operations: 1 }),
  );
  const beforeJoin = state.actions.length;
  // v123 is not the version that mark committed: the position is unknown.
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 123,
    turnId: TURN_B,
  });
  assert.equal(state.actions.length, beforeJoin + 1);
  assert.deepEqual(state.actions.at(-1)?.action, {
    action: "seed",
    position: 1,
    dirty: true,
  });
});

/* ---------------------------------------------------------------------------
 * The live sequence (task 10, fix round 3).
 *
 * Taken frame-for-frame from `agent_turn_event_stream` for turn
 * `7addaeaf-75ee-514d-b474-0dd3e42cd312` (Apollo document
 * `doc_1c35a98d45435c7bb8d19408bb9e03e8`), the run a controller walk found
 * reloading the canvas at a checkpoint it should have suppressed:
 *
 *   turn.accepted, turn.started, design.op_batch{operations_total: 1},
 *   design.checkpoint{version: 126, operations: 1}
 *
 * with a page reload between the op batch and the checkpoint, and the document
 * loading at version 125. Both design frames carry the SAME `turn_id` and the
 * SAME `document_id` (verified in the database), and the two ledger numbers
 * agree — so the anchor MUST come out in sync.
 * ------------------------------------------------------------------------ */

const LIVE_TURN = "7addaeaf-75ee-514d-b474-0dd3e42cd312";

test("the live late-join sequence anchors IN SYNC — the checkpoint must not reload", () => {
  // (i) the run's op batch replays over SSE before the document has loaded.
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ turnId: LIVE_TURN, operations: [op("cta")], operationsTotal: 1 }),
  );
  // (ii) the document finishes loading at v125 — no checkpoint of this run's yet.
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 125,
    turnId: LIVE_TURN,
  });
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    turnId: LIVE_TURN,
    position: 1,
    dirty: false,
  });
  // (iii) the checkpoint that committed v126 — one operation, the one streamed.
  const next = applySceneStreamFrame(
    state,
    checkpoint({ turnId: LIVE_TURN, version: 126, operations: 1 }),
  );
  assert.deepEqual(next.actions.at(-1)?.action, {
    action: "anchor",
    version: 126,
    inSync: true,
  });
});

test("a seed that cannot name the run keeps the run the STREAM named", () => {
  // THE DEFECT. `runningTurn` is null for the renders between a replayed
  // `turn.accepted` (which maps to "queued") and the `turn.started` behind it,
  // and a document that finishes loading in that window used to seed with no
  // turn at all — which reset a cursor the stream had already carried to 1 back
  // to `{turn: null, position: 0}`. The next checkpoint then read as a NEW run
  // (rebase) standing at a position the canvas had never reached, so it
  // reloaded: rung A's flicker, at every checkpoint, for the rest of the run.
  let state = applySceneStreamFrame(
    NO_SCENE_STREAM,
    opBatch({ turnId: LIVE_TURN, operations: [op("cta")], operationsTotal: 1 }),
  );
  state = seedSceneStreamState(state, {
    documentId: DOC,
    documentVersion: 125,
    turnId: null,
  });
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    turnId: LIVE_TURN,
    position: 1,
    dirty: false,
  });
  const next = applySceneStreamFrame(
    state,
    checkpoint({ turnId: LIVE_TURN, version: 126, operations: 1 }),
  );
  assert.deepEqual(next.actions.at(-1)?.action, {
    action: "anchor",
    version: 126,
    inSync: true,
  });
});

test("a turn-less seed onto a document nothing has streamed still starts at 0", () => {
  const state = seedSceneStreamState(NO_SCENE_STREAM, {
    documentId: DOC,
    documentVersion: 125,
    turnId: null,
  });
  assert.deepEqual(state.cursors.get(DOC), {
    documentId: DOC,
    turnId: null,
    position: 0,
    dirty: false,
  });
});
