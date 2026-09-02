import assert from "node:assert/strict";
import test from "node:test";
import {
  AD_DOCUMENT_ID,
  HARVESTED_AD_PAGE,
  adImage,
  adTokenText,
} from "../adapter/__fixtures__/scene-nodes";
import { uploadWebAsset } from "../data/assets";
import type {
  AssetRecord,
  Node,
  Operation,
  Scene,
} from "../engine/scene/contracts";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import { sceneManualWriteGate } from "./use-scene-manual-edits";
import {
  NOT_ACCEPTING_EDITS,
  NOT_AN_IMAGE_TARGET,
  SAME_IMAGE_IN_USE,
  SELECTION_MOVED,
  SceneReplaceImageRefused,
  createSceneReplaceImageHandler,
} from "./use-scene-replace-image";

/**
 * AD4.A step 2 (§1.3 row 1): the Replace-image ORCHESTRATION — the gate before
 * the transport, the upload, the hand-off to the one write path, and every
 * refusal. Which operations the document gets is the adapter's decision and is
 * proven in `adapter/scene-apply.test.ts`; this file proves the sequencing
 * around it.
 *
 * Every case runs against AD2.2's harvested bytes
 * (`__fixtures__/scene-nodes`, document `doc_ad22linkedinsquare00000000001`).
 * The accessors hand back LIVE references into the shared frozen scene, so a
 * case that needs a different node CLONES the scene and edits exactly one
 * field.
 */

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** The harvested image with exactly one field changed. */
function heroWith(change: (node: Node) => void): Node {
  const node = clone(HARVESTED_AD_PAGE).nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  change(node);
  return node;
}

const RECORD: AssetRecord = {
  id: "asset_upload_new",
  kind: "raster_image",
  label: "hero-v2.png",
  source: { kind: "uploaded", filename: "hero-v2.png", uploaded_by: null },
  status: "ready",
};

/** A promise the test releases by hand — an upload held in flight. `resolve` is
 * definitely assigned by the executor, which runs synchronously. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function pngFile(name = "hero-v2.png"): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: "image/png" });
}

function harness({
  accepted = true,
  armed = true,
  locked = false,
  node = adImage() as Node | null,
  upload = async () => RECORD,
}: {
  accepted?: boolean;
  armed?: boolean;
  /** Task 4 fix round 1 (I3): a design turn is running on this document. */
  locked?: boolean;
  node?: Node | null;
  upload?: (file: File) => Promise<AssetRecord>;
} = {}) {
  const applied: { intent?: string; operations: Operation[] }[] = [];
  const errors: string[] = [];
  const notes: string[] = [];
  const uploads: File[] = [];
  let cleared = 0;
  const deps = {
    applyOps: (operations: Operation[], intent?: string) => {
      applied.push({ intent, operations });
      return accepted;
    },
    writeGate: () =>
      sceneManualWriteGate({
        armed,
        engineReady: armed,
        lockNote: AGENT_RUN_LOCK_NOTE,
        locked,
      }),
    clearMessages: () => {
      cleared += 1;
      errors.length = 0;
    },
    documentId: AD_DOCUMENT_ID as string | null,
    node,
    onError: (message: string) => errors.push(message),
    onNote: (message: string) => notes.push(message),
    upload: (candidate: File) => {
      uploads.push(candidate);
      return upload(candidate);
    },
  };
  const handler = createSceneReplaceImageHandler(() => deps);
  return {
    applied,
    clearCount: () => cleared,
    deps,
    errors,
    handler,
    notes,
    uploads,
  };
}

test("the picked file is uploaded and the canonical pair reaches the one write path", async () => {
  const { applied, handler, uploads } = harness();

  await handler(pngFile());

  assert.equal(uploads.length, 1);
  assert.equal(uploads[0].name, "hero-v2.png");
  assert.equal(applied.length, 1, "one batch, so one undo step");
  assert.deepEqual(
    applied[0].operations.map((operation) => operation.kind),
    ["upsert_asset", "place_asset_in_node"],
  );
});

test("the upload posts multipart `file` to the AUTHENTICATED design BFF mount", async () => {
  // Proven through the real client the hook binds by default, so the route and
  // the field name are this lane's, not just the web lane's. `/assets` is
  // workspace-gated and must never reach the headerless `design-public` mount.
  const calls: { init: RequestInit | undefined; url: string }[] = [];
  const fetchImpl = (async (input: unknown, init?: RequestInit) => {
    calls.push({ init, url: String(input) });
    return new Response(JSON.stringify({ asset: RECORD }), {
      headers: { "content-type": "application/json" },
      status: 200,
    });
  }) as unknown as typeof fetch;
  const { applied, handler } = harness({
    upload: (file) => uploadWebAsset(file, { fetchImpl }),
  });

  await handler(pngFile());

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/clue/design/assets");
  assert.equal(calls[0].init?.method, "POST");
  const body = calls[0].init?.body;
  assert.ok(body instanceof FormData, "the body is multipart FormData");
  assert.ok(body.get("file") instanceof File, "the file rides the `file` field");
  assert.equal(applied.length, 1);
});

test("§4: a LOCKED image never reaches the transport — a half write is refused first", async () => {
  const { applied, errors, handler, uploads } = harness({
    node: heroWith((node) => {
      node.locked = true;
    }),
  });

  await assert.rejects(handler(pngFile()));

  assert.equal(uploads.length, 0, "no asset is minted for a write §4 refuses");
  assert.equal(applied.length, 0);
  // Task 3: this used to assert SILENCE. The silence was the bug (spec §1) — a
  // preview that snapped back with no explanation reads as "upload does nothing".
  assert.deepEqual(errors, [NOT_AN_IMAGE_TARGET]);
});

test("a non-image selection, and no selection at all, never upload", async () => {
  const text = harness({ node: adTokenText() });
  await assert.rejects(text.handler(pngFile()));
  assert.equal(text.uploads.length, 0);
  assert.equal(text.applied.length, 0);

  const none = harness({ node: null });
  await assert.rejects(none.handler(pngFile()));
  assert.equal(none.uploads.length, 0);
  assert.equal(none.applied.length, 0);
});

test("a failed upload names the reason in the inspector's own error slot and writes nothing", async () => {
  const { applied, errors, handler } = harness({
    upload: async () => {
      throw new Error("asset payload exceeds the limit");
    },
  });

  await assert.rejects(handler(pngFile()));

  assert.deepEqual(errors, ["asset payload exceeds the limit"]);
  assert.equal(applied.length, 0);
});

test("a non-Error rejection still says something rather than nothing", async () => {
  const { errors, handler } = harness({
    upload: async () => {
      throw "socket hang up";
    },
  });

  await assert.rejects(handler(pngFile()));

  assert.deepEqual(errors, ["socket hang up"]);
});

test("a write the ENGINE refuses rejects too — the panel must not keep the preview", async () => {
  const { applied, errors, handler } = harness({ accepted: false });

  await assert.rejects(handler(pngFile()));

  assert.equal(applied.length, 1, "the batch was offered");
  // The controller already put the engine's own words in the error slot; a
  // second message here would be new failure UI.
  assert.deepEqual(errors, []);
});

test("re-picking the file the node already carries is NOT a write, and now SAYS so", async () => {
  const { applied, errors, handler } = harness({
    upload: async () => ({
      ...RECORD,
      id: "asset_ing_2b0928ca4f3a3c70",
      label: "Brand gradient backdrop",
    }),
  });

  // Task 3: this used to RESOLVE silently on the theory that the document really
  // does hold this picture. From the user's chair a silent resolve after a wait
  // is indistinguishable from a broken upload — so it now reports and rejects.
  await assert.rejects(handler(pngFile()), SceneReplaceImageRefused);

  assert.equal(applied.length, 0, "still not a write");
  assert.deepEqual(errors, [SAME_IMAGE_IN_USE]);
});

test("a second pick while one is in flight is refused, never applied out of order", async () => {
  const held = deferred<AssetRecord>();
  const { applied, handler, uploads } = harness({ upload: () => held.promise });

  const first = handler(pngFile("a.png"));
  await assert.rejects(handler(pngFile("b.png")));
  assert.equal(uploads.length, 1, "the second pick never reaches the transport");
  held.resolve(RECORD);
  await first;

  assert.equal(applied.length, 1);
  assert.equal(uploads[0].name, "a.png");
});

test("a selection that MOVES during the upload writes nothing — never into the wrong node", async () => {
  const held = deferred<AssetRecord>();
  const state = harness({ upload: () => held.promise });

  const pending = state.handler(pngFile());
  assert.equal(state.uploads.length, 1, "the upload is in flight");
  // The user selected something else (or opened another ad) while the bytes
  // were travelling; `applyOps` writes to whatever document is armed NOW.
  state.deps.node = adTokenText();
  held.resolve(RECORD);

  await assert.rejects(pending);
  assert.equal(state.applied.length, 0);
});

test("a node LOCKED while the upload was in flight is refused at the second gate", async () => {
  const held = deferred<AssetRecord>();
  const state = harness({ upload: () => held.promise });

  const pending = state.handler(pngFile());
  assert.equal(state.uploads.length, 1, "the upload is in flight");
  state.deps.node = heroWith((node) => {
    node.locked = true;
  });
  held.resolve(RECORD);

  await assert.rejects(pending);
  assert.equal(state.applied.length, 0);
});

test("the gate re-arms after a refusal — one bad pick does not wedge the control", async () => {
  let attempt = 0;
  const { applied, handler } = harness({
    upload: async () => {
      attempt += 1;
      if (attempt === 1) throw new Error("nope");
      return RECORD;
    },
  });

  await assert.rejects(handler(pngFile()));
  await handler(pngFile());

  assert.equal(applied.length, 1);
});

// ══ Review fixes ════════════════════════════════════════════════════════════

test("FIX 1: a write path that is NOT ARMED refuses before the transport", async () => {
  // The reachable state: CanvasKit fails to activate (D9 read-only), the scene
  // still loads and the layer tree still selects, so the Replace-image button
  // is live over an engine that can apply nothing. `applyOps` would refuse
  // SILENTLY — so an upload here would mint a real asset registry row behind an
  // empty error slot, which is exactly the half write §4's gate exists to stop.
  const { applied, errors, handler, uploads } = harness({ armed: false });

  await assert.rejects(handler(pngFile()));

  assert.equal(uploads.length, 0, "no asset is minted when nothing can land");
  assert.equal(applied.length, 0);
  // Task 3: this used to assert SILENCE, on the theory that the canvas's
  // read-only banner explains the state. It does not explain why THIS control
  // did nothing, so the refusal now names itself in the slot beside the control.
  assert.deepEqual(errors, [NOT_ACCEPTING_EDITS]);
});

test("task 4 (I3): a pick refused by the agent-run lock says SO, and spends nothing", async () => {
  // The defect: the lock reached this flow through `canApply(): boolean`, which
  // threw away the gate's reason — so a pick made while the design agent was
  // working reported "the write path is not armed", a false statement about a
  // perfectly armed editor.
  const { applied, errors, handler, notes, uploads } = harness({ locked: true });

  await assert.rejects(handler(pngFile()));

  assert.equal(uploads.length, 0, "no asset is minted while the agent works");
  assert.equal(applied.length, 0);
  assert.deepEqual(notes, [AGENT_RUN_LOCK_NOTE]);
  // The NOTE line, never the error line: a locked editor is a state to wait
  // out, not a failure.
  assert.deepEqual(errors, []);
});

test("FIX 1: the armed check is asked BEFORE the upload, not after it", async () => {
  // Ordering, not just outcome: an armed-at-pick / not-armed-at-apply run is
  // the only one allowed to reach the transport.
  const held = deferred<AssetRecord>();
  const state = harness({ upload: () => held.promise });

  const pending = state.handler(pngFile());
  assert.equal(state.uploads.length, 1, "an armed pick does reach the transport");
  held.resolve(RECORD);
  await pending;
  assert.equal(state.applied.length, 1);
});

test("FIX 3: a new attempt clears the slot, so a stale refusal cannot outlive it", async () => {
  const state = harness({
    upload: async () => {
      throw new Error("asset payload exceeds the limit");
    },
  });

  await assert.rejects(state.handler(pngFile()));
  assert.deepEqual(state.errors, ["asset payload exceeds the limit"]);

  // The user re-picks the file the node already carries: a NO-OP, which never
  // touches `applyOps` and so never used to clear anything.
  state.deps.upload = async () => ({
    ...RECORD,
    id: "asset_ing_2b0928ca4f3a3c70",
    label: "Brand gradient backdrop",
  });
  await assert.rejects(state.handler(pngFile()), SceneReplaceImageRefused);

  // Task 3: the slot used to end EMPTY here. What this test is about is that the
  // stale 413 is gone — the clear ran, and the only thing left is what the new
  // attempt itself has to say.
  assert.deepEqual(
    state.errors,
    [SAME_IMAGE_IN_USE],
    "the 413 no longer describes anything true",
  );
  assert.equal(state.applied.length, 0, "and it is still not a write");
});

test("FIX 3: a pick the pre-transport gate refuses does not CLEAR the slot — it speaks into it", async () => {
  const { clearCount, handler } = harness({
    node: heroWith((node) => {
      node.locked = true;
    }),
  });

  await assert.rejects(handler(pngFile()));

  // Task 3 narrowed this: the clear still belongs after the gate (a refused pick
  // does not get to wipe what the last attempt said), but the refusal is no
  // longer a complete non-event — it writes its own sentence, proven above.
  assert.equal(clearCount(), 0, "the gate refusal never reaches the clear");
});

test("AD4.A step 3 review: an upload that lands after the ARTIFACT TAB changed writes nothing", () => {
  // The twin of the AI suite's blocker, closed in the same change: this guard
  // compared the node id alone, and the harvest's ids are template slugs
  // (`image_hero`), so two ads routinely carry the same one. A tab switched
  // mid-upload wrote a real version into an ad the user never touched.
  const held = deferred<AssetRecord>();
  const state = harness({ upload: () => held.promise });

  const pending = state.handler(pngFile());
  assert.equal(state.uploads.length, 1, "the upload is in flight");
  // Same node id, different document.
  state.deps.documentId = "doc_a_second_ad_00000000000000";
  held.resolve(RECORD);

  return assert
    .rejects(pending)
    .then(() => assert.equal(state.applied.length, 0, "nothing lands in the other ad"));
});

test("AD4.A step 3 review: a pick with no document armed never reaches the transport", async () => {
  const state = harness();
  state.deps.documentId = null;

  await assert.rejects(state.handler(pngFile()));

  assert.equal(state.uploads.length, 0, "nothing is minted with nothing to write to");
  assert.equal(state.applied.length, 0);
});

// ══ Task 3: every refusal SPEAKS ════════════════════════════════════════════
// The founder's report was "upload does nothing": four refusal paths threw a
// diagnostic-only `SceneReplaceImageRefused` and put NOTHING in the inspector's
// error slot, so the preview snapped back with no explanation. The silence was
// the bug (spec §1); these four cases pin the sentence each refusal now says.
// Deps are built directly here rather than through `harness`, so the sentences
// are asserted against the runner and not against a test-local clearing rule.

function speakingDeps(
  over: Partial<{
    armed: boolean;
    documentId: string | null;
    node: Node | null;
    upload: (f: File) => Promise<AssetRecord>;
  }> = {},
) {
  const errors: string[] = [];
  const applied: Operation[][] = [];
  const deps = {
    applyOps: (ops: Operation[]) => {
      applied.push(ops);
      return true;
    },
    clearMessages: () => undefined,
    documentId: over.documentId === undefined ? AD_DOCUMENT_ID : over.documentId,
    node: over.node === undefined ? (adImage() as Node) : over.node,
    onError: (message: string) => {
      errors.push(message);
    },
    onNote: () => undefined,
    // The merged gate: a silent "not armed" refusal (no note), never the lock.
    writeGate: () =>
      (over.armed ?? true)
        ? { allowed: true, note: null, refusal: null }
        : { allowed: false, note: null, refusal: "not_armed" as const },
    upload: over.upload ?? (async () => RECORD),
  };
  return { applied, deps, errors };
}

test("a refusal because the write path is not armed SPEAKS, then throws", async () => {
  const { deps, errors } = speakingDeps({ armed: false });
  await assert.rejects(
    createSceneReplaceImageHandler(() => deps)(pngFile()),
    SceneReplaceImageRefused,
  );
  assert.deepEqual(errors, [NOT_ACCEPTING_EDITS]);
});

test("a refusal because the selection is not an unlocked image SPEAKS", async () => {
  const locked = heroWith((node) => {
    node.locked = true;
  });
  const { deps, errors } = speakingDeps({ node: locked });
  await assert.rejects(
    createSceneReplaceImageHandler(() => deps)(pngFile()),
    SceneReplaceImageRefused,
  );
  assert.deepEqual(errors, [NOT_AN_IMAGE_TARGET]);
  const text = speakingDeps({ node: adTokenText() as Node });
  await assert.rejects(
    createSceneReplaceImageHandler(() => text.deps)(pngFile()),
    SceneReplaceImageRefused,
  );
  assert.deepEqual(text.errors, [NOT_AN_IMAGE_TARGET]);
});

test("a refusal because the selection moved during the upload SPEAKS", async () => {
  const gate = deferred<AssetRecord>();
  let current: Node | null = adImage() as Node;
  const errors: string[] = [];
  const deps = () => ({
    applyOps: () => true,
    clearMessages: () => undefined,
    documentId: AD_DOCUMENT_ID,
    node: current,
    onError: (m: string) => {
      errors.push(m);
    },
    onNote: () => undefined,
    writeGate: () => ({ allowed: true, note: null, refusal: null }),
    upload: () => gate.promise,
  });
  const run = createSceneReplaceImageHandler(deps)(pngFile());
  current = adTokenText() as Node;
  gate.resolve(RECORD);
  await assert.rejects(run, SceneReplaceImageRefused);
  assert.deepEqual(errors, [SELECTION_MOVED]);
});

test("uploading the very image already in use SPEAKS instead of silently doing nothing", async () => {
  const same = heroWith((node) => {
    if (node.kind.kind === "image") node.kind.asset_id = RECORD.id;
  });
  const { applied, deps, errors } = speakingDeps({ node: same });
  await assert.rejects(
    createSceneReplaceImageHandler(() => deps)(pngFile()),
    SceneReplaceImageRefused,
  );
  assert.deepEqual(errors, [SAME_IMAGE_IN_USE]);
  assert.equal(applied.length, 0);
});
