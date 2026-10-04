import assert from "node:assert/strict";
import test from "node:test";
import { ClueAuthenticationError } from "@/auth/errors";
import {
  handleDesignProxyRequest,
  type DesignProxyDependencies,
} from "./[...path]/design-proxy-handler";

function dependencies(
  overrides: Partial<{
    authenticationEnabled: boolean;
    originAllowed: boolean;
    workspaceId: () => Promise<string>;
    designApiBaseUrl: string;
    fetchImpl: typeof fetch;
  }> = {},
): DesignProxyDependencies {
  return {
    authenticationEnabled: true,
    originAllowed: true,
    workspaceId: async () => "ws_test",
    designApiBaseUrl: "http://design.internal:8000",
    fetchImpl: async () => Response.json({ ok: true }),
    ...overrides,
  };
}

test("authentication disabled refuses with 503 before any forwarding", async () => {
  const response = await handleDesignProxyRequest(
    new Request("http://localhost/api/clue/design/documents/doc-1"),
    ["documents", "doc-1"],
    dependencies({ authenticationEnabled: false }),
  );
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.error.code, "AUTHENTICATION_NOT_CONFIGURED");
});

test("an upload cannot follow a workspace cookie changed after file selection", async () => {
  let forwarded = false;
  const response = await handleDesignProxyRequest(
    new Request("http://localhost/api/clue/design/assets", {
      method: "POST", headers: {"X-Expected-Workspace-Id": "ws_original"}, body: "file",
    }), ["assets"], dependencies({fetchImpl: async () => {forwarded = true; return Response.json({});}}),
  );
  assert.equal(response.status, 409);
  assert.equal((await response.json()).error.code, "WORKSPACE_CHANGED");
  assert.equal(forwarded, false);
});

test("a disallowed mutation origin is refused with 403", async () => {
  const response = await handleDesignProxyRequest(
    new Request("http://localhost/api/clue/design/documents", { method: "POST" }),
    ["documents"],
    dependencies({ originAllowed: false }),
  );
  assert.equal(response.status, 403);
  const body = await response.json();
  assert.equal(body.error.code, "REQUEST_ORIGIN_FORBIDDEN");
});

test("an unauthenticated request becomes the 401 error envelope", async () => {
  const response = await handleDesignProxyRequest(
    new Request("http://localhost/api/clue/design/documents/doc-1"),
    ["documents", "doc-1"],
    dependencies({
      workspaceId: async () => {
        throw new ClueAuthenticationError("Sign in to continue", {
          code: "AUTHENTICATION_REQUIRED",
          status: 401,
        });
      },
    }),
  );
  assert.equal(response.status, 401);
  const body = await response.json();
  assert.equal(body.error.code, "AUTHENTICATION_REQUIRED");
  assert.equal(body.error.message, "Sign in to continue");
});

test("an authenticated request forwards with the workspace header, never browser credentials", async () => {
  const captured: { url?: string; init?: RequestInit } = {};
  const response = await handleDesignProxyRequest(
    new Request(
      "http://localhost/api/clue/design/documents/doc-1/render?mode=preview",
      {
        headers: {
          accept: "application/json",
          authorization: "Bearer browser-token-must-not-forward",
          cookie: "clue_workspace_id=ws_spoof",
          "x-workspace-id": "ws_spoof",
        },
      },
    ),
    ["documents", "doc-1", "render"],
    dependencies({
      fetchImpl: async (input, init) => {
        captured.url = String(input);
        captured.init = init;
        return Response.json({ ok: true });
      },
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(
    captured.url,
    "http://design.internal:8000/documents/doc-1/render?mode=preview",
  );
  const headers = new Headers(captured.init?.headers);
  assert.equal(headers.get("X-Workspace-Id"), "ws_test");
  assert.equal(headers.get("accept"), "application/json");
  assert.equal(headers.get("authorization"), null);
  assert.equal(headers.get("cookie"), null);
  assert.equal(captured.init?.cache, "no-store");
  assert.equal(captured.init?.redirect, "manual");
});

test("a mutation body rides through and the design API's 4xx passes back", async () => {
  const captured: { body?: unknown; method?: string } = {};
  const response = await handleDesignProxyRequest(
    new Request("http://localhost/api/clue/design/documents/doc-1/operations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ base_version: 3 }),
    }),
    ["documents", "doc-1", "operations"],
    dependencies({
      fetchImpl: async (_input, init) => {
        captured.method = init?.method;
        captured.body = init?.body;
        return Response.json(
          { detail: "stale base_version" },
          { status: 409, headers: { "X-Request-Id": "req-9" } },
        );
      },
    }),
  );
  assert.equal(captured.method, "POST");
  assert.equal(
    new TextDecoder().decode(captured.body as ArrayBuffer),
    JSON.stringify({ base_version: 3 }),
  );
  assert.equal(response.status, 409);
  assert.equal(response.headers.get("X-Request-Id"), "req-9");
  const body = await response.json();
  assert.equal(body.detail, "stale base_version");
});

test("thumbnail PNG bytes, content-type, cache-control, and the version query pass through", async () => {
  const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
  const captured: { url?: string } = {};
  const response = await handleDesignProxyRequest(
    new Request("http://localhost/api/clue/design/documents/doc_1/thumbnail?v=7"),
    ["documents", "doc_1", "thumbnail"],
    dependencies({
      fetchImpl: async (input) => {
        captured.url = String(input);
        return new Response(png, {
          status: 200,
          headers: {
            "content-type": "image/png",
            "cache-control": "private, max-age=31536000, immutable",
          },
        });
      },
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(
    captured.url,
    "http://design.internal:8000/documents/doc_1/thumbnail?v=7",
  );
  assert.equal(response.headers.get("content-type"), "image/png");
  assert.equal(
    response.headers.get("cache-control"),
    "private, max-age=31536000, immutable",
  );
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), png);
});

test("dot segments in the path are refused, not forwarded", async () => {
  await assert.rejects(
    handleDesignProxyRequest(
      new Request("http://localhost/api/clue/design/x"),
      ["..", "internal"],
      dependencies(),
    ),
    /dot segments/,
  );
});

test("an image revalidation forwards If-None-Match and passes a bodiless 304 with its ETag", async () => {
  let forwarded: string | null = null;
  const response = await handleDesignProxyRequest(
    new Request("http://localhost/api/clue/design/assets/a1/bytes", {
      headers: { "If-None-Match": '"abc"' },
    }),
    ["assets", "a1", "bytes"],
    dependencies({
      fetchImpl: async (_input, init) => {
        forwarded = new Headers(init?.headers).get("if-none-match");
        return new Response(null, {
          status: 304,
          headers: { etag: '"abc"', "cache-control": "private, max-age=300" },
        });
      },
    }),
  );
  assert.equal(forwarded, '"abc"');
  assert.equal(response.status, 304);
  assert.equal(response.headers.get("etag"), '"abc"');
  assert.equal(response.headers.get("cache-control"), "private, max-age=300");
  assert.equal(await response.text(), "");
});
