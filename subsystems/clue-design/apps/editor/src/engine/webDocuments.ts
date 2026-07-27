/**
 * Website-mode data layer — the two fetch wrappers the /new gate and the
 * /web editor shell compose.
 *
 * Same contract shape as documentStore.ts / brandHub.ts: every call takes an
 * explicit `{ apiBaseUrl }` options object (read at call time from
 * `editorApiBaseUrl()`), wraps `fetch` so it is never stored bare, and throws
 * on any non-2xx so the caller's error branch owns the message. Web documents
 * are a distinct `doc_kind` from scene documents, so this lives beside — not
 * inside — the scene-centric documentStore.
 */

export interface WebDocumentOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

export interface BrandKitRefInput {
  id: string;
  version: number;
}

export interface CreateWebDocumentInput {
  title: string;
  brandKitRef?: BrandKitRefInput;
}

export interface CreatedWebDocument {
  documentId: string;
}

/** One web page in a {@link WebDoc}. P0 only needs identity/route; the tree
 * (`root`/`nodes`) and per-page detail land with generation in the next slice. */
export interface WebPageSummary {
  id: string;
  name: string;
  route: string;
  root?: unknown;
  nodes?: unknown;
}

/** The WebDoc JSON carried under the GET /documents/{id} `scene` key for web
 * documents. Fields are optional so a freshly-created (empty) web document —
 * which has no pages yet — parses through the same type. */
export interface WebDoc {
  schema_version?: number;
  id?: string;
  title?: string;
  theme?: unknown;
  pages?: WebPageSummary[];
  assets?: unknown;
  custom_css?: string;
}

export interface LoadedWebDocument {
  documentId: string;
  /** `"web"` for a website document; anything else means the caller opened a
   * scene document by mistake (the shell shows a wrong-kind message). */
  docKind: string;
  title: string;
  /** The WebDoc JSON (null when the server returned no scene body). */
  webDoc: WebDoc | null;
}

/** Pull the human-facing message off a non-2xx response. FastAPI returns
 * `{ detail: ... }` (string or `{ message }`); fall back to the raw text, then
 * to a status line, so the gate can surface something honest inline. */
async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.clone().json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (detail && typeof detail === "object") {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string" && message.trim()) {
        return message;
      }
    }
  } catch {
    /* not JSON — fall through to text */
  }
  try {
    const text = (await response.text()).trim();
    if (text) {
      return text;
    }
  } catch {
    /* body already consumed / unreadable */
  }
  return fallback;
}

/** Create a website document (`POST /documents` with `doc_kind: "web"`). The
 * server mints the id and seeds an empty WebDoc; the gate stashes the brief and
 * routes to /web/{id}. */
export async function createWebDocument(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  input: CreateWebDocumentInput
): Promise<CreatedWebDocument> {
  const body: Record<string, unknown> = {
    doc_kind: "web",
    title: input.title
  };
  if (input.brandKitRef) {
    body.brand_kit_ref = {
      id: input.brandKitRef.id,
      version: input.brandKitRef.version
    };
  }
  const response = await fetchImpl(new URL("/documents", apiBaseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Website create failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { document?: { id?: unknown } };
  const documentId = payload.document?.id;
  if (typeof documentId !== "string" || documentId.length === 0) {
    throw new Error("Website create returned no document id.");
  }
  return { documentId };
}

/** Load a website document (`GET /documents/{id}`). The `scene` key holds the
 * WebDoc JSON for web documents; `docKind` lets the shell reject a scene
 * document opened at a /web URL. */
export async function fetchWebDocument(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  documentId: string
): Promise<LoadedWebDocument> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? `Document ${documentId} was not found.`
        : `Document fetch failed (HTTP ${response.status}).`
    );
  }
  const payload = (await response.json()) as {
    id?: unknown;
    doc_kind?: unknown;
    title?: unknown;
    scene?: unknown;
  };
  return {
    documentId: typeof payload.id === "string" ? payload.id : documentId,
    docKind: typeof payload.doc_kind === "string" ? payload.doc_kind : "scene",
    title: typeof payload.title === "string" ? payload.title : "Untitled website",
    webDoc:
      payload.scene && typeof payload.scene === "object" ? (payload.scene as WebDoc) : null
  };
}

export interface StartedWebTurn {
  runId: string;
}

/** Kick off a website-mode agent turn (`POST /documents/{id}/web/turns`). The
 * server mints a run id and starts executing async; the caller then subscribes
 * to `GET /agent/runs/{runId}/events` for progress. A 409 (wrong doc kind)
 * surfaces its `detail.code` through the shared error reader. */
export async function startWebTurn(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  documentId: string,
  prompt: string,
  model?: string | null
): Promise<StartedWebTurn> {
  const body: Record<string, unknown> = { prompt };
  if (model != null) {
    body.model = model;
  }
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/turns`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Website turn failed to start (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { run_id?: unknown };
  const runId = payload.run_id;
  if (typeof runId !== "string" || runId.length === 0) {
    throw new Error("Website turn returned no run id.");
  }
  return { runId };
}

/** One diagnostic returned alongside a web render (opaque to the shell — passed
 * through for callers that want to surface them). */
export interface WebRenderResult {
  html: string;
  diagnostics: unknown[];
}

/** Fetch the rendered HTML for a web document
 * (`GET /documents/{id}/web/render?mode=editor&runtime_src=…`). The `html` is a
 * full document intended for a sandboxed `srcdoc` iframe; `runtimeSrc` is the
 * URL the rendered page loads the Tailwind browser runtime from (relative URLs
 * resolve against the parent origin inside a srcdoc iframe). */
export async function fetchWebRenderHtml(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  documentId: string,
  runtimeSrc: string
): Promise<WebRenderResult> {
  const url = new URL(`/documents/${encodeURIComponent(documentId)}/web/render`, apiBaseUrl);
  url.searchParams.set("mode", "editor");
  url.searchParams.set("runtime_src", runtimeSrc);
  const response = await fetchImpl(url);
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Website render failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { html?: unknown; diagnostics?: unknown };
  return {
    html: typeof payload.html === "string" ? payload.html : "",
    diagnostics: Array.isArray(payload.diagnostics) ? payload.diagnostics : []
  };
}

/** True when a web document has any authored content — a page with at least one
 * non-root node. A freshly-created (empty) document has no pages, or pages whose
 * `nodes` map is empty; either way this is false and the shell shows the empty
 * state / auto-sends a queued brief. */
export function webDocumentHasContent(webDoc: WebDoc | null): boolean {
  if (!webDoc || !Array.isArray(webDoc.pages)) {
    return false;
  }
  return webDoc.pages.some((page) => {
    const nodes = page.nodes;
    return Boolean(nodes && typeof nodes === "object" && Object.keys(nodes).length > 0);
  });
}

/** The sessionStorage key the gate stashes a brief under (read once by the web
 * shell). One key per document so parallel tabs never cross briefs. */
export function webPromptStorageKey(documentId: string): string {
  return `lumen.web.prompt.${documentId}`;
}
