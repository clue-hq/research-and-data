import assert from "node:assert/strict";
import test from "node:test";
import { uploadWebAsset, WebAssetUploadError } from "./assets";

// W4.2 (§1 row 12, lane B): the asset-store upload behind the Replace-image
// flow. The endpoint is reached ONLY through the authenticated BFF mount.

function pngFile(name = "banner.png"): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: "image/png" });
}

test("the upload posts multipart to the BFF assets mount and returns the record", async () => {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const record = { id: "asset_new", label: "banner.png", kind: "raster_image" };
  const fetchImpl = (async (input: unknown, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(
      JSON.stringify({ schema_version: 1, asset: record, deduplicated: false }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as unknown as typeof fetch;

  const uploaded = await uploadWebAsset(pngFile(), { fetchImpl });

  assert.equal(uploaded.id, "asset_new");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/clue/design/assets");
  assert.equal(calls[0].init?.method, "POST");
  // The browser must set the multipart boundary itself — a hand-set
  // content-type would produce an unparseable body server-side.
  assert.equal(calls[0].init?.headers, undefined);
  const body = calls[0].init?.body;
  assert.ok(body instanceof FormData);
  const sent = body.get("file");
  assert.ok(sent instanceof File);
  assert.equal(sent.name, "banner.png");
  assert.equal(body.get("label"), "banner.png");
});

test("a refusal throws the design detail's message and code", async () => {
  const fetchImpl = (async () =>
    new Response(
      JSON.stringify({
        detail: {
          code: "ingest.too_large",
          message: "asset payload exceeds the limit",
          diagnostics: [],
        },
      }),
      { status: 413, headers: { "content-type": "application/json" } },
    )) as unknown as typeof fetch;

  await assert.rejects(
    uploadWebAsset(pngFile(), { fetchImpl }),
    (error: unknown) =>
      error instanceof WebAssetUploadError &&
      error.message === "asset payload exceeds the limit" &&
      error.code === "ingest.too_large" &&
      error.status === 413,
  );
});

test("a FastAPI string detail (and a code-only detail) still names the reason", async () => {
  const stringDetail = (async () =>
    new Response(JSON.stringify({ detail: "license_json is not valid JSON" }), {
      status: 400,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch;
  await assert.rejects(
    uploadWebAsset(pngFile(), { fetchImpl: stringDetail }),
    (error: unknown) =>
      error instanceof WebAssetUploadError &&
      error.message === "license_json is not valid JSON",
  );

  const codeOnly = (async () =>
    new Response(JSON.stringify({ detail: { code: "ingest.unreadable" } }), {
      status: 400,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch;
  await assert.rejects(
    uploadWebAsset(pngFile(), { fetchImpl: codeOnly }),
    (error: unknown) =>
      error instanceof WebAssetUploadError &&
      error.message === "ingest.unreadable" &&
      error.code === "ingest.unreadable",
  );
});

test("a non-JSON refusal keeps a status-shaped message", async () => {
  const fetchImpl = (async () =>
    new Response("<html>gateway</html>", { status: 502 })) as unknown as typeof fetch;
  await assert.rejects(
    uploadWebAsset(pngFile(), { fetchImpl }),
    (error: unknown) =>
      error instanceof WebAssetUploadError &&
      error.message.includes("502") &&
      error.status === 502,
  );
});

test("an OK response without an asset is a refusal, never a silent success", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ schema_version: 1, diagnostics: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch;
  await assert.rejects(
    uploadWebAsset(pngFile(), { fetchImpl }),
    (error: unknown) => error instanceof WebAssetUploadError,
  );
});

test("the default fetch is the global one, called with the BFF path", async () => {
  const original = globalThis.fetch;
  const seen: string[] = [];
  globalThis.fetch = (async (input: unknown) => {
    seen.push(String(input));
    return new Response(
      JSON.stringify({ asset: { id: "asset_default", label: "x", kind: "raster_image" } }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as unknown as typeof fetch;
  try {
    const record = await uploadWebAsset(pngFile("x.png"));
    assert.equal(record.id, "asset_default");
    assert.deepEqual(seen, ["/api/clue/design/assets"]);
  } finally {
    globalThis.fetch = original;
  }
});
