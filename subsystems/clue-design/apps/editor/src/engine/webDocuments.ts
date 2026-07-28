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

/** A single node in a WebDoc page tree. The Rust `WebNode` flattens its `kind`
 * enum onto the node object (serde `#[serde(flatten)]`), so `kind` sits beside
 * `classes`/`children` and the per-kind fields (variant/content, label/href,
 * asset_id/alt, …) appear inline. Fields are optional so any kind parses
 * through the one type; the inspector reads only the ones its kind exposes. */
export interface WebNode {
  id: string;
  kind: string;
  classes: string;
  children?: string[];
  name?: string;
  // text
  variant?: string;
  content?: string;
  // button — link form (href/new_tab) OR command form (command/command_target)
  label?: string;
  href?: string | null;
  new_tab?: boolean;
  command?: string;
  command_target?: string | null;
  // image
  asset_id?: string;
  alt?: string;
  // section
  tag?: string;
  anchor_id?: string | null;
  // icon
  icon?: string;
  // embed
  html?: string;
  // component (branch: dialog/accordion/marquee)
  component?: string;
  aria_label?: string;
  single_open?: boolean;
  default_open?: number;
  speed_s?: number;
  direction?: string;
  pause_on_hover?: boolean;
}

/** One web page in a {@link WebDoc}: identity/route plus the flattened node
 * map (`{ [id]: WebNode }`) the inspector looks selections up in. */
export interface WebPageSummary {
  id: string;
  name: string;
  route: string;
  root?: string;
  nodes?: Record<string, WebNode>;
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
  /** The document's committed version — the `base_version` a manual edit sends
   * for optimistic concurrency (null when the server omitted it). */
  currentVersion: number | null;
  /** Undo/redo depth from the document's stacks (absent stacks → 0) — drives
   * the topbar's disabled states. */
  undoDepth: number;
  redoDepth: number;
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
    current_version?: unknown;
    undo_stack?: unknown;
    redo_stack?: unknown;
  };
  return {
    documentId: typeof payload.id === "string" ? payload.id : documentId,
    docKind: typeof payload.doc_kind === "string" ? payload.doc_kind : "scene",
    title: typeof payload.title === "string" ? payload.title : "Untitled website",
    webDoc:
      payload.scene && typeof payload.scene === "object" ? (payload.scene as WebDoc) : null,
    currentVersion:
      typeof payload.current_version === "number" ? payload.current_version : null,
    undoDepth: Array.isArray(payload.undo_stack) ? payload.undo_stack.length : 0,
    redoDepth: Array.isArray(payload.redo_stack) ? payload.redo_stack.length : 0
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
  model?: string | null,
  targetNodeIds?: string[]
): Promise<StartedWebTurn> {
  const body: Record<string, unknown> = { prompt };
  if (model != null) {
    body.model = model;
  }
  if (targetNodeIds && targetNodeIds.length > 0) {
    body.target_node_ids = targetNodeIds;
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
 * resolve against the parent origin inside a srcdoc iframe).
 *
 * Pass `bridge: { nonce }` (editor mode only) to have the server inject the
 * selection bridge into the document — it draws hover/selection outlines,
 * blocks navigation, and posts nonce-tagged selection events to the parent. */
export async function fetchWebRenderHtml(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  documentId: string,
  runtimeSrc: string,
  bridge?: { nonce?: string }
): Promise<WebRenderResult> {
  const url = new URL(`/documents/${encodeURIComponent(documentId)}/web/render`, apiBaseUrl);
  url.searchParams.set("mode", "editor");
  url.searchParams.set("runtime_src", runtimeSrc);
  if (bridge?.nonce) {
    url.searchParams.set("bridge", "1");
    url.searchParams.set("nonce", bridge.nonce);
  }
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

// ── manual editing: web operations, undo/redo, theme ─────────────────────────

/** The whole-props payload for a `set_node_props` op — the FULL kind object,
 * carrying the same `kind` discriminant as the node it targets (a props edit
 * may not change kind). A button is a union: the legacy link form (href/new_tab)
 * or the command form (an invoker button that opens/closes a dialog). A
 * component is a branch node (dialog/accordion/marquee). */
export type WebButtonLinkProps = {
  kind: "button";
  label: string;
  variant: string;
  href: string;
  new_tab: boolean;
};
export type WebButtonCommandProps = {
  kind: "button";
  label: string;
  variant: string;
  command: "show_modal" | "close";
  command_target: string;
};
export type WebButtonProps = WebButtonLinkProps | WebButtonCommandProps;

export type WebComponentProps =
  | { kind: "component"; component: "dialog"; aria_label?: string }
  | { kind: "component"; component: "accordion"; single_open: boolean; default_open?: number }
  | {
      kind: "component";
      component: "marquee";
      speed_s: number;
      direction: "left" | "right";
      pause_on_hover: boolean;
    };

export type WebNodeProps =
  | { kind: "text"; variant: string; content: string }
  | WebButtonProps
  | { kind: "image"; asset_id: string; alt: string; href?: string | null; new_tab: boolean }
  | { kind: "section"; tag: string; anchor_id?: string | null }
  | { kind: "container" }
  | { kind: "icon"; icon: string }
  | { kind: "embed"; html: string }
  | WebComponentProps;

/** The three actions a button can take — the inspector's "Action" control. */
export type WebButtonAction = "link" | "show_modal" | "close";

/** Read a button node's current action off its flattened props. A `command`
 * of `show_modal`/`close` is the command form; anything else is the link form.
 * (Type guard for code that would otherwise read `node.href` blindly — a
 * command button carries no href.) */
export function webNodeButtonAction(node: WebNode): WebButtonAction {
  if (node.command === "show_modal") {
    return "show_modal";
  }
  if (node.command === "close") {
    return "close";
  }
  return "link";
}

/** True when this props object is the command (invoker) form of a button. */
export function isWebButtonCommandProps(props: WebButtonProps): props is WebButtonCommandProps {
  return "command" in props;
}

/** Build a whole-props button payload for the given action, preserving
 * label + variant across a link↔command switch. The link form reads href +
 * new_tab; the command form reads command_target. This is the single place the
 * inspector shapes a button props edit, so link↔command round-trips are total
 * and testable. */
export function buildWebButtonProps(params: {
  action: WebButtonAction;
  label: string;
  variant: string;
  href: string;
  new_tab: boolean;
  command_target: string;
}): WebButtonProps {
  if (params.action === "link") {
    return {
      kind: "button",
      label: params.label,
      variant: params.variant,
      href: params.href,
      new_tab: params.new_tab
    };
  }
  return {
    kind: "button",
    label: params.label,
    variant: params.variant,
    command: params.action,
    command_target: params.command_target
  };
}

/** A dialog component the button command form can target (its node id, plus the
 * authored name when set). */
export interface WebDialogOption {
  id: string;
  name?: string;
}

/** Every dialog component across the document, in page + node-map order — the
 * target list the button command form's select offers. */
export function listDialogComponents(webDoc: WebDoc | null): WebDialogOption[] {
  if (!webDoc || !Array.isArray(webDoc.pages)) {
    return [];
  }
  const dialogs: WebDialogOption[] = [];
  for (const page of webDoc.pages) {
    const nodes = page.nodes;
    if (!nodes || typeof nodes !== "object") {
      continue;
    }
    for (const node of Object.values(nodes)) {
      if (node.kind === "component" && node.component === "dialog") {
        dialogs.push(node.name ? { id: node.id, name: node.name } : { id: node.id });
      }
    }
  }
  return dialogs;
}

/** A single manual-edit operation (serde snake_case, discriminated by `kind`).
 * v1 exposes the three the inspector + contenteditable commit path emit. */
export type WebOperation =
  | { kind: "set_node_classes"; page_id: string; id: string; classes: string }
  | { kind: "set_text"; page_id: string; id: string; content: string }
  | { kind: "set_node_props"; page_id: string; id: string; props: WebNodeProps };

/** Op builders — the one place a manual-edit payload is shaped, so panels bind
 * fields and call these rather than spelling out op objects inline. */
export function setNodeClassesOp(pageId: string, id: string, classes: string): WebOperation {
  return { kind: "set_node_classes", page_id: pageId, id, classes };
}

export function setTextOp(pageId: string, id: string, content: string): WebOperation {
  return { kind: "set_text", page_id: pageId, id, content };
}

export function setNodePropsOp(pageId: string, id: string, props: WebNodeProps): WebOperation {
  return { kind: "set_node_props", page_id: pageId, id, props };
}

/** One validation diagnostic returned with a 422 invalid-batch rejection. */
export interface WebOperationDiagnostic {
  code?: string;
  message?: string;
  severity?: string;
  [key: string]: unknown;
}

/** A typed failure from {@link applyWebOperations}, distinguishing the two
 * recoverable server rejections the shell reacts to differently:
 *   • `kind === "base_version"` (HTTP 409) — the document moved on; refetch and
 *     retry against the new version.
 *   • `kind === "invalid"` (HTTP 422) — the batch would leave the doc invalid;
 *     `diagnostics[0]` carries the message to surface inline.
 * Anything else is `kind === "other"`. */
export class WebOperationsError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly kind: "base_version" | "invalid" | "other";
  readonly diagnostics: WebOperationDiagnostic[];

  constructor(params: {
    message: string;
    status: number;
    code: string | null;
    kind: "base_version" | "invalid" | "other";
    diagnostics?: WebOperationDiagnostic[];
  }) {
    super(params.message);
    this.name = "WebOperationsError";
    this.status = params.status;
    this.code = params.code;
    this.kind = params.kind;
    this.diagnostics = params.diagnostics ?? [];
  }
}

/** The successful result of an operations batch. */
export interface AppliedWebOperations {
  schemaVersion: number | null;
  currentVersion: number | null;
  diagnostics: WebOperationDiagnostic[];
}

/** Extract `{ code, diagnostics }` from a FastAPI `detail` object (the shape
 * both the 409 and 422 rejections use), tolerating a string detail. */
function readErrorDetail(body: unknown): {
  code: string | null;
  diagnostics: WebOperationDiagnostic[];
  message: string | null;
} {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    return {
      code: typeof record.code === "string" ? record.code : null,
      diagnostics: Array.isArray(record.diagnostics)
        ? (record.diagnostics as WebOperationDiagnostic[])
        : [],
      message: typeof record.message === "string" ? record.message : null
    };
  }
  return {
    code: null,
    diagnostics: [],
    message: typeof detail === "string" ? detail : null
  };
}

/** Apply a manual-edit batch (`POST /documents/{id}/web/operations`). Sends the
 * loaded document version as `base_version` for optimistic concurrency. Throws
 * a {@link WebOperationsError} on 409 (base-version) and 422 (invalid batch) so
 * the caller can react to each distinctly; any other non-2xx throws it as
 * `kind: "other"`. */
export async function applyWebOperations(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  documentId: string,
  operations: WebOperation[],
  options?: { baseVersion?: number | null; intent?: string }
): Promise<AppliedWebOperations> {
  const body: Record<string, unknown> = { operations };
  if (options?.baseVersion != null) {
    body.base_version = options.baseVersion;
  }
  if (options?.intent) {
    body.intent = options.intent;
  }
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/operations`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.clone().json();
    } catch {
      /* not JSON — leave parsed null */
    }
    const detail = readErrorDetail(parsed);
    if (response.status === 409) {
      throw new WebOperationsError({
        message: detail.message ?? "This website was changed elsewhere.",
        status: 409,
        code: detail.code,
        kind: "base_version"
      });
    }
    if (response.status === 422) {
      const first = detail.diagnostics[0];
      throw new WebOperationsError({
        message:
          first?.message ?? detail.message ?? "This edit could not be applied.",
        status: 422,
        code: detail.code,
        kind: "invalid",
        diagnostics: detail.diagnostics
      });
    }
    throw new WebOperationsError({
      message:
        detail.message ?? `Edit failed (HTTP ${response.status}).`,
      status: response.status,
      code: detail.code,
      kind: "other"
    });
  }
  const payload = (await response.json()) as {
    schema_version?: unknown;
    document?: { current_version?: unknown };
    diagnostics?: unknown;
  };
  return {
    schemaVersion: typeof payload.schema_version === "number" ? payload.schema_version : null,
    currentVersion:
      typeof payload.document?.current_version === "number"
        ? payload.document.current_version
        : null,
    diagnostics: Array.isArray(payload.diagnostics)
      ? (payload.diagnostics as WebOperationDiagnostic[])
      : []
  };
}

/** The version a completed undo/redo leaves the document at. */
export interface WebHistoryResult {
  currentVersion: number | null;
}

async function postWebHistory(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  documentId: string,
  path: "undo" | "redo"
): Promise<WebHistoryResult> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/${path}`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}"
    }
  );
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.clone().json();
    } catch {
      /* not JSON */
    }
    const detail = readErrorDetail(parsed);
    // 409 undo.empty / redo.empty is expected when the stack is exhausted; the
    // caller keeps its buttons disabled off the loaded depths, so surface it as
    // a benign typed error rather than crashing.
    throw new WebOperationsError({
      message: detail.message ?? `${path} failed (HTTP ${response.status}).`,
      status: response.status,
      code: detail.code,
      kind: response.status === 409 ? "base_version" : "other"
    });
  }
  const payload = (await response.json()) as { document?: { current_version?: unknown } };
  return {
    currentVersion:
      typeof payload.document?.current_version === "number"
        ? payload.document.current_version
        : null
  };
}

/** Undo the last committed change (`POST /documents/{id}/web/undo`). */
export function webUndo(
  options: WebDocumentOptions,
  documentId: string
): Promise<WebHistoryResult> {
  return postWebHistory(options, documentId, "undo");
}

/** Redo the last undone change (`POST /documents/{id}/web/redo`). */
export function webRedo(
  options: WebDocumentOptions,
  documentId: string
): Promise<WebHistoryResult> {
  return postWebHistory(options, documentId, "redo");
}

/** The resolved theme the inspector reads token swatches + type families from. */
export interface WebTheme {
  /** Token name → CSS color string, e.g. `{ primary: "#0A5", ink: "#111" }`. */
  tokens: Record<string, string>;
  displayFamily: string | null;
  bodyFamily: string | null;
}

/** Fetch the document's resolved theme (`GET /documents/{id}/web/theme`) — the
 * inspector's color swatch grid + type family labels. */
export async function fetchWebTheme(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
  documentId: string
): Promise<WebTheme> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/theme`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Theme fetch failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as {
    theme?: {
      tokens?: unknown;
      display_family?: unknown;
      body_family?: unknown;
    };
  };
  const theme = payload.theme ?? {};
  const tokens: Record<string, string> = {};
  if (theme.tokens && typeof theme.tokens === "object") {
    for (const [name, value] of Object.entries(theme.tokens as Record<string, unknown>)) {
      if (typeof value === "string") {
        tokens[name] = value;
      }
    }
  }
  return {
    tokens,
    displayFamily: typeof theme.display_family === "string" ? theme.display_family : null,
    bodyFamily: typeof theme.body_family === "string" ? theme.body_family : null
  };
}
