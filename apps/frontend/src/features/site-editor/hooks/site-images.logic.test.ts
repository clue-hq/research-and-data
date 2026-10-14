import assert from "node:assert/strict";
import { test } from "node:test";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import type { AssetRecord } from "@/features/design-editor/engine/scene/contracts";
import {
  EMPTY_SITE_IMAGE_AI,
  IMAGE_PLACEHOLDER_SRC,
  SITE_IMAGE_NOT_PLACED_MOVED,
  SITE_IMAGE_NOT_SAVED,
  appAssetSrc,
  assetIdForUrl,
  assetStoreUrlOf,
  createSiteImageAiRunner,
  fieldsHaveImage,
  imageFieldAi,
  siteImageAiBinding,
  type SiteImageAiDeps,
  type SiteImageAiState,
} from "./site-images.logic";

const A = "a".repeat(64);
const B = "b".repeat(64);
const record = (id: string, digest: string | null, status = "ready") =>
  ({ id, label: id, kind: "raster_image", status, source: { kind: "uploaded" }, media: digest ? { digest: { algorithm: "sha256", value: digest } } : {} }) as unknown as AssetRecord;
const HERO = { componentId: "what", documentId: "doc-1", prop: "image", target: "/analysis" };

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
  assert.equal(imageFieldAi(h.state(), HERO).busy, null);
});

test("a generation is refused before the spend when the field is not writable", async () => {
  let spent = 0;
  const h = harness({ generate: async () => (spent++, record("asset_gen", B)), writable: () => false });
  await h.runner.generate(HERO, "a calm clinic reception");
  assert.equal(spent, 0);
  assert.deepEqual(h.placed, []);
});

test("a picture paid for on one document is never placed on another, and the marketer is told", async () => {
  const h = harness();
  const pending = h.runner.generate(HERO, "a calm clinic reception");
  h.deps.documentId = "doc-2";
  await pending;
  assert.deepEqual(h.placed, []);
  assert.deepEqual(h.errors, [SITE_IMAGE_NOT_PLACED_MOVED], "it is in the library, not lost silently");
});

test("a picture without a stored file says so instead of placing a broken url", async () => {
  const h = harness({ generate: async () => record("asset_gen", null) });
  await h.runner.generate(HERO, "x");
  assert.deepEqual(h.errors, [SITE_IMAGE_NOT_SAVED]);
});

test("an edit stages a candidate; accept places it only on its own field; save-as-new notes it", async () => {
  const h = harness();
  await h.runner.edit(HERO, "make it warmer");
  assert.equal(imageFieldAi(h.state(), HERO).candidate?.id, "asset_edit");
  assert.equal(h.runner.accept({ ...HERO, prop: "logo" }), false, "never onto another field");
  assert.equal(h.runner.accept(HERO), true);
  assert.deepEqual(h.placed, [`/asset-store/${B}`]);
  await h.runner.edit(HERO, "again");
  assert.equal(h.runner.saveAsNew(HERO), true);
  assert.equal(imageFieldAi(h.state(), HERO).savedNotice, "Saved asset_edit to the asset library.");
});

test("the binding shows a candidate and a notice only on the field they belong to", async () => {
  const h = harness();
  await h.runner.edit(HERO, "make it warmer");
  const own = siteImageAiBinding({ ai: h.state(), canEdit: true, runner: h.runner, target: HERO, url: `/asset-store/${A}` });
  const other = siteImageAiBinding({ ai: h.state(), canEdit: true, runner: h.runner, target: { ...HERO, prop: "logo" }, url: "" });
  assert.equal(own.candidate?.label, "asset_edit");
  assert.equal(own.beforeSrc, `/api/clue/design-public/asset-store/${A}`);
  assert.equal(own.hasImage, true);
  assert.equal(other.candidate, null);
  assert.equal(other.hasImage, false);
});

test("an image field anywhere in the selection, even inside a list's items, loads the library", () => {
  const text: FieldDescription = { kind: "text", label: "Heading", name: "heading" };
  const image: FieldDescription = { kind: "image", label: "Image", name: "image" };
  assert.equal(fieldsHaveImage([text, image]), true, "a top-level image");
  assert.equal(
    fieldsHaveImage([text, { item: [{ kind: "text", label: "Name", name: "name" }, { ...image, name: "photo" }], kind: "list", label: "People", name: "people" }]),
    true,
    "an image only inside a list's item",
  );
  assert.equal(fieldsHaveImage([text, { item: [text], kind: "list", label: "Stats", name: "stats" }]), false, "no image at all");
  assert.equal(fieldsHaveImage([]), false);
});

// Review finding S2b-5: one AI edit left un-accepted used to block every other image edit, on every
// site, silently; and a field busy generating made every image field look busy. AI work is now kept
// per field (its site, its component, its prop).
const LOGO = { ...HERO, prop: "logo" };
const OTHER_SITE = { ...HERO, documentId: "doc-2" };

test("S2b-5: a candidate waiting on one field never blocks an edit on another field or another site", async () => {
  const h = harness();
  await h.runner.edit(HERO, "make it warmer");
  await h.runner.edit(LOGO, "make it smaller");
  assert.equal(imageFieldAi(h.state(), LOGO).candidate?.id, "asset_edit", "the second field got its own candidate");
  assert.equal(imageFieldAi(h.state(), HERO).candidate?.id, "asset_edit", "the first one is still waiting");
  h.deps.documentId = "doc-2";
  await h.runner.edit(OTHER_SITE, "brighter");
  assert.equal(imageFieldAi(h.state(), OTHER_SITE).candidate?.id, "asset_edit");
  h.deps.documentId = "doc-1";
  assert.equal(h.runner.accept(HERO), true);
  assert.equal(imageFieldAi(h.state(), LOGO).candidate?.id, "asset_edit", "accepting one leaves the others");
  h.runner.reject(LOGO);
  assert.equal(imageFieldAi(h.state(), LOGO).candidate, null);
  assert.equal(imageFieldAi(h.state(), OTHER_SITE).candidate?.id, "asset_edit");
});

test("S2b-5: a second edit on the SAME field waits for the first to be decided", async () => {
  let edits = 0;
  const h = harness({ edit: async () => (edits++, record("asset_edit", B)) });
  await h.runner.edit(HERO, "make it warmer");
  await h.runner.edit(HERO, "and again");
  assert.equal(edits, 1);
});

test("S2b-5: only the field that is working shows it", async () => {
  let release: (value: AssetRecord) => void = () => undefined;
  const h = harness({ generate: () => new Promise<AssetRecord>((resolve) => (release = resolve)) });
  const pending = h.runner.generate(HERO, "a calm clinic reception");
  const own = siteImageAiBinding({ ai: h.state(), canEdit: true, runner: h.runner, target: HERO, url: "" });
  const other = siteImageAiBinding({ ai: h.state(), canEdit: true, runner: h.runner, target: LOGO, url: "" });
  assert.equal(own.generating, true);
  assert.equal(other.generating, false);
  await h.runner.edit(LOGO, "make it smaller");
  assert.equal(imageFieldAi(h.state(), LOGO).candidate?.id, "asset_edit", "another field works meanwhile");
  release(record("asset_gen", B));
  await pending;
  assert.equal(imageFieldAi(h.state(), HERO).busy, null);
});

