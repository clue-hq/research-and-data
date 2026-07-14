import { describe, expect, it } from "vitest";
import type { AssetDigest, AssetRecord } from "../contracts";
import { assetBytesUrl, sceneAssetBytesUrl } from "../assetLibrary";

/**
 * Canvas image parity: the canvas resolves image bytes from the SCENE's own
 * asset record (content digest → /asset-store/{digest}) — the same source of
 * truth server exports resolve from — so a scene-borne asset renders whether
 * or not anything registered it in the asset library.
 */

const DIGEST = "da2488f9f707198562e3d28ece3ff87654c5e62174748f3607e9808da0d14a1a";
const BASE = "http://127.0.0.1:8002";

function record(overrides: Partial<AssetRecord["media"]> = {}): AssetRecord {
  return {
    id: "asset_img_run_test_0",
    label: "Generated hero",
    kind: "raster_image",
    status: "ready",
    source: { kind: "generated", request_id: "req", model: "mock" },
    media: {
      mime_type: "image/png",
      digest: { algorithm: "sha256", value: DIGEST },
      location: { provider: "local-store", opaque_ref: `sha256/da/${DIGEST}`, url: null },
      ...overrides
    }
  } as AssetRecord;
}

describe("sceneAssetBytesUrl", () => {
  it("resolves a scene record's sha256 digest to the content-addressed endpoint", () => {
    const url = sceneAssetBytesUrl(BASE, { asset_img_run_test_0: record() }, "asset_img_run_test_0");
    expect(url).toBe(`${BASE}/asset-store/${DIGEST}`);
  });

  it("falls back to the registry endpoint when the scene has no record (dangling ref)", () => {
    const url = sceneAssetBytesUrl(BASE, {}, "asset_missing");
    expect(url).toBe(assetBytesUrl(BASE, "asset_missing"));
  });

  it("falls back when the record has no digest", () => {
    const url = sceneAssetBytesUrl(
      BASE,
      { asset_img_run_test_0: record({ digest: null }) },
      "asset_img_run_test_0"
    );
    expect(url).toBe(assetBytesUrl(BASE, "asset_img_run_test_0"));
  });

  it("falls back for non-sha256 or malformed digests (never builds a bad path)", () => {
    for (const digest of [
      { algorithm: "md5", value: DIGEST },
      { algorithm: "sha256", value: DIGEST.toUpperCase() },
      { algorithm: "sha256", value: "../../etc/passwd" },
      { algorithm: "sha256", value: DIGEST.slice(1) }
    ]) {
      const url = sceneAssetBytesUrl(
        BASE,
        { a: record({ digest: digest as AssetDigest }) },
        "a"
      );
      expect(url).toBe(assetBytesUrl(BASE, "a"));
    }
  });
});
