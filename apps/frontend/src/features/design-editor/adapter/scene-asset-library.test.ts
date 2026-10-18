import assert from "node:assert/strict";
import { it } from "node:test";
import type { AssetRecord } from "../engine/scene/contracts";
import {
  composeAssetLibrary,
  filterAssetLibrary,
  kitLibraryEntries,
  registryCategory,
} from "./scene-asset-library";

function rec(id: string, extra: Partial<AssetRecord> = {}): AssetRecord {
  return { id, kind: "raster_image", label: id, status: "ready",
    source: { kind: "uploaded", filename: `${id}.png`, uploaded_by: null }, ...extra };
}
const GENERATED: AssetRecord = rec("gen1", { source: { kind: "generated", request_id: null, model: "x" } });

it("reads logo variants and images out of a brand_kit_json, in kit order, deduped", () => {
  const kit = { assets: {
    logos: { mark: { variants: [{ asset_id: "logo_a" }, { asset_id: "logo_b" }] }, wordmark: null },
    images: { hero: { asset_id: "img_h", role: "hero" }, shot: { asset_id: "img_s", role: "screenshot" }, dup: { asset_id: "logo_a" } },
  } };
  assert.deepEqual(kitLibraryEntries(kit), [
    { assetId: "logo_a", category: "logo" }, { assetId: "logo_b", category: "logo" },
    { assetId: "img_h", category: "background" }, { assetId: "img_s", category: "mockup" },
  ]);
  assert.deepEqual(kitLibraryEntries(null), []);
  assert.deepEqual(kitLibraryEntries({ assets: { fonts: {} } }), []);
});

it("categorizes registry-only records: generated → ai-generated, everything else → upload", () => {
  assert.equal(registryCategory(GENERATED), "ai-generated");
  assert.equal(registryCategory(rec("u")), "upload");
  assert.equal(registryCategory(rec("w", { source: { kind: "website", url: "https://x", captured_at: null } })), "upload");
  // A logo the shared lookup fetched (the agent's fetch_logo, the library's Logo search) is a logo.
  assert.equal(
    registryCategory(rec("l", { source: { kind: "website", url: "https://x", captured_at: null }, tags: ["target-account", "logo-ladder"] })),
    "logo",
  );
});

it("pins kit items first in kit order, then the registry in server order, deduped with the kit winning", () => {
  const registry = [rec("new1"), rec("logo_b", { label: "from registry" }), GENERATED, rec("logo_a")];
  const items = composeAssetLibrary({
    registry,
    kitEntries: [{ assetId: "logo_a", category: "logo" }, { assetId: "logo_b", category: "logo" }],
    inUseAssetId: "new1",
  });
  assert.deepEqual(items.map((i) => [i.record.id, i.pinned, i.category, i.inUse]), [
    ["logo_a", true, "logo", false], ["logo_b", true, "logo", false],
    ["new1", false, "upload", true], ["gen1", false, "ai-generated", false],
  ]);
  assert.equal(items[1].record.label, "from registry"); // the registry's record, the kit's category
});

it("drops archived records and kit entries with no registry record", () => {
  const items = composeAssetLibrary({
    registry: [rec("live"), rec("gone", { status: "archived" })],
    kitEntries: [{ assetId: "missing", category: "logo" }],
    inUseAssetId: null,
  });
  assert.deepEqual(items.map((i) => i.record.id), ["live"]);
});

it("filters by query (label or filename, case-insensitive) and by category", () => {
  const items = composeAssetLibrary({
    registry: [rec("Hero Banner"), rec("team", { media: { filename: "Team-Photo.JPG" } }), GENERATED],
    kitEntries: [], inUseAssetId: null,
  });
  assert.deepEqual(filterAssetLibrary(items, { query: "hero", category: "all" }).map((i) => i.record.id), ["Hero Banner"]);
  assert.deepEqual(filterAssetLibrary(items, { query: "photo", category: "all" }).map((i) => i.record.id), ["team"]);
  assert.deepEqual(filterAssetLibrary(items, { query: "", category: "ai-generated" }).map((i) => i.record.id), ["gen1"]);
  assert.equal(filterAssetLibrary(items, { query: "", category: "all" }).length, 3);
});
