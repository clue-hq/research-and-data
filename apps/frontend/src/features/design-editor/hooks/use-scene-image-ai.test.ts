import assert from "node:assert/strict";
import test from "node:test";
import {
  AD_DOCUMENT_ID,
  HARVESTED_AD_PAGE,
  adImage,
  adTokenText,
} from "../adapter/__fixtures__/scene-nodes";
import type {
  EditAssetRequest,
  GenerateAssetRequest,
} from "../engine/scene/assetLibrary";
import type {
  AssetRecord,
  Node,
  Operation,
  Scene,
} from "../engine/scene/contracts";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import { sceneManualWriteGate } from "./use-scene-manual-edits";
import {
  createSceneImageAiRunner,
  editSceneAsset,
  generateSceneAsset,
  type SceneImageAiState,
} from "./use-scene-image-ai";

/**
 * AD4.A step 3 (§1.3 row 2): the AI suite's ORCHESTRATION — the gates before
 * the spend, the two transports, what is staged versus what is written, and
 * every refusal. Which operations the document gets is the adapter's decision
 * and is proven in `adapter/scene-apply.test.ts`; the request shaping is
 * `adapter/scene-image-ai.test.ts`. This file proves the sequencing around
 * them.
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

function record(overrides: Partial<AssetRecord> = {}): AssetRecord {
  return {
    id: "asset_gen_new",
    kind: "raster_image",
    label: "a calm clinic reception",
    source: { kind: "generated", model: "image-gen-v1", request_id: null },
    status: "ready",
    ...overrides,
  };
}

/** A promise the test releases by hand — a generation held in flight. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function harness({
  accepted = true,
  armed = true,
  edit = async () => record({ id: "asset_gen_edited" }),
  generate = async () => record(),
  node = adImage() as Node | null,
  scene = HARVESTED_AD_PAGE as Scene | null,
}: {
  accepted?: boolean;
  armed?: boolean;
  edit?: (request: EditAssetRequest) => Promise<AssetRecord>;
  generate?: (request: GenerateAssetRequest) => Promise<AssetRecord>;
  node?: Node | null;
  scene?: Scene | null;
} = {}) {
  const applied: { intent?: string; operations: Operation[] }[] = [];
  const edits: EditAssetRequest[] = [];
  const errors: string[] = [];
  const generations: GenerateAssetRequest[] = [];
  let state: SceneImageAiState = {
    candidate: null,
    editing: false,
    generating: false,
    savedNotice: null,
  };
  let cleared = 0;
  /** Mutable so a case can disarm the write path mid-review — or (task 4) lock
   * it behind a running design turn. */
  const live = { armed, locked: false };
  const notes: string[] = [];
  const deps = {
    applyOps: (operations: Operation[], intent?: string) => {
      applied.push({ intent, operations });
      return accepted;
    },
    writeGate: () =>
      sceneManualWriteGate({
        armed: live.armed,
        engineReady: live.armed,
        lockNote: AGENT_RUN_LOCK_NOTE,
        locked: live.locked,
      }),
    clearMessages: () => {
      cleared += 1;
      errors.length = 0;
    },
    documentId: AD_DOCUMENT_ID as string | null,
    edit: (request: EditAssetRequest) => {
      edits.push(request);
      return edit(request);
    },
    generate: (request: GenerateAssetRequest) => {
      generations.push(request);
      return generate(request);
    },
    node,
    onError: (message: string) => errors.push(message),
    onNote: (message: string) => notes.push(message),
    publish: (next: SceneImageAiState) => {
      state = next;
    },
    scene,
  };
  return {
    applied,
    clearCount: () => cleared,
    deps,
    edits,
    errors,
    generations,
    live,
    notes,
    runner: createSceneImageAiRunner(() => deps),
    state: () => state,
  };
}

// ══ Generate ════════════════════════════════════════════════════════════════

test("generate: the picture swaps into the node immediately — one batch, the canonical pair", async () => {
  const state = harness();

  await state.runner.generate("a calm clinic reception");

  assert.equal(state.generations.length, 1);
  assert.equal(state.applied.length, 1, "one batch, so one undo step");
  assert.deepEqual(
    state.applied[0].operations.map((operation) => operation.kind),
    ["upsert_asset", "place_asset_in_node"],
  );
  assert.equal(state.state().candidate, null, "generate never stages a review");
});

test("generate: the request carries the node's resolution and the truncated label", async () => {
  const state = harness();

  await state.runner.generate("  a calm clinic reception  ");

  assert.deepEqual(state.generations[0], {
    height: 983,
    label: "a calm clinic reception",
    prompt: "a calm clinic reception",
    width: 1536,
  });
});

/** Runs a case against the REAL default transports — the very functions the
 * hook binds — with a browser-shaped origin and a captured `fetch`. That is
 * what makes the route, the body and the required `provider` field this lane's,
 * rather than a look-alike request that happens to match. */
async function withCapturedFetch(
  asset: AssetRecord,
  run: (calls: { init: RequestInit | undefined; url: string }[]) => Promise<void>,
) {
  const calls: { init: RequestInit | undefined; url: string }[] = [];
  const globals = globalThis as {
    fetch?: typeof fetch;
    window?: unknown;
  };
  const realFetch = globals.fetch;
  // `designBffConfig` reads the page origin; this runner has no DOM.
  globals.window = { location: { origin: "https://app.example" } };
  globals.fetch = (async (input: unknown, init?: RequestInit) => {
    calls.push({ init, url: String(input) });
    return new Response(JSON.stringify({ asset }), {
      headers: { "content-type": "application/json" },
      status: 200,
    });
  }) as unknown as typeof fetch;
  try {
    await run(calls);
  } finally {
    delete globals.window;
    globals.fetch = realFetch;
  }
}

test("generate: the POST reaches the AUTHENTICATED design BFF mount with the provider the API demands", async () => {
  // `/assets/generate` is workspace-gated and must never reach the headerless
  // `design-public` mount, which serves only public asset bytes.
  await withCapturedFetch(record(), async (calls) => {
    const state = harness({ generate: generateSceneAsset });

    await state.runner.generate("a calm clinic reception");

    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/clue/design/assets/generate");
    assert.equal(calls[0].init?.method, "POST");
    const body = JSON.parse(String(calls[0].init?.body)) as Record<string, unknown>;
    assert.equal(body.provider, "image-gen-v1", "the API 422s on a body without it");
    assert.equal(body.output_kind, "raster_image");
    assert.equal(body.prompt, "a calm clinic reception");
    assert.equal(body.width, 1536);
    assert.equal(body.height, 983);
    assert.equal(state.applied.length, 1);
  });
});

test("§4: a LOCKED image never reaches the model — a half write is refused before the spend", async () => {
  const state = harness({
    node: heroWith((node) => {
      node.locked = true;
    }),
  });

  await state.runner.generate("anything");

  assert.equal(state.generations.length, 0, "nothing is minted for a write §4 refuses");
  assert.equal(state.applied.length, 0);
  // Silent, like every other §4 refusal on this lane.
  assert.deepEqual(state.errors, []);
  assert.equal(state.clearCount(), 0, "a complete non-event touches no slot");
});

test("generate: a non-image selection, and no selection at all, never reach the model", async () => {
  const text = harness({ node: adTokenText() });
  await text.runner.generate("anything");
  assert.equal(text.generations.length, 0);

  const none = harness({ node: null });
  await none.runner.generate("anything");
  assert.equal(none.generations.length, 0);
});

test("generate: a write path that is NOT ARMED refuses before the spend", async () => {
  // The reachable state: CanvasKit fails to activate (D9 read-only), the scene
  // still loads and the layer tree still selects, so the button is live over an
  // engine that can apply nothing — and `applyOps` would refuse SILENTLY, so a
  // generation here would mint a real asset behind an empty error slot.
  const state = harness({ armed: false });

  await state.runner.generate("anything");

  assert.equal(state.generations.length, 0, "nothing is minted when nothing can land");
  assert.equal(state.applied.length, 0);
  assert.deepEqual(state.errors, []);
});

test("task 4 (I3): generate under the agent-run lock spends nothing and SAYS why", async () => {
  // Same non-spend as the not-armed case above, and the opposite silence: this
  // refusal has words, and dropping them (the `canApply(): boolean` seam) left
  // a live-looking Generate button whose click did nothing at all.
  const state = harness();
  state.live.locked = true;

  await state.runner.generate("a hero image");

  assert.equal(state.generations.length, 0, "nothing is minted while the agent works");
  assert.equal(state.applied.length, 0);
  assert.deepEqual(state.notes, [AGENT_RUN_LOCK_NOTE]);
  assert.deepEqual(state.errors, [], "a locked editor is a state, not a failure");
});

test("generate: an empty or whitespace-only prompt spends nothing", async () => {
  const state = harness();

  await state.runner.generate("   ");

  assert.equal(state.generations.length, 0);
});

test("generate: a failed generation names the API's reason in the inspector's own error slot", async () => {
  const state = harness({
    generate: async () => {
      throw new Error("image model is not configured");
    },
  });

  await state.runner.generate("a calm clinic reception");

  assert.deepEqual(state.errors, ["image model is not configured"]);
  assert.equal(state.applied.length, 0);
  assert.equal(state.state().generating, false, "the pending state always ends");
});

test("generate: a non-Error rejection still says something rather than nothing", async () => {
  const state = harness({
    generate: async () => {
      throw "socket hang up";
    },
  });

  await state.runner.generate("a calm clinic reception");

  assert.deepEqual(state.errors, ["socket hang up"]);
});

test("generate: a SECOND run while one is in flight is refused, never applied out of order", async () => {
  const held = deferred<AssetRecord>();
  const state = harness({ generate: () => held.promise });

  const first = state.runner.generate("first");
  await state.runner.generate("second");
  assert.equal(state.generations.length, 1, "the second run never reaches the model");
  assert.equal(state.state().generating, true);
  held.resolve(record());
  await first;

  assert.equal(state.applied.length, 1);
  assert.equal(state.generations[0].prompt, "first");
});

test("generate: a selection that MOVES mid-flight writes nothing — never into the wrong node", async () => {
  const held = deferred<AssetRecord>();
  const state = harness({ generate: () => held.promise });

  const pending = state.runner.generate("a calm clinic reception");
  assert.equal(state.generations.length, 1, "the generation is in flight");
  state.deps.node = adTokenText();
  held.resolve(record());
  await pending;

  assert.equal(state.applied.length, 0);
});

test("generate: a node LOCKED mid-flight is refused at the second gate", async () => {
  const held = deferred<AssetRecord>();
  const state = harness({ generate: () => held.promise });

  const pending = state.runner.generate("a calm clinic reception");
  state.deps.node = heroWith((node) => {
    node.locked = true;
  });
  held.resolve(record());
  await pending;

  assert.equal(state.applied.length, 0);
});

test("generate: the generation cache handing back the node's OWN asset is not a write, and not a failure", async () => {
  // `/assets/generate` keys a cache on prompt + model + size, so re-running an
  // identical prompt returns the very asset the node already carries.
  const state = harness({
    generate: async () => record({ id: "asset_ing_2b0928ca4f3a3c70" }),
  });

  await state.runner.generate("a calm clinic reception");

  assert.equal(state.applied.length, 0);
  assert.deepEqual(state.errors, []);
});

test("generate: a new attempt clears the slot, so a stale refusal cannot outlive it", async () => {
  const state = harness({
    generate: async () => {
      throw new Error("image model is not configured");
    },
  });

  await state.runner.generate("a calm clinic reception");
  assert.deepEqual(state.errors, ["image model is not configured"]);

  state.deps.generate = async () => record({ id: "asset_ing_2b0928ca4f3a3c70" });
  await state.runner.generate("a calm clinic reception");

  assert.deepEqual(state.errors, [], "the old refusal no longer describes anything true");
});

// ══ Edit and remove background ══════════════════════════════════════════════

test("edit: the result is STAGED for review and the node is not touched at all", async () => {
  const state = harness();

  await state.runner.edit("make the sky warmer");

  assert.equal(state.edits.length, 1);
  assert.equal(state.applied.length, 0, "an edit writes nothing until Accept");
  assert.equal(state.state().candidate?.record.id, "asset_gen_edited");
  assert.equal(state.state().candidate?.forNodeId, "image_hero");
  assert.equal(state.state().candidate?.forDocumentId, AD_DOCUMENT_ID);
});

test("edit: the request carries the node's own asset as the source, and the truncated label", async () => {
  const state = harness();

  await state.runner.edit("  make the sky warmer  ");

  assert.deepEqual(state.edits[0], {
    label: "make the sky warmer",
    prompt: "make the sky warmer",
    sourceAssetId: "asset_ing_2b0928ca4f3a3c70",
    transparentBackground: undefined,
  });
});

test("edit: the POST is the SAME route as generate, plus a source_asset_id", async () => {
  await withCapturedFetch(record({ id: "asset_gen_edited" }), async (calls) => {
    const state = harness({ edit: editSceneAsset });

    await state.runner.removeBackground();

    assert.equal(calls[0].url, "/api/clue/design/assets/generate");
    const body = JSON.parse(String(calls[0].init?.body)) as Record<string, unknown>;
    assert.equal(body.source_asset_id, "asset_ing_2b0928ca4f3a3c70");
    assert.equal(body.provider, "image-gen-v1");
    assert.equal(body.transparent_background, true);
    assert.equal(state.applied.length, 0, "an edit still writes nothing");
  });
});

test("remove background: the fixed instruction, transparency on, and no typed text required", async () => {
  const state = harness();

  await state.runner.removeBackground();

  assert.deepEqual(state.edits[0], {
    label: "Remove the background completely",
    prompt: "Remove the background completely",
    sourceAssetId: "asset_ing_2b0928ca4f3a3c70",
    transparentBackground: true,
  });
  assert.equal(state.applied.length, 0, "it stages, like every other edit");
});

test("§4: a LOCKED image, a non-image node and an unarmed write path all refuse to spend on an edit", async () => {
  const locked = harness({
    node: heroWith((node) => {
      node.locked = true;
    }),
  });
  await locked.runner.edit("make the sky warmer");
  assert.equal(locked.edits.length, 0);

  const text = harness({ node: adTokenText() });
  await text.runner.edit("make the sky warmer");
  assert.equal(text.edits.length, 0);

  const unarmed = harness({ armed: false });
  await unarmed.runner.edit("make the sky warmer");
  assert.equal(unarmed.edits.length, 0);
});

test("edit: an asset that is not READY has no pixels to edit — nothing is spent", async () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.assets.asset_ing_2b0928ca4f3a3c70.status = "pending";
  const state = harness({ node: scene.nodes.image_hero, scene });

  await state.runner.edit("make the sky warmer");

  assert.equal(state.edits.length, 0);
});

test("edit: an empty instruction, and a SECOND edit while one is staged, both spend nothing", async () => {
  const empty = harness();
  await empty.runner.edit("   ");
  assert.equal(empty.edits.length, 0);

  const staged = harness();
  await staged.runner.edit("make the sky warmer");
  assert.equal(staged.edits.length, 1);
  await staged.runner.edit("and remove the person on the left");
  assert.equal(staged.edits.length, 1, "the staged candidate must be answered first");
  await staged.runner.removeBackground();
  assert.equal(staged.edits.length, 1);
});

test("edit: a failed edit names the API's reason and stages nothing", async () => {
  const state = harness({
    edit: async () => {
      throw new Error("source asset has no stored bytes to edit");
    },
  });

  await state.runner.edit("make the sky warmer");

  assert.deepEqual(state.errors, ["source asset has no stored bytes to edit"]);
  assert.equal(state.state().candidate, null);
  assert.equal(state.state().editing, false, "the pending state always ends");
});

test("edit: a result that lands after the selection MOVED is still kept, stamped with its node", async () => {
  // A paid result is never thrown away: it is stamped with the node it was made
  // FROM, so it is simply invisible until that node is selected again. The
  // accept path is what refuses to place it anywhere else.
  const held = deferred<AssetRecord>();
  const state = harness({ edit: () => held.promise });

  const pending = state.runner.edit("make the sky warmer");
  state.deps.node = adTokenText();
  held.resolve(record({ id: "asset_gen_edited" }));
  await pending;

  assert.equal(state.state().candidate?.forNodeId, "image_hero");
  assert.equal(state.applied.length, 0);
});

// ══ Candidate review ════════════════════════════════════════════════════════

async function staged() {
  const state = harness();
  await state.runner.edit("make the sky warmer");
  assert.ok(state.state().candidate, "the edit staged a candidate");
  return state;
}

test("accept: the candidate swaps in through the SAME pair, carrying the placement forward", async () => {
  const state = await staged();

  assert.equal(state.runner.accept(), true, "an accept that landed says so");

  assert.equal(state.applied.length, 1, "one batch, so one undo step");
  assert.deepEqual(
    state.applied[0].operations.map((operation) => operation.kind),
    ["upsert_asset", "place_asset_in_node"],
  );
  const place = state.applied[0].operations[1] as unknown as {
    placement: Record<string, unknown>;
  };
  assert.deepEqual(place.placement, {
    alt_text: "Brand gradient backdrop",
    fit: "cover",
    focal_point: { x: 0.5, y: 0.42 },
    preserve_transparency: false,
  });
  assert.equal(state.state().candidate, null, "the review is over");
});

test("accept: a candidate is NEVER placed on a different node than the one it was made from", async () => {
  const state = await staged();
  state.deps.node = adTokenText();

  assert.equal(state.runner.accept(), false, "and it reports the refusal");

  assert.equal(state.applied.length, 0);
  assert.ok(state.state().candidate, "and the paid result is kept, not discarded");
});

test("accept: a write the ENGINE refuses keeps the candidate staged for a retry", async () => {
  const state = harness({ accepted: false });
  await state.runner.edit("make the sky warmer");

  state.runner.accept();

  assert.equal(state.applied.length, 1, "the batch was offered");
  assert.ok(state.state().candidate, "a refused write does not update the panel's record");
});

test("accept: a node LOCKED since the edit refuses, and the candidate survives the refusal", async () => {
  const state = await staged();
  state.deps.node = heroWith((node) => {
    node.locked = true;
  });

  state.runner.accept();

  assert.equal(state.applied.length, 0);
  assert.ok(state.state().candidate, "the lock is a refusal, not a discard");
});

test("accept: an unarmed write path refuses and keeps the candidate", async () => {
  const state = await staged();
  state.live.armed = false;

  state.runner.accept();

  assert.equal(state.applied.length, 0);
  assert.ok(
    state.state().candidate,
    "an unarmed accept keeps the paid result staged",
  );
});

test("reject: zero scene mutations, and the review is over", async () => {
  const state = await staged();

  state.runner.reject();

  assert.equal(state.applied.length, 0);
  assert.equal(state.state().candidate, null);
  assert.equal(state.state().savedNotice, null);
});

test("save as new: zero scene mutations, and the notice names the asset that was kept", async () => {
  const state = await staged();

  state.runner.saveAsNew();

  assert.equal(state.applied.length, 0);
  assert.equal(state.state().candidate, null);
  assert.deepEqual(state.state().savedNotice, {
    forDocumentId: AD_DOCUMENT_ID,
    forNodeId: "image_hero",
    // REVIEW FIX: STAMPED like the candidate it describes. Unstamped it
    // followed the user onto the next image and stated something that had
    // never happened there.
    message: "Saved a calm clinic reception to the asset library.",
  });
});

test("a new edit clears the last save notice — it no longer describes anything current", async () => {
  const state = await staged();
  state.runner.saveAsNew();
  assert.ok(state.state().savedNotice, "save as new set a notice");

  await state.runner.edit("make the sky warmer");

  assert.equal(state.state().savedNotice, null);
});

// ══ Review fixes ════════════════════════════════════════════════════════════

test("BLOCKER: a generation that resolves after the ARTIFACT TAB changed writes nothing", async () => {
  // The repro: generate on doc A's `image_hero`, switch tabs to doc B, select
  // doc B's `image_hero` — the harvest's ids are template slugs, so two ads
  // routinely carry the same one — and a node-id-only guard passed, writing a
  // real version and a real undo step into an ad the user never touched.
  const held = deferred<AssetRecord>();
  const state = harness({ generate: () => held.promise });

  const pending = state.runner.generate("a calm clinic reception");
  assert.equal(state.generations.length, 1, "the generation is in flight");
  // Same node id, different document.
  state.deps.documentId = "doc_a_second_ad_00000000000000";
  held.resolve(record());
  await pending;

  assert.equal(state.applied.length, 0, "nothing lands in the other ad");
});

test("BLOCKER: a generation with no document armed never reaches the model", async () => {
  const state = harness();
  state.deps.documentId = null;

  await state.runner.generate("a calm clinic reception");

  assert.equal(state.generations.length, 0, "nothing is minted with nothing to write to");
  assert.equal(state.applied.length, 0);
});

test("a generate supersedes a save notice — it describes a picture about to leave", async () => {
  const state = await staged();
  state.runner.saveAsNew();
  assert.ok(state.state().savedNotice, "save as new set a notice");

  await state.runner.generate("a calm clinic reception");

  assert.equal(state.state().savedNotice, null);
});

test("RE-REVIEW: every refused accept REPORTS the refusal, so the panel clears nothing", async () => {
  // The panel keys the instruction draft's clearing on this boolean. Each case
  // below also keeps the candidate — the two facts are one fact: a refusal
  // touches nothing.
  const engineRefused = harness({ accepted: false });
  await engineRefused.runner.edit("make the sky warmer");
  assert.equal(engineRefused.runner.accept(), false, "a CAS/engine refusal");
  assert.ok(engineRefused.state().candidate, "and the candidate survives it");

  const unarmed = await staged();
  unarmed.live.armed = false;
  assert.equal(unarmed.runner.accept(), false, "an unarmed write path");
  assert.ok(unarmed.state().candidate, "and the candidate survives it");

  const locked = await staged();
  locked.deps.node = heroWith((node) => {
    node.locked = true;
  });
  assert.equal(locked.runner.accept(), false, "a node locked since the edit");
  assert.ok(locked.state().candidate, "and the candidate survives it");

  const none = harness();
  assert.equal(none.runner.accept(), false, "and nothing staged is not a landing");
  assert.equal(none.runner.saveAsNew(), false, "nor is a save with nothing to save");
});

test("RE-REVIEW: the genuine NO-OP accept reports true — the document really does hold it", async () => {
  // The edit handed back the asset the node already carries, so no operation is
  // produced and the review is genuinely over. Clearing the instruction here is
  // correct: the question has been answered.
  const state = harness({
    edit: async () => record({ id: "asset_ing_2b0928ca4f3a3c70" }),
  });
  await state.runner.edit("make the sky warmer");

  assert.equal(state.runner.accept(), true);

  assert.equal(state.applied.length, 0, "and it wrote nothing");
  assert.equal(state.state().candidate, null, "and the review is over");
});

test("save as new reports true when it confirmed a candidate", async () => {
  const state = await staged();

  assert.equal(state.runner.saveAsNew(), true);

  assert.ok(state.state().savedNotice, "and it left the notice behind");
});
