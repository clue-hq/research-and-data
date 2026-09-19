import assert from "node:assert/strict";
import test, { mock } from "node:test";
import type { SceneStreamActionRecord } from "../adapter/scene-stream-cursor";
import { replaySceneStreamJoin } from "../adapter/scene-stream-cursor";
import type { Operation, Scene } from "../engine/scene/contracts";
import type { EngineApplyOutcome } from "../engine/scene/wasmEngine";
import {
  ADD_PAGE_DRAW_MS,
  DRAW_MAX_MS,
  DRAW_MIN_MS,
  INTER_STEP_PAUSE_MS,
  MATERIALIZE_FADE_MS,
  MAX_BATCH_REVEAL_MS,
  MIN_STEP_TOTAL_MS,
  REDUCED_MOTION_STEP_MS,
  SceneRevealPump,
  TRAVEL_MS,
  consumeSceneStreamActions,
} from "./use-scene-live-reveal";

/**
 * The live-reveal pump (scene live-streaming rung B, task 9).
 *
 * The MVP editor's `useAgentTurn.ts` §S2.1 cases, re-expressed against the
 * platform pump: the engine runs AHEAD of the display and the visible swap is
 * HELD until the travel+draw clock elapses, a batch landing mid-draw reconciles
 * cumulatively instead of crawling through a backlog, a fast-forward snaps, an
 * engine refusal shows nothing and latches until the next anchor, and an unlock
 * hands the canvas back to the document.
 *
 * Everything here runs on node:test's fake clock; nothing waits on real time.
 * `steppedClock` is the house pattern from task 3's throttle test — a coarse
 * `tick` runs callbacks at the END of the window, which would let a hold that
 * fired late still look on time.
 */

/** Run `body` with the timers faked, and always give the clock back. */
function onFakeClock(body: () => void): void {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    body();
  } finally {
    mock.timers.reset();
  }
}

function steppedClock() {
  return {
    advance(ms: number) {
      for (let step = 0; step < ms; step += 1) mock.timers.tick(1);
    },
  };
}

/* ---------------------------------------------------------------------------
 * Fixtures. A 1000×1000 page and zero-area boxes, so every ported timing lands
 * on an exact integer: `drawMsForReveal` scales with the box diagonal as a
 * fraction of the page's, and a zero box is exactly DRAW_MIN_MS.
 * ------------------------------------------------------------------------ */

const PAGE_ID = "page_1";

function baseScene(): Scene {
  return {
    schema_version: 1,
    meta: {
      id: "doc_1",
      title: "Ad",
      artifact_type: null,
      medium: "digital",
      brand_kit: null,
      status: { kind: "draft" },
    },
    pages: {
      [PAGE_ID]: {
        id: PAGE_ID,
        name: "Page",
        size: {
          width: 1000,
          height: 1000,
          unit: "px",
          preset: null,
          orientation: "portrait",
        },
        children: [],
        bleed: null,
        safe_area: null,
        background: [],
      },
    },
    nodes: {},
    slots: {},
    assets: {},
    export_profiles: [],
  } as unknown as Scene;
}

function insertNode(nodeId: string): Operation {
  return {
    kind: "insert_node",
    parent: { kind: "page", id: PAGE_ID },
    index: 0,
    node: { id: nodeId },
  } as unknown as Operation;
}

function addPage(pageId: string): Operation {
  return {
    kind: "add_page",
    page: { id: pageId, name: pageId },
  } as unknown as Operation;
}

function updateNode(nodeId: string): Operation {
  return {
    kind: "update_node",
    node_id: nodeId,
    patch: {},
  } as unknown as Operation;
}

/**
 * A stand-in for the canvas's engine seam: it folds `insert_node` into the
 * scene with a zero-area computed box (so the timing is exact) and records
 * every batch it was handed.
 */
function fakeEngine() {
  let scene = baseScene();
  const batches: Operation[][] = [];
  let refuse: "no" | "reject" | "throw" = "no";
  return {
    batches,
    refuseWith(mode: "no" | "reject" | "throw") {
      refuse = mode;
    },
    scene: () => scene,
    apply(operations: Operation[]): EngineApplyOutcome | null {
      batches.push(operations);
      if (refuse === "throw") throw new Error("engine exploded");
      if (refuse === "reject") {
        return {
          accepted: false,
          scene,
          diagnostics: [],
          inverseOperations: null,
          appliedOperations: 0,
        };
      }
      const nodes = { ...scene.nodes } as Record<string, unknown>;
      const pages = { ...scene.pages } as Record<string, unknown>;
      for (const operation of operations) {
        const op = operation as unknown as Record<string, never>;
        const kind = (op as unknown as { kind: string }).kind;
        if (kind === "insert_node") {
          const id = (op as unknown as { node: { id: string } }).node.id;
          nodes[id] = {
            id,
            name: id,
            kind: { kind: "text" },
            computed: { layout_bounds: { x: 0, y: 0, width: 0, height: 0 } },
          };
        } else if (kind === "add_page") {
          const page = (op as unknown as { page: { id: string } }).page;
          pages[page.id] = { ...page, children: [] };
        }
      }
      scene = { ...scene, nodes, pages } as unknown as Scene;
      return {
        accepted: true,
        scene,
        diagnostics: [],
        inverseOperations: null,
        appliedOperations: operations.length,
      };
    },
  };
}

function harness(reducedMotion = false) {
  const engine = fakeEngine();
  const displays: (Scene | null)[] = [];
  const available = { value: true };
  const pump = new SceneRevealPump({
    apply: (operations) => engine.apply(operations),
    engineAvailable: () => available.value,
    engineIdentity: () => engine,
    onDisplayScene: (scene) => displays.push(scene),
    reducedMotion,
  });
  pump.start();
  return { available, engine, displays, pump };
}

/** The lead before the first step, and the hold before its content lands. */
const FIRST_LEAD = INTER_STEP_PAUSE_MS; // 120
const NODE_HOLD = TRAVEL_MS + DRAW_MIN_MS; // 200 + 250

/* ------------------------------------------------------------------------ */

test("the ported timings are the MVP editor's own numbers", () => {
  assert.equal(TRAVEL_MS, 200);
  assert.equal(DRAW_MIN_MS, 250);
  assert.equal(DRAW_MAX_MS, 500);
  assert.equal(ADD_PAGE_DRAW_MS, 300);
  assert.equal(MATERIALIZE_FADE_MS, 250);
  assert.equal(INTER_STEP_PAUSE_MS, 120);
  assert.equal(MAX_BATCH_REVEAL_MS, 15000);
  assert.equal(MIN_STEP_TOTAL_MS, 250);
  assert.equal(REDUCED_MOTION_STEP_MS, 80);
});

test("a node batch reaches the engine immediately and the display swaps at travel+draw", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    pump.enqueue([insertNode("n1")]);
    // Nothing has run yet: the first step begins after one inter-step pause,
    // exactly as the MVP's `enqueueStreamedBatch` schedules it.
    assert.equal(engine.batches.length, 0);

    clock.advance(FIRST_LEAD);
    // ENGINE-AHEAD: the operations are in the engine…
    assert.equal(engine.batches.length, 1);
    // …and the display has NOT moved. This is the S2.1 inversion.
    assert.equal(displays.length, 0);

    clock.advance(NODE_HOLD - 1);
    assert.equal(displays.length, 0, "the content must not land before the box does");

    clock.advance(1);
    assert.equal(displays.length, 1);
    assert.ok(displays[0] && "n1" in displays[0].nodes);

    pump.stop();
  });
});

test("an add_page materializes at once — the empty artboard IS the placeholder", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { displays, pump } = harness();

    pump.enqueue([addPage("page_2")]);
    clock.advance(FIRST_LEAD);
    // No hold: the MVP holds NODE content only, because a held page has no
    // artboard for its own chrome to anchor to.
    assert.equal(displays.length, 1);
    assert.ok(displays[0] && "page_2" in displays[0].pages);

    pump.stop();
  });
});

test("a batch landing mid-draw drains the backlog in ONE cumulative apply", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    pump.enqueue([insertNode("n1"), insertNode("n2")]);
    clock.advance(FIRST_LEAD);
    assert.deepEqual(engine.batches.length, 1, "step 1 applied");
    assert.equal(displays.length, 0, "step 1 is still drawing");

    // Mid-draw: the second step is still queued behind the one in flight.
    clock.advance(100);
    pump.enqueue([insertNode("n3")]);

    // The backlog was drained as ONE apply and materialized immediately — no
    // visible catch-up crawl — and the held step's content rode along with it.
    assert.equal(engine.batches.length, 2);
    assert.deepEqual(engine.batches[1], [insertNode("n2")]);
    assert.equal(displays.length, 1);
    assert.ok(displays[0] && "n1" in displays[0].nodes && "n2" in displays[0].nodes);

    // …and the NEW batch then paces normally from its own lead.
    clock.advance(FIRST_LEAD);
    assert.equal(engine.batches.length, 3);
    assert.deepEqual(engine.batches[2], [insertNode("n3")]);

    pump.stop();
  });
});

test("non-visual operations ride WITH the next visual step, never on a dead beat", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    pump.enqueue([updateNode("n0"), insertNode("n1")]);
    clock.advance(FIRST_LEAD);
    assert.deepEqual(engine.batches, [[updateNode("n0"), insertNode("n1")]]);

    pump.stop();
  });
});

test("fastForward snaps: everything pending applies and shows at once", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    pump.enqueue([insertNode("n1"), insertNode("n2")]);
    clock.advance(FIRST_LEAD);
    assert.equal(displays.length, 0);

    pump.fastForward();
    assert.equal(engine.batches.length, 2);
    assert.equal(displays.length, 1, "one swap, not one per step");
    assert.ok(displays[0] && "n1" in displays[0].nodes && "n2" in displays[0].nodes);

    // Nothing is left on the clock.
    clock.advance(10_000);
    assert.equal(displays.length, 1);

    pump.stop();
  });
});

test("fastForward with nothing queued still lands the held content", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD);
    assert.equal(engine.batches.length, 1);
    assert.equal(displays.length, 0);

    pump.fastForward();
    assert.equal(engine.batches.length, 1, "nothing was re-applied");
    assert.equal(displays.length, 1, "the held scene was released");

    pump.stop();
  });
});

test("an engine refusal shows NOTHING and latches until the next anchor", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    engine.refuseWith("reject");
    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD + NODE_HOLD + 1000);
    assert.equal(displays.length, 0, "a refused batch is never hand-patched onto the canvas");
    assert.equal(pump.isDirty(), true);

    // The latch holds: later batches are not even offered to the engine.
    engine.refuseWith("no");
    pump.enqueue([insertNode("n2")]);
    clock.advance(10_000);
    assert.equal(engine.batches.length, 1);
    assert.equal(displays.length, 0);

    // The cursor anchors later, the reload repairs the display, and the pump
    // draws again from the reloaded base.
    pump.anchor(false);
    assert.equal(pump.isDirty(), false);
    assert.deepEqual([...displays], [null], "the canvas goes back to the document");

    pump.enqueue([insertNode("n3")]);
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(engine.batches.length, 2);
    assert.equal(displays.length, 2);

    pump.stop();
  });
});

test("a dirty pump is not clean, so its in-sync anchor is decided stale and re-seats", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    engine.refuseWith("reject");
    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD + 1);
    assert.equal(pump.isDirty(), true);
    assert.equal(pump.isClean(), false, "a latched pump is not clean");

    // The CURSOR never learns the engine refused, so it goes on reporting in
    // sync. `isClean()` is the other half of the composite decision — the same
    // fact the controller reads to decide the reload — and it says no, so this
    // anchor is a STALE one: the reload fires, the override drops, and the
    // latch clears because that reload re-seats the engine.
    engine.refuseWith("no");
    pump.anchor(true);
    assert.equal(pump.isDirty(), false, "the reload re-seats it");
    assert.deepEqual(displays.at(-1), null, "the reloaded document wins");

    pump.enqueue([insertNode("n2")]);
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(engine.batches.length, 2, "and the reveal resumes");

    pump.stop();
  });
});

test("a pump with no engine is never clean, so its anchors never suppress", () => {
  onFakeClock(() => {
    const { available, displays, pump } = harness();
    // D9 read-only: `applyStreamedOperations` returns null for every batch, so
    // this canvas can render nothing at all. Rung A's reload is the ONLY thing
    // keeping it current, and it must not be suppressed away.
    available.value = false;
    assert.equal(pump.isClean(), false);

    pump.anchor(true);
    assert.deepEqual(displays.at(-1), null);

    available.value = true;
    assert.equal(pump.isClean(), true);

    pump.stop();
  });
});

test("a stopped pump is never clean", () => {
  onFakeClock(() => {
    const { pump } = harness();
    assert.equal(pump.isClean(), true);
    pump.stop();
    assert.equal(pump.isClean(), false, "unknown-to-absent is never healthy");
  });
});

test("an engine that THROWS latches exactly like one that refuses", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    engine.refuseWith("throw");
    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD + 1);
    assert.equal(pump.isDirty(), true);
    assert.equal(displays.length, 0);

    pump.stop();
  });
});

test("an in-sync anchor keeps the drawn scene; a stale one hands the canvas back", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { displays, pump } = harness();

    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1);

    // inSync: the canvas provably already shows the checkpoint's version, so
    // the working scene is kept and nothing is emitted.
    pump.anchor(true);
    assert.equal(displays.length, 1, "an in-sync anchor must not flicker the canvas");

    // Stale: the reload's document becomes the new base, so the override drops
    // and the canvas renders the reloaded document.
    pump.anchor(false);
    assert.deepEqual(displays[1], null);

    pump.stop();
  });
});

test("stopping (the lock releasing) clears the override and the clock", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    pump.enqueue([insertNode("n1"), insertNode("n2")]);
    clock.advance(FIRST_LEAD);
    assert.equal(engine.batches.length, 1);

    pump.stop();
    assert.deepEqual(displays.at(-1), null, "the canvas returns to the document");

    const applied = engine.batches.length;
    clock.advance(10_000);
    assert.equal(engine.batches.length, applied, "no timer survived the stop");
    assert.equal(displays.filter((scene) => scene !== null).length, 0);
  });
});

test("a stopped pump ignores everything until it is started again", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();
    pump.stop();

    pump.enqueue([insertNode("n1")]);
    clock.advance(10_000);
    assert.equal(engine.batches.length, 0);
  });
});

test("reduced motion collapses the theater to one fast beat", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness(true);

    pump.enqueue([insertNode("n1")]);
    // No lead pause under reduced motion: the first step starts at once.
    clock.advance(0);
    mock.timers.tick(0);
    assert.equal(engine.batches.length, 1);
    clock.advance(REDUCED_MOTION_STEP_MS);
    assert.equal(displays.length, 1);

    pump.stop();
  });
});

/* ---------------------------------------------------------------------------
 * Resume by sequence. Several SSE frames commit in one React tick, so reading
 * only the LATEST action would coalesce applies away — the pump tracks the last
 * sequence it consumed and walks every newer entry in order.
 * ------------------------------------------------------------------------ */

/**
 * A logged apply, with the ledger position the fold stamps on it.
 *
 * The default keeps a RUNNING total across the calls a test makes, because that
 * is what `operations_total` is: where a batch ends in its run's ledger, never
 * its own length. The pump reads it to refuse a range it has already drawn
 * (fix round 3), so batches that all claimed to end at 1 would describe one
 * operation streamed over and over.
 */
let loggedLedger = 0;
function appliedBatch(
  operations: Operation[],
  operationsTotal?: number,
): SceneStreamActionRecord["action"] {
  loggedLedger += operations.length;
  return {
    action: "apply",
    operations,
    operationsTotal: operationsTotal ?? loggedLedger,
  };
}

function record(
  sequence: number,
  documentId: string,
  action: SceneStreamActionRecord["action"],
): SceneStreamActionRecord {
  return { sequence, documentId, action };
}

test("every action newer than the cursor is consumed, in order — never just the last", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    const log: SceneStreamActionRecord[] = [
      record(1, "doc_1", appliedBatch([insertNode("n1")])),
      record(2, "doc_1", appliedBatch([insertNode("n2")])),
      record(3, "doc_1", appliedBatch([insertNode("n3")])),
    ];
    const next = consumeSceneStreamActions(pump, log, "doc_1", 0);
    assert.equal(next, 3);

    // Three batches landed. The second and third fast-forwarded the first's
    // backlog (the MVP's own new-batch rule), so the engine saw all three.
    clock.advance(FIRST_LEAD * 4 + NODE_HOLD * 4);
    const seen = engine.batches.flat();
    assert.deepEqual(seen, [insertNode("n1"), insertNode("n2"), insertNode("n3")]);

    // Re-consuming the same log from the returned cursor does nothing.
    const applied = engine.batches.length;
    assert.equal(consumeSceneStreamActions(pump, log, "doc_1", next), 3);
    clock.advance(10_000);
    assert.equal(engine.batches.length, applied);

    pump.stop();
  });
});

test("actions naming another document advance the cursor but never touch the pump", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    const log: SceneStreamActionRecord[] = [
      record(1, "doc_other", appliedBatch([insertNode("x")])),
      record(2, "doc_1", appliedBatch([insertNode("n1")])),
    ];
    assert.equal(consumeSceneStreamActions(pump, log, "doc_1", 0), 2);
    clock.advance(FIRST_LEAD);
    assert.deepEqual(engine.batches, [[insertNode("n1")]]);

    pump.stop();
  });
});

test("an anchor in the log reaches the pump with its inSync verdict", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1);

    consumeSceneStreamActions(
      pump,
      [record(2, "doc_1", { action: "anchor", version: 7, inSync: true })],
      "doc_1",
      1,
    );
    assert.equal(displays.length, 1, "in-sync: nothing changes");

    consumeSceneStreamActions(
      pump,
      [record(3, "doc_1", { action: "anchor", version: 8, inSync: false })],
      "doc_1",
      2,
    );
    assert.deepEqual(displays.at(-1), null, "stale: the reload's document wins");

    pump.stop();
  });
});

test("a cursor `dirty` action leaves the drawn scene alone — it is a waiting room", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1);

    consumeSceneStreamActions(
      pump,
      [record(2, "doc_1", { action: "dirty" })],
      "doc_1",
      1,
    );
    assert.equal(displays.length, 1);
    assert.equal(pump.isDirty(), false, "the CURSOR is dirty, not the engine");

    pump.stop();
  });
});

/* ---------------------------------------------------------------------------
 * Late join (task 10) — the seed action, and the backlog it fast-forwards.
 *
 * Someone who opens (or reloads) a tab onto a document whose run is in flight
 * wants to SEE where the design is, not to watch five minutes of it re-drawn
 * from the beginning. The cursor's seed says WHERE the loaded document stands
 * in the ledger; this is what the pump does with the frames beyond it.
 * ------------------------------------------------------------------------ */

function seed(sequence: number, documentId: string, position: number): SceneStreamActionRecord {
  return record(sequence, documentId, { action: "seed", position, dirty: false });
}

test("a join fast-forwards the backlog that arrives with it — no animation", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [
        seed(1, "doc_1", 40),
        record(2, "doc_1", appliedBatch([insertNode("n1")])),
        record(3, "doc_1", appliedBatch([insertNode("n2")])),
      ],
      "doc_1",
      0,
    );
    // Before ANY clock has run: both batches are in the engine and on screen.
    assert.deepEqual(engine.batches.flat(), [insertNode("n1"), insertNode("n2")]);
    const shown = displays.at(-1);
    assert.ok(shown && "n1" in shown.nodes && "n2" in shown.nodes);

    // And nothing is left on the clock — the join spent the whole backlog.
    const settled = displays.length;
    clock.advance(10_000);
    assert.equal(displays.length, settled);

    pump.stop();
  });
});

test("what arrives AFTER the join's own pass is live, and draws itself in", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    // A join with nothing to catch up on — the tab-open-at-run-start path. The
    // join hands the canvas back to the document it loaded (one null) and is
    // spent in that same pass, because fix round 2 delivers a join's backlog
    // WITH it rather than a tick or two behind it.
    consumeSceneStreamActions(pump, [seed(1, "doc_1", 40)], "doc_1", 0);
    assert.equal(engine.batches.length, 0);
    assert.equal(displays.length, 1);
    assert.equal(displays.at(-1), null, "the join hands the canvas back first");

    // The run's first batch is LIVE, and a live batch is a reveal, not a snap.
    consumeSceneStreamActions(
      pump,
      [record(2, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      1,
    );
    assert.equal(displays.length, 1, "held back on the clock, not shown at once");
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 2);
    assert.ok(displays.at(-1)?.nodes.n1);

    // …and so is the one behind it.
    consumeSceneStreamActions(
      pump,
      [record(3, "doc_1", appliedBatch([insertNode("n2")]))],
      "doc_1",
      2,
    );
    assert.equal(displays.length, 2, "a live batch is paced, not snapped");
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 3);
    assert.ok(displays.at(-1)?.nodes.n2);

    pump.stop();
  });
});

test("a join hands the canvas back to the document it just loaded", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1);

    // A reload landed a fresh document under the pump: whatever it was holding
    // is a picture of a different base.
    consumeSceneStreamActions(pump, [seed(2, "doc_1", 96)], "doc_1", 1);
    assert.equal(displays.at(-1), null);

    pump.stop();
  });
});

test("a join clears the engine-refusal latch — the reloaded document is the new base", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    engine.refuseWith("reject");
    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD);
    assert.equal(pump.isDirty(), true);

    engine.refuseWith("no");
    consumeSceneStreamActions(pump, [seed(1, "doc_1", 96)], "doc_1", 0);
    assert.equal(pump.isDirty(), false);

    consumeSceneStreamActions(
      pump,
      [record(2, "doc_1", appliedBatch([insertNode("n2")]))],
      "doc_1",
      1,
    );
    // Live again: the batch is paced, so it reaches the engine on the clock.
    clock.advance(FIRST_LEAD);
    assert.deepEqual(engine.batches.at(-1), [insertNode("n2")]);

    pump.stop();
  });
});

test("a join naming another document never touches this pump", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1);

    consumeSceneStreamActions(pump, [seed(2, "doc_other", 40)], "doc_1", 1);
    assert.equal(displays.length, 1, "another document's join is not this canvas's");

    pump.stop();
  });
});

test("an eviction gap in the action log stops the pump until the next anchor", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1);

    // The log's oldest surviving entry is sequence 70: everything between 2 and
    // 69 was appended and evicted while this consumer was not looking, and any
    // of it could have been an apply. What survived is contiguous in the LEDGER
    // with what did not, which is precisely why it may not be applied here.
    consumeSceneStreamActions(
      pump,
      [record(70, "doc_1", appliedBatch([insertNode("n9")]))],
      "doc_1",
      1,
    );
    clock.advance(10_000);
    assert.equal(pump.isDirty(), true);
    assert.equal(displays.length, 1, "nothing lands on top of the hole");
    assert.equal(engine.batches.length, 1, "and nothing was even offered");

    // The anchor behind the gap is the recovery, exactly as it is for a refused
    // apply: stale, so the canvas reloads and the pump starts over from it.
    consumeSceneStreamActions(
      pump,
      [record(71, "doc_1", { action: "anchor", version: 9, inSync: false })],
      "doc_1",
      70,
    );
    assert.equal(pump.isDirty(), false);
    assert.equal(displays.at(-1), null);

    pump.stop();
  });
});

test("a jump in sequence WITHIN one log read is not a gap — other documents stream too", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [
        record(1, "doc_other", appliedBatch([insertNode("x")])),
        record(2, "doc_other", { action: "dirty" }),
        record(3, "doc_1", appliedBatch([insertNode("n1")])),
      ],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD);
    assert.equal(pump.isDirty(), false);
    assert.deepEqual(engine.batches, [[insertNode("n1")]]);

    pump.stop();
  });
});

/* ---------------------------------------------------------------------------
 * Per-run ledgers (task 10, fix round 1) — the rebase.
 * ------------------------------------------------------------------------ */

test("a rebase re-seats the canvas on the document, and the new run's first batch draws in", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1, "the previous run drew this");

    // A frame from a NEW turn: what is on screen belongs to a run that is over,
    // and the new run's operations count from the DOCUMENT, so the override
    // drops before its first batch lands on top.
    consumeSceneStreamActions(
      pump,
      [
        record(2, "doc_1", { action: "rebase", turnId: "turn-b" }),
        record(3, "doc_1", appliedBatch([insertNode("n2")])),
      ],
      "doc_1",
      1,
    );
    assert.equal(displays.at(-1), null, "the loaded document is the new base");
    // LIVE, not backlog: the first batch of a fresh run is drawn in, not snapped.
    const beforeDraw = displays.length;
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, beforeDraw + 1);
    assert.ok(displays.at(-1)?.nodes.n2);
    assert.deepEqual(engine.batches.at(-1), [insertNode("n2")]);

    pump.stop();
  });
});

test("a rebase clears an engine-refusal latch — the new run starts from the document", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    engine.refuseWith("reject");
    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD);
    assert.equal(pump.isDirty(), true);

    engine.refuseWith("no");
    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", { action: "rebase", turnId: "turn-b" })],
      "doc_1",
      0,
    );
    assert.equal(pump.isDirty(), false);

    pump.stop();
  });
});

test("another document's rebase never re-seats this canvas", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { displays, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")]))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.length, 1);

    consumeSceneStreamActions(
      pump,
      [record(2, "doc_other", { action: "rebase", turnId: "turn-b" })],
      "doc_1",
      1,
    );
    assert.equal(displays.length, 1);

    pump.stop();
  });
});

/* ---------------------------------------------------------------------------
 * Never twice (task 10, fix round 3).
 * ------------------------------------------------------------------------ */

test("a remounted engine replays an asset registration before its next placement", () => {
  onFakeClock(() => {
    let engine = { assets: new Set<string>(), nodes: new Set(["checkpoint_node"]) };
    const assetId = "asset_after_checkpoint";
    const registration = { kind: "upsert_asset", asset: { id: assetId } } as Operation;
    const placement = { kind: "place_asset_in_node", node_id: "image", asset_id: assetId } as Operation;
    let refusals = 0;
    const pump = new SceneRevealPump({
      engineIdentity: () => engine,
      reducedMotion: true,
      onDisplayScene: () => {},
      apply: (operations) => {
        for (const operation of operations) {
          if (operation.kind === "insert_node") {
            if (engine.nodes.has(operation.node.id)) {
              refusals += 1;
              return null;
            }
            engine.nodes.add(operation.node.id);
          }
          if (operation.kind === "upsert_asset") engine.assets.add(operation.asset.id);
          if (operation.kind === "place_asset_in_node" && !engine.assets.has(operation.asset_id)) {
            refusals += 1;
            return null;
          }
        }
        return { accepted: true, scene: baseScene(), diagnostics: [], inverseOperations: null, appliedOperations: operations.length };
      },
    });
    pump.start();
    pump.enqueue([registration], 60);
    pump.fastForward();
    assert.ok(engine.assets.has(assetId));

    // Gallery -> artifact creates a new engine from the last checkpoint,
    // whose ledger position is 59. The chat-level pump survives that remount.
    engine = { assets: new Set<string>(), nodes: new Set(["checkpoint_node"]) };
    const replay = replaySceneStreamJoin({
      documentId: "doc_1", turnId: "turn_1", position: 59,
      actions: [
        record(1, "doc_1", { action: "rebase", turnId: "turn_1" }),
        record(2, "doc_1", appliedBatch([insertNode("checkpoint_node")], 59)),
        record(3, "doc_1", appliedBatch([registration], 60)),
      ],
    });
    assert.equal(replay.dirty, false);
    assert.deepEqual(replay.operations, [registration], "replay excludes the committed insert at position 59");
    consumeSceneStreamActions(pump, [
      record(1, "doc_1", { action: "seed", position: 59, dirty: false }),
      record(2, "doc_1", appliedBatch([...replay.operations], replay.position)),
    ], "doc_1", 0);
    pump.enqueue([placement], 61);
    pump.fastForward();
    assert.equal(refusals, 0, "the new engine must receive the replayed registration");
    assert.ok(engine.assets.has(assetId));
    assert.equal(pump.isDirty(), false);
    pump.stop();
  });
});

test("a join never re-applies a ledger range the pump has already drawn", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    // The backlog reached this pump LIVE — the lock and the open document are
    // both known before the document finishes loading, so the session was
    // already streaming when the replayed frames landed.
    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")], 1))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.deepEqual(engine.batches, [[insertNode("n1")]]);

    // …and only then did the document load, so the join replays the SAME ledger
    // range. Applying it again would put the operation into the engine twice —
    // for an insert, the engine refuses and the pump latches dirty, which makes
    // every checkpoint from then on reload a canvas that was perfectly in sync.
    consumeSceneStreamActions(
      pump,
      [
        record(2, "doc_1", { action: "seed", position: 0, dirty: false }),
        record(3, "doc_1", appliedBatch([insertNode("n1")], 1)),
      ],
      "doc_1",
      1,
    );
    assert.equal(engine.batches.length, 1, "the same range is applied once");
    assert.equal(pump.isDirty(), false);

    // The live batch behind it still lands, in full.
    consumeSceneStreamActions(
      pump,
      [record(4, "doc_1", appliedBatch([insertNode("n2")], 2))],
      "doc_1",
      3,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.deepEqual(engine.batches.at(-1), [insertNode("n2")]);

    pump.stop();
  });
});

test("a join applies only the TAIL of a range the pump is partway through", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")], 1))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);

    // The join's catch-up covers (0, 3] — the first operation of which the pump
    // already drew.
    consumeSceneStreamActions(
      pump,
      [
        record(2, "doc_1", { action: "seed", position: 0, dirty: false }),
        record(
          3,
          "doc_1",
          appliedBatch([insertNode("n1"), insertNode("n2"), insertNode("n3")], 3),
        ),
      ],
      "doc_1",
      1,
    );
    assert.deepEqual(engine.batches.at(-1), [insertNode("n2"), insertNode("n3")]);
    assert.equal(pump.isDirty(), false);

    pump.stop();
  });
});

test("a NEW run's ledger starts over — a rebase forgets what was applied", () => {
  onFakeClock(() => {
    const clock = steppedClock();
    const { engine, pump } = harness();

    consumeSceneStreamActions(
      pump,
      [record(1, "doc_1", appliedBatch([insertNode("n1")], 1))],
      "doc_1",
      0,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(engine.batches.length, 1);

    // Position 1 of the NEXT run is a different operation entirely, so the
    // already-applied bookkeeping cannot survive the run boundary.
    consumeSceneStreamActions(
      pump,
      [
        record(2, "doc_1", { action: "rebase", turnId: "turn-b" }),
        record(3, "doc_1", appliedBatch([insertNode("n9")], 1)),
      ],
      "doc_1",
      1,
    );
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.deepEqual(engine.batches.at(-1), [insertNode("n9")]);

    pump.stop();
  });
});

test("a queued reveal retains the presentation belonging to its own authored operation", () => {
  onFakeClock(() => {
    const engine = fakeEngine();
    const displays: (Scene | null)[] = [];
    let latest: Scene | null = null;
    const pump = new SceneRevealPump({
      apply: operations => {
        const result = engine.apply(operations)!;
        latest = { ...result.scene, meta:{ ...result.scene.meta, title:`effective-${engine.batches.length}` } };
        return { ...result, presentationScene:latest };
      }, engineAvailable:() => true, onDisplayScene: scene => displays.push(scene), reducedMotion:true,
    });
    pump.start(); pump.enqueue([insertNode("n1")]);
    const clock = steppedClock(); clock.advance(FIRST_LEAD + REDUCED_MOTION_STEP_MS + 1);
    const first = displays.filter(Boolean).at(-1)!;
    assert.equal(first.meta.title,"effective-1");
    pump.enqueue([insertNode("n2")]);
    clock.advance(FIRST_LEAD + REDUCED_MOTION_STEP_MS + 1);
    assert.equal(first.meta.title,"effective-1");
    assert.equal(displays.filter(Boolean).at(-1)!.meta.title,"effective-2");
    pump.stop();
  });
});

test("a non-ready reveal frame never resurfaces while the next ready frame is held", () => {
  onFakeClock(() => {
    const engine = fakeEngine();
    const displays: (Scene | null)[] = [];
    const statuses = ["ready", "invalid", "ready"] as const;
    const pump = new SceneRevealPump({
      apply: operations => {
        const result = engine.apply(operations)!;
        const revision = engine.batches.length;
        const presentationScene = {
          ...result.scene,
          meta: { ...result.scene.meta, title: `frame-${revision}` },
        };
        return {
          ...result,
          presentationScene,
          derivation: { context_key: "context", input_revision: revision,
            status: statuses[revision - 1], diagnostics: [] },
        };
      },
      engineAvailable: () => true,
      onDisplayScene: scene => displays.push(scene),
      reducedMotion: false,
    });
    const clock = steppedClock();
    pump.start();
    pump.enqueue([insertNode("n1")]);
    clock.advance(FIRST_LEAD + NODE_HOLD);
    assert.equal(displays.filter(Boolean).at(-1)!.meta.title, "frame-1");
    pump.enqueue([insertNode("n2")]);
    clock.advance(FIRST_LEAD + NODE_HOLD);
    // The accepted second operation is applied, but its invalid derivation
    // must never become an override that a newer engine status can unmask.
    assert.equal(engine.batches.length, 2);
    assert.equal(displays.filter(Boolean).at(-1)!.meta.title, "frame-1");
    pump.enqueue([insertNode("n3")]);
    clock.advance(FIRST_LEAD);
    assert.equal(engine.batches.length, 3);
    assert.equal(displays.filter(Boolean).at(-1)!.meta.title, "frame-1");
    clock.advance(NODE_HOLD - 1);
    assert.equal(displays.filter(Boolean).at(-1)!.meta.title, "frame-1");
    clock.advance(1);
    assert.equal(displays.filter(Boolean).at(-1)!.meta.title, "frame-3");
    assert.equal(displays.some(scene => scene?.meta.title === "frame-2"), false);
    assert.equal(pump.isClean(), true);
    pump.stop();
  });
});
