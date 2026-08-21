import assert from "node:assert/strict";
import test from "node:test";
import type { AssetRecord } from "../engine/asset-types";
import type { LoadedWebDocument, WebOperation } from "../engine/webDocuments";
import { HARVESTED_IMAGE_PAGE } from "../adapter/__fixtures__/web-nodes";
import { createReplaceImageHandler } from "./use-replace-image";
import type { WebArtifactSelection } from "./use-web-artifact-selection";
import { inspectorSelectionFor, hydrateInspectorState } from "../adapter/hydrate";

// W4.2 (§1 row 12, lane B): the Replace-image flow — upload, then the proven
// op batch (upsert_asset only when the record is new to the document, one
// batch = one undo step, intent "replace_image").

const RECORD: AssetRecord = {
  id: "asset_fresh",
  label: "banner.png",
  kind: "raster_image",
  status: "ready",
  source: { kind: "uploaded", filename: "banner.png", uploaded_by: null },
};

function file(name = "banner.png"): File {
  return new File([new Uint8Array([1])], name, { type: "image/png" });
}

function loadedDocument(assets: Record<string, unknown>): LoadedWebDocument {
  return {
    documentId: "doc_1",
    docKind: "web",
    title: "Lane B",
    currentVersion: 7,
    undoDepth: 0,
    redoDepth: 0,
    webDoc: {
      pages: [
        {
          id: "page_1",
          root: HARVESTED_IMAGE_PAGE.page_root,
          nodes: HARVESTED_IMAGE_PAGE.nodes,
        },
      ],
      assets,
    },
  } as unknown as LoadedWebDocument;
}

function selectionOf(nodeId: string): WebArtifactSelection {
  const node = HARVESTED_IMAGE_PAGE.nodes[nodeId];
  assert.ok(node, `fixture node ${nodeId} missing`);
  return {
    node,
    nodeInfo: { nodeId } as WebArtifactSelection["nodeInfo"],
    schema: inspectorSelectionFor(node, HARVESTED_IMAGE_PAGE.page_root),
    hydrated: hydrateInspectorState(node, node.classes),
  };
}

function harness({
  assets = {},
  nodeId = "img_plain",
  upload = async () => RECORD,
}: {
  assets?: Record<string, unknown>;
  nodeId?: string | null;
  upload?: (file: File) => Promise<AssetRecord>;
} = {}) {
  const applied: { operations: WebOperation[]; intent?: string }[] = [];
  const errors: string[] = [];
  const uploads: File[] = [];
  // ONE mutable deps object rather than a fresh one per read, so a case can
  // move the document (or the selection) while an upload is in flight — the
  // same shape the ad lane's two hooks are tested through.
  const deps = {
    applyOps: (operations: WebOperation[], intent?: string) =>
      applied.push({ operations, intent }),
    document: loadedDocument(assets),
    onError: (message: string) => errors.push(message),
    selection: nodeId === null ? null : selectionOf(nodeId),
    upload: (candidate: File) => {
      uploads.push(candidate);
      return upload(candidate);
    },
  };
  const handler = createReplaceImageHandler(() => deps);
  return { applied, deps, errors, handler, uploads };
}

test("a fresh asset applies upsert_asset then replace_asset in one batch", async () => {
  const { applied, handler, uploads } = harness();
  await handler(file());

  assert.equal(uploads.length, 1);
  assert.equal(applied.length, 1);
  assert.equal(applied[0].intent, "replace_image");
  assert.deepEqual(applied[0].operations, [
    { kind: "upsert_asset", record: RECORD },
    {
      kind: "replace_asset",
      page_id: "page_1",
      id: "img_plain",
      asset_id: "asset_fresh",
    },
  ]);
});

test("an asset already on the document replaces without an upsert", async () => {
  const { applied, handler } = harness({
    assets: { asset_fresh: { id: "asset_fresh" } },
  });
  await handler(file());

  assert.deepEqual(applied[0].operations, [
    {
      kind: "replace_asset",
      page_id: "page_1",
      id: "img_plain",
      asset_id: "asset_fresh",
    },
  ]);
});

test("a non-image selection (and no selection) never uploads", async () => {
  const button = harness({ nodeId: "cta" });
  await button.handler(file());
  assert.deepEqual(button.uploads, []);
  assert.deepEqual(button.applied, []);
  assert.deepEqual(button.errors, []);

  const none = harness({ nodeId: null });
  await none.handler(file());
  assert.deepEqual(none.uploads, []);
  assert.deepEqual(none.applied, []);
});

test("an upload refusal surfaces inline and applies no operations", async () => {
  const { applied, errors, handler } = harness({
    upload: async () => {
      throw new Error("asset payload exceeds the limit");
    },
  });
  await handler(file());

  assert.deepEqual(applied, []);
  assert.deepEqual(errors, ["asset payload exceeds the limit"]);
});

test("a non-Error rejection still says something honest", async () => {
  const { errors, handler } = harness({
    upload: async () => {
      throw "boom";
    },
  });
  await handler(file());
  assert.equal(errors.length, 1);
  assert.ok(errors[0].length > 0);
});

test("a second file is ignored while the first upload is still in flight", async () => {
  const pending: ((record: AssetRecord) => void)[] = [];
  const { applied, handler, uploads } = harness({
    upload: () =>
      new Promise<AssetRecord>((resolve) => {
        pending.push(resolve);
      }),
  });

  const first = handler(file("first.png"));
  await handler(file("second.png"));
  assert.deepEqual(
    uploads.map((candidate) => candidate.name),
    ["first.png"],
  );

  pending[0](RECORD);
  await first;
  assert.equal(applied.length, 1);

  // The gate reopens once the batch is away.
  void handler(file("third.png"));
  assert.deepEqual(
    uploads.map((candidate) => candidate.name),
    ["first.png", "third.png"],
  );
  pending[1](RECORD);
});

test("AD4.A step 3 review: an upload that lands after the DOCUMENT changed writes nothing", async () => {
  // The same data-integrity defect the ad lane's blocker named, in shipped
  // lane-B code: `applyOps` is bound to the document loaded when this handler
  // captured it, so a user who moved to another document mid-upload had the
  // batch written into the one they LEFT, keyed on a base version that had
  // since moved to the one they were in.
  let release!: (record: AssetRecord) => void;
  const held = new Promise<AssetRecord>((settle) => {
    release = settle;
  });
  const state = harness({ upload: () => held });

  const pending = state.handler(file());
  assert.equal(state.uploads.length, 1, "the upload is in flight");
  state.deps.document = {
    ...state.deps.document,
    documentId: "doc_2",
  } as typeof state.deps.document;
  release(RECORD);
  await pending;

  assert.equal(state.applied.length, 0, "nothing lands in the other document");
  assert.deepEqual(state.errors, [], "and it is a silent refusal, not a failure");
});

test("AD4.A step 3 review: the guard is inert while the document stays put", async () => {
  // The passing path is byte-for-byte what it always was — the guard only
  // decides whether the write happens.
  const state = harness();

  await state.handler(file());

  assert.equal(state.applied.length, 1);
  assert.equal(state.applied[0].intent, "replace_image");
});
