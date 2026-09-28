import assert from "node:assert/strict";
import { it } from "node:test";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "../adapter/__fixtures__/scene-nodes";
import { parentOriginOf } from "./use-scene-clipboard";
import type {
  AssetRecord,
  Node,
  Operation,
  Scene,
} from "../engine/scene/contracts";
import {
  CLIENT_ASSET_MAX_BYTES,
  IMAGE_PASTE_INTENT,
  ingestExternalImages,
  pastedImageNodeSize,
  svgMarkupToFile,
  type ExternalImageIngestDeps,
  type ExternalImagePlacement,
} from "./use-scene-image-paste";

/**
 * Clipboard Task 8 — external image ingestion: a dropped or pasted picture
 * becomes an uploaded asset and ONE image node, or a refusal that says which
 * file and why.
 *
 * Everything with a rule is a module-level function over an injected deps
 * object (`createSceneReplaceImageHandler` / Task 7 precedent — the runner is
 * `tsx --test` over `.ts` only, so a hook is never component-tested here), so
 * every case below drives the real ingestion with a FAKE upload and reads the
 * operations it would have applied. No DOM, no transport, no engine.
 *
 * THE FIXTURE'S OWN SHAPE, which the placement assertions lean on:
 *   page `page_linkedin_square` is 1200x1200 pt and holds ONE child,
 *   `frame_ad_root` — so a page-parented insert appends at index 1.
 *   `auto_row_copy` is an UNLOCKED auto-layout holding two children, which is
 *   what makes an into-layout (⌘V-with-a-row-selected) gesture reachable.
 *   R25's 60%-of-the-short-side box on this page is therefore 720.
 */

// ── harness ────────────────────────────────────────────────────────────────

function pngFile(name = "shot.png", bytes = 1024): File {
  const file = new File([new Uint8Array(bytes)], name, { type: "image/png" });
  return file;
}

/** A ready raster record: the shape a successful upload hands back. */
function rasterRecord(
  overrides: Partial<AssetRecord> = {},
  pixels: { width: number; height: number } = { width: 400, height: 200 },
): AssetRecord {
  return {
    id: "asset_new_0001",
    label: "shot.png",
    kind: "raster_image",
    status: "ready",
    source: { kind: "uploaded", filename: "shot.png", uploaded_by: null },
    raster: {
      pixel_width: pixels.width,
      pixel_height: pixels.height,
      dpi_x: null,
      dpi_y: null,
      has_alpha: null,
      color_profile: null,
      aspect_ratio: null,
    },
    vector: null,
    ...overrides,
  };
}

/** A ready vector record — an SVG's dimensions live in `vector`, and both of
 * its fields are NULLABLE, which is why R22 exists. */
function vectorRecord(
  size: { width: number | null; height: number | null } = {
    width: 300,
    height: 150,
  },
): AssetRecord {
  return {
    id: "asset_new_svg1",
    label: "pasted-image.svg",
    kind: "vector",
    status: "ready",
    source: { kind: "uploaded", filename: "pasted-image.svg", uploaded_by: null },
    raster: null,
    vector: {
      width: size.width,
      height: size.height,
      view_box: null,
      has_transparency: null,
      path_data: null,
    },
  };
}

interface Harness {
  applied: { operations: Operation[]; intent?: string }[];
  deps: ExternalImageIngestDeps;
  errors: string[];
  uploaded: File[];
}

/** The ingestion wired to a fake upload and a recording write path. */
function harness(
  options: {
    canApply?: () => boolean;
    applyOps?: (operations: Operation[], intent?: string) => boolean;
    scene?: () => Scene | null;
    upload?: (file: File) => Promise<AssetRecord>;
  } = {},
): Harness {
  const applied: { operations: Operation[]; intent?: string }[] = [];
  const errors: string[] = [];
  const uploaded: File[] = [];
  const upload =
    options.upload ?? (async () => rasterRecord());
  const deps: ExternalImageIngestDeps = {
    applyOps:
      options.applyOps ??
      ((operations, intent) => {
        applied.push({ operations, intent });
        return true;
      }),
    canApply: options.canApply ?? (() => true),
    parentOrigin: parentOriginOf,
    reportError: (message) => errors.push(message),
    scene: options.scene ?? (() => HARVESTED_AD_PAGE),
    upload: async (file) => {
      uploaded.push(file);
      return upload(file);
    },
  };
  return { applied, deps, errors, uploaded };
}

const VIEWPORT_CENTER: ExternalImagePlacement = {
  mode: { kind: "viewport-center", center: { x: 600, y: 600 } },
  pageId: AD_PAGE_ID,
  selectedNodeId: null,
};

/** The node an `insert_node` op carries, typed. */
function insertedNode(operation: Operation): Node {
  assert.equal(operation.kind, "insert_node");
  return (operation as Extract<Operation, { kind: "insert_node" }>).node;
}

function insertedAt(operation: Operation): number {
  assert.equal(operation.kind, "insert_node");
  return (operation as Extract<Operation, { kind: "insert_node" }>).index;
}

/** The batch's inserts, in order — the ops each picture's `upsert_asset`
 * precedes. Cases about WHERE a picture lands read this; the case about the
 * batch's own shape reads the raw array. */
function inserts(operations: Operation[]): Operation[] {
  return operations.filter((operation) => operation.kind === "insert_node");
}

// ── R25: the sizing rule ───────────────────────────────────────────────────

it("fits a pasted image inside 60% of the page's SHORT side, at its own aspect", () => {
  // The ratified numbers: 4000x2000 on a 1080x1080 page → a 648-wide fit.
  assert.deepEqual(
    pastedImageNodeSize(
      { width: 4000, height: 2000 },
      { width: 1080, height: 1080 },
    ),
    { width: 648, height: 324 },
  );
});

it("never UPSCALES: a small image pastes at its intrinsic size", () => {
  assert.deepEqual(
    pastedImageNodeSize(
      { width: 200, height: 100 },
      { width: 1080, height: 1080 },
    ),
    { width: 200, height: 100 },
  );
});

it("reads the SHORT side of a non-square page, not its width", () => {
  // 60% of 1000, not of 2000 — a landscape page must not license a wider box.
  assert.deepEqual(
    pastedImageNodeSize(
      { width: 1200, height: 1200 },
      { width: 2000, height: 1000 },
    ),
    { width: 600, height: 600 },
  );
});

// ── svg markup → a file, so ONE path ingests every picture ─────────────────

it("turns pasted svg markup into an image/svg+xml File", async () => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>';
  const file = svgMarkupToFile(svg);

  assert.equal(file.type, "image/svg+xml");
  // The brief's literal name, pinned: it is what the refusal path shows a user
  // for markup that arrived with no filename of its own.
  assert.equal(file.name, "pasted.svg");
  assert.equal(await file.text(), svg);
});

// ── the happy path ─────────────────────────────────────────────────────────

it("uploads a png ONCE and inserts one image node carrying its asset id", async () => {
  const test = harness();

  const outcome = await ingestExternalImages(
    [pngFile()],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.deepEqual(outcome, { inserted: 1, refusals: [] });
  assert.equal(test.uploaded.length, 1);
  assert.equal(test.errors.length, 0);
  // R20: ONE applyOps for the whole gesture — one undo frame. TWO operations
  // in it: the asset must be registered on the document before a node can
  // reference it (see the batch-shape case below).
  assert.equal(test.applied.length, 1);
  assert.equal(test.applied[0].intent, IMAGE_PASTE_INTENT);
  assert.equal(test.applied[0].operations.length, 2);

  const operation = test.applied[0].operations[1];
  assert.deepEqual(
    (operation as Extract<Operation, { kind: "insert_node" }>).parent,
    { kind: "page", id: AD_PAGE_ID },
  );
  // The page holds one child (`frame_ad_root`), so the paste appends at 1.
  assert.equal(insertedAt(operation), 1);

  const node = insertedNode(operation);
  assert.deepEqual(node.kind, {
    kind: "image",
    asset_id: "asset_new_0001",
    alt: "shot.png",
  });
  assert.equal(node.name, "shot.png");
  assert.match(node.id, /^node-/);
  // 400x200 is already inside the 720 box: intrinsic size, centred on (600,600).
  assert.deepEqual(node.size, {
    width: { kind: "fixed", value: 400 },
    height: { kind: "fixed", value: 200 },
  });
  assert.deepEqual(node.transform, {
    x: 400,
    y: 500,
    rotation: 0,
    skew_x: 0,
    skew_y: 0,
    flip_x: false,
    flip_y: false,
  });
  // Childless, unstyled, unlocked, and NEVER carrying solved geometry.
  assert.deepEqual(node.children, []);
  assert.deepEqual(node.fills, []);
  assert.deepEqual(node.strokes, []);
  assert.deepEqual(node.corner, {
    top_left: 0,
    top_right: 0,
    bottom_right: 0,
    bottom_left: 0,
  });
  assert.equal(node.opacity, 1);
  assert.equal(node.clip, false);
  assert.equal(node.layout, null);
  assert.equal(node.computed, null);
  assert.equal(node.locked, false);
});

it("REGISTERS each asset on the document before the node that references it", async () => {
  let count = 0;
  const test = harness({
    upload: async () => {
      count += 1;
      return rasterRecord({ id: `asset_new_000${count}` });
    },
  });

  await ingestExternalImages(
    [pngFile("first.png"), pngFile("second.png")],
    VIEWPORT_CENTER,
    test.deps,
  );

  const operations = test.applied[0].operations;
  // Per file, in order: register, then insert. `insert_node` alone would leave
  // `scene.assets` without the record — the canvas resolves no bytes for an
  // unregistered id (a blank box) and lumen-core's strict validation flags it.
  assert.deepEqual(
    operations.map((operation) => operation.kind),
    ["upsert_asset", "insert_node", "upsert_asset", "insert_node"],
  );
  // Each pair is about the SAME asset: the record registered is the record the
  // node points at.
  for (const pair of [0, 2]) {
    const upsert = operations[pair] as Extract<
      Operation,
      { kind: "upsert_asset" }
    >;
    const node = insertedNode(operations[pair + 1]);
    assert.equal(
      upsert.asset.id,
      (node.kind as Extract<typeof node.kind, { kind: "image" }>).asset_id,
    );
  }
  // The record travels VERBATIM — the store's own row, not a rebuilt one.
  assert.deepEqual(
    (operations[0] as Extract<Operation, { kind: "upsert_asset" }>).asset,
    rasterRecord({ id: "asset_new_0001" }),
  );
});

it("downscales a big picture through the R25 rule on the way in", async () => {
  const test = harness({
    upload: async () =>
      rasterRecord({}, { width: 4000, height: 2000 }),
  });

  await ingestExternalImages([pngFile()], VIEWPORT_CENTER, test.deps);

  const node = insertedNode(inserts(test.applied[0].operations)[0]);
  // 60% of this fixture page's 1200 short side is 720.
  assert.deepEqual(node.size, {
    width: { kind: "fixed", value: 720 },
    height: { kind: "fixed", value: 360 },
  });
});

it("centres a DROPPED image on the page point the pointer named", async () => {
  const test = harness({
    upload: async () => rasterRecord({}, { width: 200, height: 100 }),
  });

  await ingestExternalImages(
    [pngFile()],
    {
      mode: { kind: "drop-point", pagePoint: { x: 500, y: 500 } },
      pageId: AD_PAGE_ID,
      selectedNodeId: null,
    },
    test.deps,
  );

  const node = insertedNode(inserts(test.applied[0].operations)[0]);
  assert.equal(node.transform.x, 400);
  assert.equal(node.transform.y, 450);
});

it("routes svg markup down the SAME path as a pasted file", async () => {
  const test = harness({ upload: async () => vectorRecord() });

  const outcome = await ingestExternalImages(
    [svgMarkupToFile('<svg xmlns="http://www.w3.org/2000/svg"/>')],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.deepEqual(outcome, { inserted: 1, refusals: [] });
  assert.equal(test.uploaded[0].type, "image/svg+xml");
  const node = insertedNode(inserts(test.applied[0].operations)[0]);
  // The dimensions came from `vector`, which is where an SVG's live.
  assert.deepEqual(node.size, {
    width: { kind: "fixed", value: 300 },
    height: { kind: "fixed", value: 150 },
  });
});

// ── R24: per-file fan-out, R20: one frame ──────────────────────────────────

it("fans a multi-file gesture out by +10/+10 per file, in ONE applyOps", async () => {
  let count = 0;
  const test = harness({
    upload: async () => {
      count += 1;
      return rasterRecord({ id: `asset_new_000${count}` });
    },
  });

  const outcome = await ingestExternalImages(
    [pngFile("first.png"), pngFile("second.png")],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.deepEqual(outcome, { inserted: 2, refusals: [] });
  assert.equal(test.applied.length, 1);
  const [first, second] = inserts(test.applied[0].operations);
  assert.equal(insertedNode(first).transform.x, 400);
  assert.equal(insertedNode(first).transform.y, 500);
  assert.equal(insertedNode(second).transform.x, 410);
  assert.equal(insertedNode(second).transform.y, 510);
  // Consecutive seats keep the drop order's z-order.
  assert.equal(insertedAt(first), 1);
  assert.equal(insertedAt(second), 2);
  // Two nodes, two ids.
  assert.notEqual(insertedNode(first).id, insertedNode(second).id);
});

it("inserts consecutive CHILDREN when an unlocked auto-layout is selected", async () => {
  let count = 0;
  const test = harness({
    upload: async () => {
      count += 1;
      return rasterRecord({ id: `asset_new_000${count}` });
    },
  });

  await ingestExternalImages(
    [pngFile("first.png"), pngFile("second.png")],
    {
      mode: { kind: "viewport-center", center: { x: 600, y: 600 } },
      pageId: AD_PAGE_ID,
      selectedNodeId: "auto_row_copy",
    },
    test.deps,
  );

  const [first, second] = inserts(test.applied[0].operations);
  assert.deepEqual(
    (first as Extract<Operation, { kind: "insert_node" }>).parent,
    { kind: "node", id: "auto_row_copy" },
  );
  // `[text_headline, group_proof]` → appended after both, then after that.
  assert.equal(insertedAt(first), 2);
  assert.equal(insertedAt(second), 3);
  // The solver owns a managed child's position: no fan-out is written into a
  // transform the next solve overwrites.
  assert.equal(insertedNode(second).transform.x, 0);
  assert.equal(insertedNode(second).transform.y, 0);
});

// ── refusals ───────────────────────────────────────────────────────────────

it("refuses a disallowed type by naming the allowlist, and never uploads it", async () => {
  const test = harness();
  const gif = new File([new Uint8Array(8)], "loop.gif", { type: "image/gif" });

  const outcome = await ingestExternalImages([gif], VIEWPORT_CENTER, test.deps);

  assert.equal(outcome.inserted, 0);
  assert.equal(test.uploaded.length, 0);
  assert.equal(test.applied.length, 0);
  assert.equal(test.errors.length, 1);
  assert.match(test.errors[0], /loop\.gif/);
  assert.match(test.errors[0], /PNG, JPEG, WebP, and SVG/);
});

it("refuses a file over the client byte cap before spending an upload", async () => {
  const test = harness();
  const huge = new File(
    [new Uint8Array(8)],
    "huge.png",
    { type: "image/png" },
  );
  // A real 10 MiB+ buffer would make this suite allocate for nothing; the cap
  // reads `file.size`, so the size is what the case states.
  Object.defineProperty(huge, "size", { value: CLIENT_ASSET_MAX_BYTES + 1 });

  const outcome = await ingestExternalImages([huge], VIEWPORT_CENTER, test.deps);

  assert.equal(outcome.inserted, 0);
  assert.equal(test.uploaded.length, 0);
  assert.equal(test.applied.length, 0);
  assert.match(test.errors[0], /huge\.png/);
  assert.match(test.errors[0], /10 MB/);
});

it("refuses a record that is not READY yet, by its label, and inserts nothing", async () => {
  const test = harness({
    upload: async () =>
      rasterRecord({ label: "still-cooking.png", status: "pending" }),
  });

  const outcome = await ingestExternalImages(
    [pngFile("still-cooking.png")],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
  // The upload DID happen — this refusal is about the record it returned.
  assert.equal(test.uploaded.length, 1);
  assert.equal(test.applied.length, 0);
  assert.equal(test.errors.length, 1);
  assert.match(test.errors[0], /still-cooking\.png/);
});

it("refuses a record with NO readable dimensions rather than guessing a box", async () => {
  const test = harness({
    // R22: both metadata blocks empty — an SVG with no width/height at all.
    upload: async () => vectorRecord({ width: null, height: null }),
  });

  const outcome = await ingestExternalImages(
    [pngFile("dimensionless.png")],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
  assert.equal(test.applied.length, 0);
  assert.match(test.errors[0], /dimensions/);
  assert.match(test.errors[0], /dimensionless\.png/);
});

it("surfaces the server's own refusal detail, verbatim", async () => {
  const test = harness({
    upload: async () => {
      throw new Error("Asset exceeds the 10485760 byte limit");
    },
  });

  const outcome = await ingestExternalImages(
    [pngFile("rejected.png")],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
  assert.equal(test.applied.length, 0);
  assert.equal(test.errors.length, 1);
  assert.match(test.errors[0], /Asset exceeds the 10485760 byte limit/);
  assert.match(test.errors[0], /rejected\.png/);
});

it("applies the SURVIVORS of a mixed gesture and reports the rest in ONE message", async () => {
  const test = harness({
    upload: async (file) =>
      file.name === "good.png"
        ? rasterRecord({ label: "good.png" })
        : Promise.reject(new Error("upstream said no")),
  });

  const outcome = await ingestExternalImages(
    [pngFile("good.png"), pngFile("bad.png")],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 1);
  assert.equal(outcome.refusals.length, 1);
  // R20: one undo frame for the survivors, one message for the refusals — and
  // the survivor's own pair, nothing from the file that never landed.
  assert.equal(test.applied.length, 1);
  assert.equal(test.applied[0].operations.length, 2);
  assert.equal(test.errors.length, 1);
  assert.match(test.errors[0], /bad\.png/);
});

it("joins several refusals into ONE semicolon-separated message", async () => {
  const test = harness();
  const gif = new File([new Uint8Array(8)], "loop.gif", { type: "image/gif" });
  const bmp = new File([new Uint8Array(8)], "old.bmp", { type: "image/bmp" });

  const outcome = await ingestExternalImages(
    [gif, bmp],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.refusals.length, 2);
  assert.equal(test.errors.length, 1);
  assert.match(test.errors[0], /loop\.gif/);
  assert.match(test.errors[0], /old\.bmp/);
  assert.match(test.errors[0], /; /);
});

it("names the files the classifier already dropped, instead of swallowing them", async () => {
  const test = harness();

  const outcome = await ingestExternalImages(
    [pngFile("keeper.png")],
    VIEWPORT_CENTER,
    test.deps,
    ["clip.gif"],
  );

  assert.equal(outcome.inserted, 1);
  assert.equal(outcome.refusals.length, 1);
  assert.match(test.errors[0], /clip\.gif/);
});

// ── the write gate, asked twice ────────────────────────────────────────────

it("refuses BEFORE the upload when the document is not accepting edits", async () => {
  const test = harness({ canApply: () => false });

  const outcome = await ingestExternalImages(
    [pngFile()],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
  assert.equal(test.uploaded.length, 0);
  assert.equal(test.applied.length, 0);
  assert.deepEqual(test.errors, [
    "This document isn't accepting edits right now.",
  ]);
});

it("re-asks the write gate after the upload, and refuses in the same words", async () => {
  let asked = 0;
  const test = harness({
    canApply: () => {
      asked += 1;
      return asked === 1;
    },
  });

  const outcome = await ingestExternalImages(
    [pngFile()],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
  // The upload was spent — which is exactly why the gate is re-asked.
  assert.equal(test.uploaded.length, 1);
  assert.equal(test.applied.length, 0);
  assert.deepEqual(test.errors, [
    "This document isn't accepting edits right now.",
  ]);
});

it("keeps the per-file reasons when the whole gesture bails late", async () => {
  let asked = 0;
  const test = harness({
    canApply: () => {
      asked += 1;
      return asked === 1;
    },
  });
  const gif = new File([new Uint8Array(8)], "loop.gif", { type: "image/gif" });

  const outcome = await ingestExternalImages(
    [pngFile("keeper.png"), gif],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
  // R20 ("each naming the file and reason"): the late bail does not swallow
  // what was already refused. The state that stopped the gesture is stated
  // FIRST — it outranks the allowlist — and the file that was never going to
  // land is still named.
  assert.equal(test.errors.length, 1);
  assert.equal(
    test.errors[0],
    `This document isn't accepting edits right now.; ${outcome.refusals[1]}`,
  );
  assert.equal(outcome.refusals.length, 2);
  assert.match(outcome.refusals[1], /loop\.gif/);
});

it("refuses when the scene went away during the upload", async () => {
  const test = harness({ scene: () => null });

  const outcome = await ingestExternalImages(
    [pngFile()],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
  assert.equal(test.applied.length, 0);
  assert.equal(test.errors.length, 1);
});

it("reports nothing at all for a gesture that carries no files", async () => {
  const test = harness();

  const outcome = await ingestExternalImages([], VIEWPORT_CENTER, test.deps);

  assert.deepEqual(outcome, { inserted: 0, refusals: [] });
  assert.equal(test.errors.length, 0);
  assert.equal(test.applied.length, 0);
  assert.equal(test.uploaded.length, 0);
});

it("reports an engine-refused batch as inserting nothing", async () => {
  const test = harness({ applyOps: () => false });

  const outcome = await ingestExternalImages(
    [pngFile()],
    VIEWPORT_CENTER,
    test.deps,
  );

  assert.equal(outcome.inserted, 0);
});

it("uploads every file of a gesture even when one of them fails", async () => {
  const seen: string[] = [];
  const test = harness({
    upload: async (file) => {
      seen.push(file.name);
      if (file.name === "first.png") {
        throw new Error("nope");
      }
      return rasterRecord();
    },
  });

  await ingestExternalImages(
    [pngFile("first.png"), pngFile("second.png")],
    VIEWPORT_CENTER,
    test.deps,
  );

  // `Promise.allSettled`, not a bail-on-first-rejection loop.
  assert.deepEqual(seen, ["first.png", "second.png"]);
});
