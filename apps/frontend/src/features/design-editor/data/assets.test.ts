import assert from "node:assert/strict";
import test from "node:test";
import type { AssetRecord } from "../engine/asset-types";
import {
  IMAGE_ASSET_KINDS,
  listImageAssets,
  LogoSearchError,
  saveSearchedLogo,
  searchLogos,
  uploadWebAsset,
  WebAssetListError,
  WebAssetUploadError,
} from "./assets";

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

// Task 1 (Replace-image / asset-library lane): the registry list read behind the
// picker — every non-archived image kind, through the same authenticated BFF.

function record(id: string, kind: "raster_image" | "vector" | "logo" = "raster_image"): AssetRecord {
  return { id, kind, label: id, status: "ready", source: { kind: "uploaded", filename: `${id}.png`, uploaded_by: null } };
}

function listStub(pages: Record<string, AssetRecord[][]>) {
  const calls: string[] = [];
  const fetchImpl = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    calls.push(`${url.pathname}${url.search}`);
    const kind = url.searchParams.get("kind") ?? "";
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const page = pages[kind]?.[offset / 200] ?? [];
    return new Response(JSON.stringify({ assets: page, count: page.length, limit: 200, offset }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  return { calls, fetchImpl };
}

test("listImageAssets reads every image kind, archived excluded, in kind order then server order", async () => {
  const { calls, fetchImpl } = listStub({
    raster_image: [[record("r1"), record("r2")]],
    vector: [[record("v1", "vector")]],
    logo: [[record("l1", "logo")]],
  });
  const records = await listImageAssets({ fetchImpl });
  assert.deepEqual(records.map((r) => r.id), ["r1", "r2", "v1", "l1"]);
  assert.deepEqual(IMAGE_ASSET_KINDS, ["raster_image", "vector", "logo"]);
  for (const kind of IMAGE_ASSET_KINDS) {
    assert.ok(calls.includes(`/api/clue/design/assets?kind=${kind}&include_archived=false&limit=200&offset=0`), kind);
  }
});

test("listImageAssets pages while a page is full", async () => {
  const full = Array.from({ length: 200 }, (_, i) => record(`r${i}`));
  const { calls, fetchImpl } = listStub({ raster_image: [full, [record("r200")]], vector: [[]], logo: [[]] });
  const records = await listImageAssets({ fetchImpl });
  assert.equal(records.length, 201);
  assert.ok(calls.some((c) => c.includes("kind=raster_image") && c.includes("offset=200")));
  assert.ok(!calls.some((c) => c.includes("kind=raster_image") && c.includes("offset=400")));
});

test("listImageAssets refuses with the API's words on a non-ok response", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ detail: { code: "auth.workspace", message: "workspace header missing" } }), {
      status: 401, headers: { "content-type": "application/json" },
    })) as typeof fetch;
  await assert.rejects(listImageAssets({ fetchImpl }), (error: unknown) => {
    assert.ok(error instanceof WebAssetListError);
    assert.equal(error.message, "workspace header missing");
    assert.equal(error.status, 401);
    return true;
  });
});

/* ── logo search ─────────────────────────────────────────────────────────── */

test("logo search posts the website to the BFF and returns every version", async () => {
  const calls: Array<{ url: string; body: unknown }> = [];
  const logos = [{ asset_id: "asset_ing_1", kind: "Full logo", background: "light", source: "Brandfetch", content_type: "image/svg+xml", preview: "data:image/svg+xml;base64,AA==" }];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), body: JSON.parse(String(init?.body)) });
    return new Response(JSON.stringify({ schema_version: 1, query: "stripe.com", name: "stripe.com", logos }), { status: 200 });
  }) as typeof fetch;
  const result = await searchLogos("stripe.com", { fetchImpl });
  assert.deepEqual(calls, [{ url: "/api/clue/design/assets/logo-search", body: { url: "stripe.com" } }]);
  assert.deepEqual(result, { name: "stripe.com", logos });
});

test("logo search surfaces the server's plain-words refusal", async () => {
  const fetchImpl = (async () => new Response(
    JSON.stringify({ detail: { code: "logo_search.bad_url", message: "Enter a website, like stripe.com." } }),
    { status: 422 },
  )) as typeof fetch;
  await assert.rejects(searchLogos("https://", { fetchImpl }), (error: unknown) =>
    error instanceof LogoSearchError && error.message === "Enter a website, like stripe.com." && error.code === "logo_search.bad_url");
});

test("saving a searched logo sends the website and the clicked version, and returns the record", async () => {
  const calls: unknown[] = [];
  const asset = { id: "asset_ing_1", label: "stripe.com logo", kind: "vector", status: "ready", source: { kind: "website", url: "https://stripe.com", captured_at: null }, tags: ["logo-ladder"] };
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push([String(input), JSON.parse(String(init?.body))]);
    return new Response(JSON.stringify({ schema_version: 1, asset }), { status: 200 });
  }) as typeof fetch;
  const saved = await saveSearchedLogo("stripe.com", "asset_ing_1", { fetchImpl });
  assert.deepEqual(calls, [["/api/clue/design/assets/logo-search/save", { url: "stripe.com", asset_id: "asset_ing_1" }]]);
  assert.equal(saved.id, "asset_ing_1");
});
