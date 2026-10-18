import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { before, test } from "node:test";
import { editorLabelFor } from "@clue/site-kit/editor-origin";
import { handleEditorRequest, type EditorResponse } from "../src/server/app";
import { readConfig, type EditorServerConfig } from "../src/server/config";
import { contentSecurityPolicy } from "../src/server/csp";

const APP = "http://localhost:3029";
const SUFFIX = "editor.localhost:3129";
const DIGEST = "a".repeat(64);
const TOKEN = "tok_0123456789abcdef";
let LABEL = "";
let HOST = "";
let config: EditorServerConfig;

before(async () => {
  LABEL = await editorLabelFor("ws_123");
  HOST = `${LABEL}.${SUFFIX}`;
  const dist = await fs.mkdtemp(path.join(os.tmpdir(), "site-editor-dist-"));
  await fs.mkdir(path.join(dist, "assets"));
  await fs.mkdir(path.join(dist, "shims"));
  await fs.writeFile(
    path.join(dist, "index.html"),
    '<meta name="clue-app-origin" content="%APP_ORIGIN%"><script type="importmap" nonce="%NONCE%">{}</script>',
  );
  await fs.writeFile(path.join(dist, "assets", "editor-abc123.js"), "console.log(1)");
  await fs.writeFile(path.join(dist, "shims", "react.mjs"), "export default 1");
  config = readConfig(
    { CLUE_APP_ORIGIN: APP, CLUE_SITE_EDITOR_SUFFIX: SUFFIX, LUMEN_API_BASE_URL: "http://127.0.0.1:8019/", PORT: "3129" },
    dist,
  );
});

function get(url: string, extra: Partial<Parameters<typeof handleEditorRequest>[1]> = {}, host: string | undefined = HOST) {
  return handleEditorRequest({ host, method: "GET", url }, { config, nonce: () => "fixed-nonce-0123456789", ...extra });
}

async function text(response: EditorResponse): Promise<string> {
  if (response.body === null) return "";
  if (typeof response.body === "string") return response.body;
  if (response.body instanceof Uint8Array) return new TextDecoder().decode(response.body);
  return new Response(response.body).text();
}

test("configuration refuses a missing or malformed setting", () => {
  const good = { CLUE_APP_ORIGIN: APP, CLUE_SITE_EDITOR_SUFFIX: SUFFIX, LUMEN_API_BASE_URL: "http://127.0.0.1:8019" };
  assert.equal(readConfig(good, "/dist").port, 3120);
  assert.equal(readConfig(good, "/dist").host, "127.0.0.1");
  assert.throws(() => readConfig({ ...good, CLUE_APP_ORIGIN: "" }, "/dist"));
  assert.throws(() => readConfig({ ...good, CLUE_APP_ORIGIN: "http://localhost:3029/path" }, "/dist"));
  assert.throws(() => readConfig({ ...good, LUMEN_API_BASE_URL: "" }, "/dist"));
  assert.throws(() => readConfig({ ...good, CLUE_SITE_EDITOR_SUFFIX: "" }, "/dist"));
});

test("the content security policy is the one D2 and the plan's Global Constraints name", () => {
  const policy = contentSecurityPolicy({ appOrigin: APP, nonce: "abc123def456ghi789" });
  for (const directive of [
    "default-src 'none'",
    "script-src 'self' 'nonce-abc123def456ghi789'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "media-src 'self'",
    "connect-src 'self'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    `frame-ancestors ${APP}`,
  ]) {
    assert.ok(policy.includes(directive), directive);
  }
  for (const forbidden of ["unsafe-eval", "strict-dynamic", "blob:", "*"]) {
    assert.equal(policy.includes(forbidden), false, forbidden);
  }
  assert.equal(contentSecurityPolicy({ appOrigin: APP, nonce: null }).includes("script-src 'self';"), true);
});

test("the page carries a fresh nonce in both its import map and its policy, and the app origin", async () => {
  const response = await get("/");
  assert.equal(response.status, 200);
  assert.equal(response.headers["content-type"], "text/html; charset=utf-8");
  assert.equal(response.headers["cache-control"], "no-store");
  assert.ok(response.headers["content-security-policy"].includes("'nonce-fixed-nonce-0123456789'"));
  assert.equal(response.headers["x-content-type-options"], "nosniff");
  assert.equal(response.headers["referrer-policy"], "no-referrer");
  const html = await text(response);
  assert.ok(html.includes('nonce="fixed-nonce-0123456789"'));
  assert.ok(html.includes(`content="${APP}"`));
});

test("only <label>.<suffix> hosts are served; the health check answers any host", async () => {
  assert.equal((await get("/", {}, `${SUFFIX}`)).status, 404);
  assert.equal((await get("/", {}, `not-a-label.${SUFFIX}`)).status, 404);
  assert.equal((await handleEditorRequest({ host: undefined, method: "GET", url: "/" }, { config })).status, 404);
  assert.equal((await get("/healthz", {}, "railway.internal:3120")).status, 200);
});

test("only GET and HEAD are allowed", async () => {
  const response = await handleEditorRequest({ host: HOST, method: "POST", url: "/" }, { config });
  assert.equal(response.status, 405);
});

test("built assets are immutable; anything outside the asset list is 404", async () => {
  const asset = await get("/assets/editor-abc123.js");
  assert.equal(asset.status, 200);
  assert.equal(asset.headers["content-type"], "text/javascript; charset=utf-8");
  assert.equal(asset.headers["cache-control"], "public, max-age=31536000, immutable");
  assert.equal((await get("/assets/..%2Findex.html")).status, 404);
  assert.equal((await get("/assets/editor-abc123.exe")).status, 404);
  assert.equal((await get("/assets/missing.js")).status, 404);
  assert.equal((await get("/shims/react.mjs")).status, 200);
  assert.equal((await get("/shims/lodash.mjs")).status, 404);
});

test("a section loads only with a token the design API verifies for THIS workspace", async () => {
  const calls: string[] = [];
  const upstream = (workspaceId: string, status = 200) =>
    (async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response("export const schema = {}; export function render() { return null; }", {
        headers: { "content-type": "text/javascript", "x-clue-workspace-id": workspaceId },
        status,
      });
    }) as typeof fetch;

  assert.equal((await get(`/sections/${DIGEST}.mjs`, { fetchImpl: upstream("ws_123") })).status, 404, "no token");
  assert.equal((await get(`/sections/${DIGEST}.mjs?t=short`, { fetchImpl: upstream("ws_123") })).status, 404, "bad token");
  assert.equal(calls.length, 0, "a malformed request never reaches the design API");

  const ok = await get(`/sections/${DIGEST}.mjs?t=${TOKEN}`, { fetchImpl: upstream("ws_123") });
  assert.equal(ok.status, 200);
  assert.equal(ok.headers["content-type"], "text/javascript; charset=utf-8");
  assert.equal(ok.headers["cache-control"], "private, no-store");
  assert.equal(calls.at(-1), `http://127.0.0.1:8019/site-sections/${DIGEST}.mjs?t=${TOKEN}`);

  // Review focus 4 (master plan): workspace B's module never loads on workspace A's origin.
  assert.equal((await get(`/sections/${DIGEST}.mjs?t=${TOKEN}`, { fetchImpl: upstream("ws_other") })).status, 404);
  assert.equal((await get(`/sections/${DIGEST}.mjs?t=${TOKEN}`, { fetchImpl: upstream("ws_123", 403) })).status, 404);

  const css = await get(`/sections/${DIGEST}.css?t=${TOKEN}`, { fetchImpl: upstream("ws_123") });
  assert.equal(css.headers["content-type"], "text/css; charset=utf-8");
});

test("the asset store is proxied headerlessly with only content-type and cache-control kept", async () => {
  const seen: { url: string; init: RequestInit | undefined }[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ init, url: String(input) });
    return new Response("png-bytes", {
      headers: {
        "cache-control": "public, max-age=31536000, immutable",
        "content-type": "image/png",
        "set-cookie": "upstream=must-not-leak",
      },
    });
  }) as typeof fetch;
  const response = await get(`/asset-store/${DIGEST}`, { fetchImpl });
  assert.equal(response.status, 200);
  assert.equal(response.headers["content-type"], "image/png");
  assert.equal(response.headers["set-cookie"], undefined);
  assert.equal(seen[0].url, `http://127.0.0.1:8019/asset-store/${DIGEST}`);
  assert.deepEqual([...new Headers(seen[0].init?.headers ?? {}).keys()], []);
  assert.equal(seen[0].init?.redirect, "manual");
  assert.equal(await text(response), "png-bytes");
  assert.equal((await get("/asset-store/not-a-digest", { fetchImpl })).status, 404);
});

test("an asset-store network failure answers 502 and still carries the editor's policy", async () => {
  const fetchImpl = (async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  const response = await get(`/asset-store/${DIGEST}`, { fetchImpl });
  assert.equal(response.status, 502);
  assert.equal(response.headers["cache-control"], "no-store");
  assert.ok(response.headers["content-security-policy"].includes("default-src 'none'"));
  assert.equal(response.headers["x-content-type-options"], "nosniff");
});

test("S2b-9: the editor refuses to start on the app's own domain", () => {
  const good = { CLUE_APP_ORIGIN: "https://app.cluehq.ai", CLUE_SITE_EDITOR_SUFFIX: "edit.deeppresence.ai", LUMEN_API_BASE_URL: "http://design-api.railway.internal:8010" };
  assert.equal(readConfig(good, "/dist").editorSuffix, "edit.deeppresence.ai");
  assert.throws(() => readConfig({ ...good, CLUE_SITE_EDITOR_SUFFIX: "edit.cluehq.ai" }, "/dist"), /app's/);
  assert.throws(() => readConfig({ ...good, CLUE_SITE_EDITOR_SUFFIX: "cluehq.ai" }, "/dist"), /app's/);
});

// Review K3-7: every workspace's editor shares one registrable domain, so one workspace's agent code
// can set many large cookies there. The editor reads no cookies, and must not answer 431 (blank editor
// in that browser for every workspace) when they arrive.
test("K3-7: a request carrying far more cookies than Node's 16 KB default is still served", async () => {
  const { createEditorServer } = await import("../src/server/server");
  const http = await import("node:http");
  const server = createEditorServer(config);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as { port: number }).port;
  const cookie = Array.from({ length: 50 }, (_, i) => `c${i}=${"x".repeat(4000)}`).join("; ");
  try {
    const status = await new Promise<number>((resolve, reject) => {
      const request = http.request({ host: "127.0.0.1", port, path: "/healthz", headers: { host: HOST, cookie } }, (response) => {
        response.resume();
        resolve(response.statusCode ?? 0);
      });
      request.on("error", reject);
      request.end();
    });
    assert.equal(status, 200);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
