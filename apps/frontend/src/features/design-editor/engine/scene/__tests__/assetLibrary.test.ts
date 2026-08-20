import { describe, expect, it, vi } from "../../__tests__/vitest-shim";
import type { AssetDigest, AssetRecord } from "../contracts";
import {
  fetchAssetRecord,
  publicAssetBytesUrl,
  publicAssetThumbnailUrl,
  sceneAssetBytesUrl
} from "../assetLibrary";

/**
 * Canvas image parity + <img src> serving: every image URL the editor hands
 * to a browser context that cannot send X-Workspace-Id (an `<img src>`, the
 * canvas image cache's bare fetcher) must be content-addressed
 * (`/asset-store/{digest}`) or nothing. A registry URL
 * (`/assets/{id}/bytes|thumbnail`) is workspace-gated and 401s in those
 * contexts, so `null` — "unfetchable", which the image cache models — is the
 * honest answer when no digest exists.
 */

const DIGEST = "da2488f9f707198562e3d28ece3ff87654c5e62174748f3607e9808da0d14a1a";
const THUMB_DIGEST = "0b12045ab033ee9004b1e618ff1d6c8fc4ecccbf94ec33aa22dd7b76f1efa135";
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

  it("returns null when the scene has no record (dangling ref = unfetchable)", () => {
    expect(sceneAssetBytesUrl(BASE, {}, "asset_missing")).toBeNull();
  });

  it("returns null when the record has no digest", () => {
    const url = sceneAssetBytesUrl(
      BASE,
      { asset_img_run_test_0: record({ digest: null }) },
      "asset_img_run_test_0"
    );
    expect(url).toBeNull();
  });

  it("returns null for non-sha256 or malformed digests (never builds a bad path)", () => {
    for (const digest of [
      { algorithm: "md5", value: DIGEST },
      { algorithm: "sha256", value: DIGEST.toUpperCase() },
      { algorithm: "sha256", value: "../../etc/passwd" },
      { algorithm: "sha256", value: DIGEST.slice(1) }
    ]) {
      const url = sceneAssetBytesUrl(BASE, { a: record({ digest: digest as AssetDigest }) }, "a");
      expect(url).toBeNull();
    }
  });
});

describe("publicAssetBytesUrl", () => {
  it("builds the content-addressed URL from media.digest", () => {
    expect(publicAssetBytesUrl(BASE, record())).toBe(`${BASE}/asset-store/${DIGEST}`);
  });

  it("returns null without a usable digest", () => {
    expect(publicAssetBytesUrl(BASE, record({ digest: null }))).toBeNull();
    expect(
      publicAssetBytesUrl(BASE, record({ digest: { algorithm: "md5", value: DIGEST } }))
    ).toBeNull();
    expect(publicAssetBytesUrl(BASE, null)).toBeNull();
  });
});

describe("publicAssetThumbnailUrl", () => {
  it("prefers the thumbnail's own digest", () => {
    const rec = record({
      thumbnail: {
        location: { provider: "local-store", opaque_ref: `sha256/0b/${THUMB_DIGEST}`, url: null },
        mime_type: "image/png",
        digest: { algorithm: "sha256", value: THUMB_DIGEST }
      }
    });
    expect(publicAssetThumbnailUrl(BASE, rec)).toBe(`${BASE}/asset-store/${THUMB_DIGEST}`);
  });

  it("falls back to full bytes when the thumbnail carries no digest", () => {
    const rec = record({
      thumbnail: {
        location: { provider: "local-store", opaque_ref: "not-a-digest", url: null },
        mime_type: "image/png"
      }
    });
    expect(publicAssetThumbnailUrl(BASE, rec)).toBe(`${BASE}/asset-store/${DIGEST}`);
  });

  it("returns null when neither digest exists", () => {
    expect(publicAssetThumbnailUrl(BASE, record({ digest: null }))).toBeNull();
    expect(publicAssetThumbnailUrl(BASE, null)).toBeNull();
  });
});

describe("fetchAssetRecord", () => {
  const jsonResponse = (status: number, body: unknown): Response =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" }
    });

  it("returns the record on 200", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(200, { schema_version: 1, asset: record() }));
    const loaded = await fetchAssetRecord({ apiBaseUrl: BASE, fetchImpl }, "asset_img_run_test_0");
    expect(loaded?.id).toBe("asset_img_run_test_0");
    expect(String(fetchImpl.mock.calls[0][0])).toBe(`${BASE}/assets/asset_img_run_test_0`);
  });

  it("returns null on 404 (unknown asset is a state, not an error)", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(404, {}));
    expect(await fetchAssetRecord({ apiBaseUrl: BASE, fetchImpl }, "asset_ghost")).toBeNull();
  });

  it("throws on other failures", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(500, {}));
    await expect(fetchAssetRecord({ apiBaseUrl: BASE, fetchImpl }, "a")).rejects.toThrow("500");
  });
});
