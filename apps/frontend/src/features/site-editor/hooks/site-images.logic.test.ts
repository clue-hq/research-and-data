import assert from "node:assert/strict";
import { test } from "node:test";
import type { AssetRecord } from "@/features/design-editor/engine/scene/contracts";
import {
  EMPTY_SITE_IMAGE_AI,
  IMAGE_PLACEHOLDER_SRC,
  SITE_IMAGE_NOT_SAVED,
  appAssetSrc,
  assetIdForUrl,
  assetStoreUrlOf,
  createSiteImageAiRunner,
  siteImageAiBinding,
  type SiteImageAiDeps,
  type SiteImageAiState,
} from "./site-images.logic";

const A = "a".repeat(64);
const B = "b".repeat(64);
const record = (id: string, digest: string | null, status = "ready") =>
  ({ id, label: id, kind: "raster_image", status, source: { kind: "uploaded" }, media: digest ? { digest: { algorithm: "sha256", value: digest } } : {} }) as unknown as AssetRecord;
const HERO = { componentId: "what", prop: "image", target: "/analysis" };

test("an asset's site url is its sha256 content address, shown in the app through the public passthrough", () => {
  assert.equal(assetStoreUrlOf(record("asset_1", A)), `/asset-store/${A}`);
  assert.equal(assetStoreUrlOf(record("asset_2", null)), null);
  assert.equal(appAssetSrc(`/asset-store/${A}`), `/api/clue/design-public/asset-store/${A}`);
  assert.equal(appAssetSrc(""), IMAGE_PLACEHOLDER_SRC);
  assert.equal(appAssetSrc("https://tracker.example/p.gif"), IMAGE_PLACEHOLDER_SRC);
  assert.equal(assetIdForUrl([record("asset_1", A), record("asset_2", B)], `/asset-store/${B}`), "asset_2");
  assert.equal(assetIdForUrl([record("asset_1", A, "pending")], `/asset-store/${A}`), null);
});

function harness(overrides: Partial<SiteImageAiDeps> = {}) {
  let state: SiteImageAiState = EMPTY_SITE_IMAGE_AI;
  const placed: string[] = [];
  const errors: string[] = [];
  const deps: SiteImageAiDeps = {
    clearMessages: () => undefined,
    currentUrl: () => `/asset-store/${A}`,
    documentId: "doc-1",
    edit: async () => record("asset_edit", B),
    generate: async () => record("asset_gen", B),
    onError: (message) => errors.push(message),
    place: (_target, url) => {
      placed.push(url);
      return true;
    },
    publish: (next) => {
      state = next;
    },
    sourceAssetId: () => "asset_1",
    writable: () => true,
    ...overrides,
  };
  const runner = createSiteImageAiRunner(() => deps);
  return { deps, errors, placed, runner, state: () => state };
}

test("a generated picture is placed straight into the field it was asked for", async () => {
  const h = harness();
  await h.runner.generate(HERO, "a calm clinic reception");
  assert.deepEqual(h.placed, [`/asset-store/${B}`]);
  assert.equal(h.state().generating, false);
});

test("a generation is refused before the spend when the field is not writable", async () => {
  let spent = 0;
  const h = harness({ generate: async () => (spent++, record("asset_gen", B)), writable: () => false });
  await h.runner.generate(HERO, "a calm clinic reception");
  assert.equal(spent, 0);
  assert.deepEqual(h.placed, []);
});

test("a picture paid for on one document is never placed on another", async () => {
  const h = harness();
  const pending = h.runner.generate(HERO, "a calm clinic reception");
  h.deps.documentId = "doc-2";
  await pending;
  assert.deepEqual(h.placed, []);
});

test("a picture without a stored file says so instead of placing a broken url", async () => {
  const h = harness({ generate: async () => record("asset_gen", null) });
  await h.runner.generate(HERO, "x");
  assert.deepEqual(h.errors, [SITE_IMAGE_NOT_SAVED]);
});

test("an edit stages a candidate; accept places it only on its own field; save-as-new notes it", async () => {
  const h = harness();
  await h.runner.edit(HERO, "make it warmer");
  assert.equal(h.state().candidate?.record.id, "asset_edit");
  assert.equal(h.runner.accept({ ...HERO, prop: "logo" }), false, "never onto another field");
  assert.equal(h.runner.accept(HERO), true);
  assert.deepEqual(h.placed, [`/asset-store/${B}`]);
  await h.runner.edit(HERO, "again");
  assert.equal(h.runner.saveAsNew(), true);
  assert.equal(h.state().savedNotice?.message, "Saved asset_edit to the asset library.");
});

test("the binding shows a candidate and a notice only on the field they belong to", async () => {
  const h = harness();
  await h.runner.edit(HERO, "make it warmer");
  const own = siteImageAiBinding({ ai: h.state(), canEdit: true, documentId: "doc-1", runner: h.runner, target: HERO, url: `/asset-store/${A}` });
  const other = siteImageAiBinding({ ai: h.state(), canEdit: true, documentId: "doc-1", runner: h.runner, target: { ...HERO, prop: "logo" }, url: "" });
  assert.equal(own.candidate?.label, "asset_edit");
  assert.equal(own.beforeSrc, `/api/clue/design-public/asset-store/${A}`);
  assert.equal(own.hasImage, true);
  assert.equal(other.candidate, null);
  assert.equal(other.hasImage, false);
});
