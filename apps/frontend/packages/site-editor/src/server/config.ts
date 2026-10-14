import { sameRegistrableDomain } from "@clue/site-kit/editor-origin";

export interface EditorServerConfig {
  port: number;
  host: string;
  appOrigin: string;
  designApiBaseUrl: string;
  editorSuffix: string;
  distDir: string;
}

function requireOrigin(raw: string | undefined, name: string): string {
  const value = (raw ?? "").trim().replace(/\/$/, "");
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute http(s) origin`);
  }
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.origin !== value) {
    throw new Error(`${name} must be an absolute http(s) origin without a path`);
  }
  return parsed.origin;
}

/** Every setting the editor server reads, refused loudly when missing (apps/frontend/packages/site-editor/.env.example). */
export function readConfig(env: Record<string, string | undefined>, distDir: string): EditorServerConfig {
  const designApiBaseUrl = (env.LUMEN_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
  if (!/^https?:\/\/[^/]+/.test(designApiBaseUrl)) throw new Error("LUMEN_API_BASE_URL is required");
  const editorSuffix = (env.CLUE_SITE_EDITOR_SUFFIX ?? "").trim().toLowerCase();
  if (!editorSuffix) throw new Error("CLUE_SITE_EDITOR_SUFFIX is required");
  const port = Number.parseInt(env.PORT ?? "3120", 10);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) throw new Error("PORT must be a TCP port");
  const appOrigin = requireOrigin(env.CLUE_APP_ORIGIN, "CLUE_APP_ORIGIN");
  // Review finding S2b-9: agent-written code runs here; on the app's registrable domain it could set
  // the app's cookies, undoing the separation D2 is built on.
  if (sameRegistrableDomain(editorSuffix, new URL(appOrigin).host)) {
    throw new Error("CLUE_SITE_EDITOR_SUFFIX must not be on the app's own domain (CLUE_APP_ORIGIN)");
  }
  return {
    appOrigin,
    designApiBaseUrl,
    distDir,
    editorSuffix,
    host: (env.HOST ?? "").trim() || "127.0.0.1",
    port,
  };
}
