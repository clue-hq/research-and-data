import { randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { editorLabelFor, editorLabelFromHost } from "@clue/site-kit/editor-origin";
import type { EditorServerConfig } from "./config";
import { contentSecurityPolicy, SECURITY_HEADERS } from "./csp";

export interface EditorRequest {
  method: string;
  url: string;
  host: string | undefined;
}

export interface EditorResponse {
  status: number;
  headers: Record<string, string>;
  body: string | Uint8Array | ReadableStream<Uint8Array> | null;
}

export interface EditorServerDeps {
  config: EditorServerConfig;
  fetchImpl?: typeof fetch;
  readFile?: (file: string) => Promise<Uint8Array>;
  nonce?: () => string;
}

const ASSET_NAME = /^[A-Za-z0-9._-]+$/;
const SHIM_NAMES = new Set(["react.mjs", "react-jsx-runtime.mjs", "zod.mjs"]);
const SECTION_PATH = /^\/sections\/([0-9a-f]{64})\.(mjs|css)$/;
const ASSET_STORE_PATH = /^\/asset-store\/([0-9a-f]{64})$/;
const TOKEN = /^[A-Za-z0-9._~-]{16,2048}$/;
const SCRIPT = "text/javascript; charset=utf-8";
const STYLE = "text/css; charset=utf-8";
const PLAIN = "text/plain; charset=utf-8";
const ASSET_TYPES: Record<string, string> = { ".css": STYLE, ".js": SCRIPT };
const ASSET_STORE_HEADERS = ["content-type", "cache-control"] as const;

function respond(
  config: EditorServerConfig,
  status: number,
  body: EditorResponse["body"],
  headers: Record<string, string>,
  nonce: string | null = null,
): EditorResponse {
  return {
    body,
    headers: {
      ...SECURITY_HEADERS,
      "content-security-policy": contentSecurityPolicy({ appOrigin: config.appOrigin, nonce }),
      ...headers,
    },
    status,
  };
}

const notFound = (config: EditorServerConfig) =>
  respond(config, 404, "Not found", { "cache-control": "no-store", "content-type": PLAIN });

async function readOrNull(readFile: (file: string) => Promise<Uint8Array>, file: string): Promise<Uint8Array | null> {
  try {
    return await readFile(file);
  } catch {
    return null;
  }
}

export async function handleEditorRequest(request: EditorRequest, deps: EditorServerDeps): Promise<EditorResponse> {
  const { config } = deps;
  const fetchImpl = deps.fetchImpl ?? fetch;
  const readFile = deps.readFile ?? ((file: string) => fs.readFile(file));
  const url = new URL(request.url, "http://editor.invalid");

  if (url.pathname === "/healthz") {
    return respond(config, 200, "ok", { "cache-control": "no-store", "content-type": PLAIN });
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return respond(config, 405, "Method not allowed", { allow: "GET, HEAD", "content-type": PLAIN });
  }
  const label = editorLabelFromHost(request.host, config.editorSuffix);
  if (!label) return notFound(config);

  if (url.pathname === "/" || url.pathname === "/index.html") {
    const nonce = (deps.nonce ?? (() => randomBytes(18).toString("base64url")))();
    const template = await readOrNull(readFile, path.join(config.distDir, "index.html"));
    if (!template) return respond(config, 503, "The editor is not built", { "content-type": PLAIN });
    const html = new TextDecoder()
      .decode(template)
      .replaceAll("%NONCE%", nonce)
      .replaceAll("%APP_ORIGIN%", config.appOrigin);
    return respond(config, 200, html, { "cache-control": "no-store", "content-type": "text/html; charset=utf-8" }, nonce);
  }

  if (url.pathname.startsWith("/assets/")) {
    const name = url.pathname.slice("/assets/".length);
    const type = ASSET_TYPES[path.extname(name)];
    if (!ASSET_NAME.test(name) || !type) return notFound(config);
    const body = await readOrNull(readFile, path.join(config.distDir, "assets", name));
    if (!body) return notFound(config);
    return respond(config, 200, body, {
      "cache-control": "public, max-age=31536000, immutable",
      "content-type": type,
      "cross-origin-resource-policy": "same-origin",
    });
  }

  if (url.pathname.startsWith("/shims/")) {
    const name = url.pathname.slice("/shims/".length);
    if (!SHIM_NAMES.has(name)) return notFound(config);
    const body = await readOrNull(readFile, path.join(config.distDir, "shims", name));
    if (!body) return notFound(config);
    return respond(config, 200, body, {
      "cache-control": "public, max-age=300",
      "content-type": SCRIPT,
      "cross-origin-resource-policy": "same-origin",
    });
  }

  const section = SECTION_PATH.exec(url.pathname);
  if (section) {
    const [, digest, extension] = section;
    const token = url.searchParams.get("t") ?? "";
    if (!TOKEN.test(token)) return notFound(config);
    let upstream: Response;
    try {
      upstream = await fetchImpl(
        `${config.designApiBaseUrl}/site-sections/${digest}.${extension}?t=${encodeURIComponent(token)}`,
        { redirect: "manual" },
      );
    } catch {
      return respond(config, 502, "Section unavailable", { "cache-control": "no-store", "content-type": PLAIN });
    }
    if (upstream.status !== 200) return notFound(config);
    const workspaceId = upstream.headers.get("x-clue-workspace-id");
    // Tenant isolation: the module must belong to the workspace whose label is this origin.
    if (!workspaceId || (await editorLabelFor(workspaceId)) !== label) return notFound(config);
    return respond(config, 200, new Uint8Array(await upstream.arrayBuffer()), {
      "cache-control": "private, no-store",
      "content-type": extension === "mjs" ? SCRIPT : STYLE,
      "cross-origin-resource-policy": "same-origin",
    });
  }

  const asset = ASSET_STORE_PATH.exec(url.pathname);
  if (asset) {
    // The same narrow passthrough as the app's /api/clue/design-public route: GET only, a content
    // address, zero request headers forwarded, two response headers kept.
    const upstream = await fetchImpl(`${config.designApiBaseUrl}/asset-store/${asset[1]}`, { redirect: "manual" });
    const headers: Record<string, string> = { "cross-origin-resource-policy": "same-origin" };
    for (const name of ASSET_STORE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) headers[name] = value;
    }
    return respond(config, upstream.status, upstream.body, headers);
  }

  return notFound(config);
}
