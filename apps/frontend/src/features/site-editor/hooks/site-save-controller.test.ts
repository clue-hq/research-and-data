import assert from "node:assert/strict";
import { test } from "node:test";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { SiteRepositoryError, type SiteRepository } from "../data/site.repository";
import {
  SITE_MOVED_ON_NOTE,
  SITE_VERSION_GONE,
  SiteSaveController,
  type SiteSaveState,
} from "./site-save-controller";

const LOCK = "The lock's own sentence.";

function site(heading: string): SiteDocument {
  return {
    id: "doc-1",
    title: "S",
    theme: {},
    pages: { "/": { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta", heading } }] } },
    shell: null,
    agent_sections: {},
  } as SiteDocument;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

function harness({ adopt = true } = {}) {
  const calls: { op: string; base: number; heading?: string; batchId?: string }[] = [];
  const pending: ReturnType<typeof deferred<{ version: number }>>[] = [];
  const next = () => {
    const result = deferred<{ version: number }>();
    pending.push(result);
    return result.promise;
  };
  const headingOf = (value: SiteDocument) =>
    String(value.pages["/"].content[0].props.heading);
  const repository: Pick<SiteRepository, "save" | "undo" | "redo" | "restore"> = {
    save: (_id, request) => {
      calls.push({ op: "save", base: request.baseVersion, heading: headingOf(request.site) });
      return next();
    },
    undo: (_id, base) => {
      calls.push({ op: "undo", base });
      return next();
    },
    redo: (_id, base) => {
      calls.push({ op: "redo", base });
      return next();
    },
    restore: (_id, batchId, base) => {
      calls.push({ op: "restore", base, batchId });
      return next();
    },
  };
  const states: SiteSaveState[] = [];
  let reloads = 0;
  const controller = new SiteSaveController({
    documentId: "doc-1",
    lockNote: LOCK,
    onReload: () => {
      reloads += 1;
    },
    onState: (state) => states.push(state),
    repository,
  });
  if (adopt) controller.adopt({ version: 5, undoDepth: 0, redoDepth: 0 });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  return { calls, controller, pending, reloads: () => reloads, settle, states };
}

test("one save in flight; later edits coalesce into one follow-up save of the newest site", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.save(site("b"));
  h.controller.save(site("c"));
  assert.deepEqual(h.calls, [{ op: "save", base: 5, heading: "a" }]);
  h.pending[0].resolve({ version: 6 });
  await h.settle();
  assert.deepEqual(h.calls.map((call) => [call.op, call.base, call.heading]), [
    ["save", 5, "a"],
    ["save", 6, "c"],
  ]);
  h.pending[1].resolve({ version: 7 });
  await h.settle();
  assert.equal(h.controller.snapshot.baseVersion, 7);
  assert.equal(h.controller.snapshot.undoDepth, 2);
  assert.equal(h.controller.snapshot.busy, false);
  assert.equal(h.reloads(), 0, "a successful save does not reload the canvas");
});

test("a base-version refusal says the document moved on, drops queued edits and reloads", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.save(site("b"));
  h.pending[0].reject(
    new SiteRepositoryError("moved", { code: "edits.base_version_mismatch", status: 409, currentVersion: 9 }),
  );
  await h.settle();
  assert.equal(h.controller.snapshot.note, SITE_MOVED_ON_NOTE);
  assert.equal(h.reloads(), 1);
  assert.equal(h.calls.length, 1, "the queued edit is dropped with the refused one");
});

test("a refusal because the agent is running carries the lock's own words", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.pending[0].reject(new SiteRepositoryError("busy", { code: "document.agent_run_active", status: 409 }));
  await h.settle();
  assert.equal(h.controller.snapshot.note, LOCK);
  assert.equal(h.reloads(), 1);
});

test("a validation refusal shows the first error and reloads the saved state", async () => {
  const h = harness();
  h.controller.save(site(""));
  h.pending[0].reject(
    new SiteRepositoryError("invalid", { code: "site.invalid", status: 422, errors: ["page.content.0(cta).heading: Too small"] }),
  );
  await h.settle();
  assert.equal(h.controller.snapshot.error, "page.content.0(cta).heading: Too small");
  assert.equal(h.controller.snapshot.note, null);
  assert.equal(h.reloads(), 1);
});

test("a transport failure keeps the edit for the next save and does not reload", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.pending[0].reject(new TypeError("Failed to fetch"));
  await h.settle();
  assert.equal(h.controller.snapshot.error, "Failed to fetch");
  assert.equal(h.reloads(), 0);
  h.controller.save(site("b"));
  assert.deepEqual(h.calls.at(-1), { op: "save", base: 5, heading: "b" });
});

test("undo waits behind an in-flight save, then steps the server stack and reloads", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.undo();
  assert.deepEqual(h.calls.map((call) => call.op), ["save"]);
  h.pending[0].resolve({ version: 6 });
  await h.settle();
  assert.deepEqual(h.calls.map((call) => [call.op, call.base]), [
    ["save", 5],
    ["undo", 6],
  ]);
  h.pending[1].resolve({ version: 7 });
  await h.settle();
  assert.equal(h.reloads(), 1);
  assert.equal(h.controller.snapshot.undoDepth, 0);
  assert.equal(h.controller.snapshot.redoDepth, 1);
});

test("an empty stack resyncs quietly", async () => {
  const h = harness();
  h.controller.undo();
  h.pending[0].reject(new SiteRepositoryError("empty", { code: "undo.empty", status: 409 }));
  await h.settle();
  assert.equal(h.reloads(), 1);
  assert.equal(h.controller.snapshot.note, null);
  assert.equal(h.controller.snapshot.error, null);
});

test("restoring a version that is gone says so and reloads", async () => {
  const h = harness();
  h.controller.restore("batch_9");
  assert.deepEqual(h.calls, [{ op: "restore", base: 5, batchId: "batch_9" }]);
  h.pending[0].reject(new SiteRepositoryError("gone", { code: "version.not_found", status: 404 }));
  await h.settle();
  assert.equal(h.controller.snapshot.error, SITE_VERSION_GONE);
  assert.equal(h.reloads(), 1);
});

test("nothing is sent before a document version is adopted", () => {
  const h = harness({ adopt: false });
  h.controller.save(site("a"));
  h.controller.undo();
  assert.deepEqual(h.calls, []);
});

// Review finding S2b-4: one queue, in the order asked. Only back-to-back saves merge.
test("two undos asked during a save both run, after it, in order", async () => {
  const h = harness();
  h.controller.save(site("First"));
  h.controller.undo();
  h.controller.undo();
  for (let i = 0; i < 3; i += 1) {
    h.pending[i].resolve({ version: 6 + i });
    await h.settle();
  }
  assert.deepEqual(h.calls.map((call) => [call.op, call.base]), [
    ["save", 5],
    ["undo", 6],
    ["undo", 7],
  ]);
});

test("an undo asked before a later edit runs first, and the edit built on the pre-undo copy is dropped", async () => {
  const h = harness();
  h.controller.save(site("Typo heading"));
  h.controller.undo();
  h.controller.save(site("Typo heading, more"));
  for (let i = 0; i < 2; i += 1) {
    h.pending[i].resolve({ version: 6 + i });
    await h.settle();
  }
  assert.deepEqual(h.calls.map((call) => `${call.op}${call.heading ? ` ${call.heading}` : ""}`), ["save Typo heading", "undo"]);
  assert.equal(h.controller.isIdle(), true);
  assert.equal(h.reloads(), 1, "the undo's own reload pushes the stepped copy to the canvas");
});

test("saves queued behind a step never run after it; a step queued behind it still does", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.save(site("b"));
  h.controller.redo();
  h.controller.save(site("c"));
  h.controller.undo();
  h.controller.save(site("d"));
  for (let i = 0; i < 4; i += 1) {
    h.pending[i]?.resolve({ version: 6 + i });
    await h.settle();
  }
  assert.deepEqual(h.calls.map((call) => `${call.op}${call.heading ? ` ${call.heading}` : ""}`), ["save a", "save b", "redo", "undo"]);
});

test("a reload requested while busy fires once the queue drains; when idle it fires at once", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.save(site("b"));
  assert.equal(h.controller.isIdle(), false);
  h.controller.requestReloadWhenIdle();
  h.pending[0].resolve({ version: 6 });
  await h.settle();
  assert.equal(h.reloads(), 0, "still busy with the queued save");
  h.pending[1].resolve({ version: 7 });
  await h.settle();
  assert.equal(h.controller.isIdle(), true);
  assert.equal(h.reloads(), 1);
  h.controller.requestReloadWhenIdle();
  assert.equal(h.reloads(), 2);
});

test("a refusal reloads once and satisfies a deferred reload", async () => {
  const h = harness();
  h.controller.save(site("a"));
  h.controller.requestReloadWhenIdle();
  h.pending[0].reject(new SiteRepositoryError("moved", { code: "edits.base_version_mismatch", status: 409, currentVersion: 9 }));
  await h.settle();
  assert.equal(h.reloads(), 1);
  assert.equal(h.controller.isIdle(), true);
});
