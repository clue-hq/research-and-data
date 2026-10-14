import assert from "node:assert/strict";
import test from "node:test";
import {
  handlePublicDesignProxyRequest,
  type PublicDesignProxyDependencies,
} from "./[...path]/public-proxy-handler";

function dependencies(
  overrides: Partial<{
    designApiBaseUrl: string;
    fetchImpl: typeof fetch;
  }> = {},
): PublicDesignProxyDependencies {
  return {
    designApiBaseUrl: "http://design.internal:8000",
    fetchImpl: async () => new Response("bytes"),
    ...overrides,
  };
}

const DIGEST = "a".repeat(64);

test("a content-addressed asset forwards headerlessly — no workspace, auth, or cookie", async () => {
  const captured: { url?: string; init?: RequestInit } = {};
  const response = await handlePublicDesignProxyRequest(
    new Request(`http://localhost/api/clue/design-public/asset-store/${DIGEST}`, {
      headers: {
        authorization: "Bearer browser-token-must-not-forward",
        cookie: "clue_workspace_id=ws_spoof",
        "x-workspace-id": "ws_spoof",
      },
    }),
    ["asset-store", DIGEST],
    dependencies({
      fetchImpl: async (input, init) => {
        captured.url = String(input);
        captured.init = init;
        return new Response("bytes");
      },
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(
    captured.url,
    `http://design.internal:8000/asset-store/${DIGEST}`,
  );
  const headers = new Headers(captured.init?.headers ?? {});
  assert.deepEqual([...headers.keys()], []);
  assert.equal(headers.get("x-workspace-id"), null);
  assert.equal(headers.get("authorization"), null);
  assert.equal(headers.get("cookie"), null);
  assert.equal(captured.init?.redirect, "manual");
});

test("the upstream immutable cache-control and content-type pass through, nothing else", async () => {
  const response = await handlePublicDesignProxyRequest(
    new Request(`http://localhost/api/clue/design-public/asset-store/${DIGEST}`),
    ["asset-store", DIGEST],
    dependencies({
      fetchImpl: async () =>
        new Response("bytes", {
          headers: {
            "content-type": "image/png",
            "cache-control": "public, max-age=31536000, immutable",
            "set-cookie": "upstream=must-not-leak",
            "x-workspace-id": "ws_upstream",
          },
        }),
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "image/png");
  assert.equal(
    response.headers.get("cache-control"),
    "public, max-age=31536000, immutable",
  );
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("x-workspace-id"), null);
  assert.equal(await response.text(), "bytes");
});

test("the upstream Access-Control-Allow-Origin passes through — @font-face fetches are CORS-mode from the editor's origin-null sandboxed iframe", async () => {
  const response = await handlePublicDesignProxyRequest(
    new Request(`http://localhost/api/clue/design-public/asset-store/${DIGEST}`),
    ["asset-store", DIGEST],
    dependencies({
      fetchImpl: async () =>
        new Response("bytes", {
          headers: {
            "content-type": "font/woff2",
            "cache-control": "public, max-age=31536000, immutable",
            "access-control-allow-origin": "*",
          },
        }),
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("access-control-allow-origin"), "*");
});

test("a path outside asset-store/<64-hex> is refused with 404 and never forwarded", async () => {
  for (const path of [
    ["font-library"],
    ["assets", "asset-1", "bytes"],
    ["asset-store", "not-a-digest"],
    ["asset-store", DIGEST, "extra"],
    ["asset-store", "A".repeat(64)],
  ]) {
    let forwarded = false;
    const response = await handlePublicDesignProxyRequest(
      new Request(`http://localhost/api/clue/design-public/${path.join("/")}`),
      path,
      dependencies({
        fetchImpl: async () => {
          forwarded = true;
          return new Response("bytes");
        },
      }),
    );
    assert.equal(response.status, 404, `expected 404 for ${path.join("/")}`);
    assert.equal(forwarded, false, `must not forward ${path.join("/")}`);
  }
});

test("a non-GET method is refused with 405 and never forwarded", async () => {
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    let forwarded = false;
    const response = await handlePublicDesignProxyRequest(
      new Request(
        `http://localhost/api/clue/design-public/asset-store/${DIGEST}`,
        { method },
      ),
      ["asset-store", DIGEST],
      dependencies({
        fetchImpl: async () => {
          forwarded = true;
          return new Response("bytes");
        },
      }),
    );
    assert.equal(response.status, 405, `expected 405 for ${method}`);
    assert.equal(forwarded, false, `must not forward ${method}`);
  }
});

test("an unconfigured design API origin refuses with 503 before any forwarding", async () => {
  let forwarded = false;
  const response = await handlePublicDesignProxyRequest(
    new Request(`http://localhost/api/clue/design-public/asset-store/${DIGEST}`),
    ["asset-store", DIGEST],
    dependencies({
      designApiBaseUrl: "",
      fetchImpl: async () => {
        forwarded = true;
        return new Response("bytes");
      },
    }),
  );
  assert.equal(response.status, 503);
  assert.equal(forwarded, false);
  const body = await response.json();
  assert.equal(body.error.code, "DESIGN_API_NOT_CONFIGURED");
  assert.equal(body.error.requestId, null);
});
