import assert from "node:assert/strict";
import test from "node:test";
import {
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
import { createSceneReplaceImageHandler } from "./use-scene-replace-image";

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
  node = adImage() as Node | null,
  upload = async () => RECORD,
}: {
  accepted?: boolean;
  armed?: boolean;
  node?: Node | null;
  upload?: (file: File) => Promise<AssetRecord>;
} = {}) {
  const applied: { intent?: string; operations: Operation[] }[] = [];
  const errors: string[] = [];
  const uploads: File[] = [];
  let cleared = 0;
  const deps = {
    applyOps: (operations: Operation[], intent?: string) => {
      applied.push({ intent, operations });
      return accepted;
    },
    canApply: () => armed,
    clearMessages: () => {
      cleared += 1;
      errors.length = 0;
    },
    node,
    onError: (message: string) => errors.push(message),
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
  // Silent, exactly like every other §4 refusal on this lane: the panel simply
  // does not record it (the rejection is what puts the preview back).
  assert.deepEqual(errors, []);
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

test("re-picking the file the node already carries is NOT a write, and is not a failure", async () => {
  const { applied, errors, handler } = harness({
    upload: async () => ({
      ...RECORD,
      id: "asset_ing_2b0928ca4f3a3c70",
      label: "Brand gradient backdrop",
    }),
  });

  // Resolves: the document really does hold this picture, so the preview
  // showing it is true.
  await handler(pngFile());

  assert.equal(applied.length, 0);
  assert.deepEqual(errors, []);
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
  // Silent, like the lock: the canvas's own read-only banner already explains
  // this state and a second message would be new failure UI.
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
  await state.handler(pngFile());

  assert.deepEqual(state.errors, [], "the 413 no longer describes anything true");
  assert.equal(state.applied.length, 0, "and it is still not a write");
});

test("FIX 3: a pick the pre-transport gate refuses changes nothing at all, messages included", async () => {
  const { clearCount, handler } = harness({
    node: heroWith((node) => {
      node.locked = true;
    }),
  });

  await assert.rejects(handler(pngFile()));

  assert.equal(clearCount(), 0, "a complete non-event does not touch the slots");
});
