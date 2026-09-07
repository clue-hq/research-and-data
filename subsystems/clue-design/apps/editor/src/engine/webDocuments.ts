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

import type { AssetRecord } from "./contracts";
import { setElementSizePixels } from "./webClassFacets";
import { webBindingKeyIsAllowed } from "./webRichText";
import { lumenFetch } from "./editorConfig";

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
  content?: RichTextDocument | string;
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
  // section/container background image semantics
  background?: WebBackgroundImage | null;
  // icon
  icon?: string;
  // embed
  html?: string;
  provider?: string;
  url?: string | null;
  // component (branch: dialog/accordion/marquee/nav_menu/carousel/tabs)
  component?: string;
  aria_label?: string;
  single_open?: boolean;
  default_open?: number;
  speed_s?: number;
  direction?: string;
  pause_on_hover?: boolean;
  show_arrows?: boolean;
  autoplay_s?: number;
  default_tab?: number;
  // custom component (leaf): immutable account-scoped artifact pin + typed props
  slug?: string;
  artifact_id?: string;
  props?: Record<string, CustomComponentPropValue>;
  // fragment (leaf, clone-fidelity F1.1): one immutable registry artifact pin
  // plus flat slot values. There is NO inspector UI for a fragment yet — that
  // is Phase F3 — but the fields are named here so a document carrying one
  // round-trips through the editor with its identity intact instead of losing
  // the only thing that says which cloned section it is.
  fragment_id?: string;
  slots?: Record<string, WebFragmentSlotValue>;
  // personalization hedge — carried by the schema, ignored by every v0 path.
  slot_key?: string | null;
}

/** A fragment slot's value: exactly one flat scalar, externally tagged by the
 * engine so an asset slot can never decay into a text slot on the wire. */
export type WebFragmentSlotValue =
  | { text: string }
  | { asset: string }
  | { visible: boolean };

export interface RichTextDocument {
  schema_version: 1;
  blocks: RichTextBlock[];
}

export type RichTextBlock =
  | {
      type: "paragraph";
      alignment?: "start" | "center" | "end" | "justify";
      children: RichTextInline[];
    }
  | {
      type: "list";
      list_type: "unordered" | "ordered";
      items: RichTextListItem[];
    };

export interface RichTextListItem {
  children: RichTextInline[];
  nested?: RichTextBlock[];
}

export interface RichTextMarks {
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
}

export interface RichTextLink {
  href: string;
  new_tab?: boolean;
}

export type RichTextInline =
  | {
      type: "text";
      text: string;
      marks?: RichTextMarks;
      classes?: string;
      link?: RichTextLink;
    }
  | {
      type: "variable";
      key: string;
      fallback: string;
      marks?: RichTextMarks;
      classes?: string;
      link?: RichTextLink;
    }
  | { type: "line_break"; link?: RichTextLink };

export function richTextDocumentHasStructure(
  content: RichTextDocument | string
): boolean {
  return (
    typeof content !== "string" &&
    (content.blocks.length !== 1 || content.blocks[0]?.type !== "paragraph")
  );
}

export function textVariantAllowsStructuredRichText(variant: string): boolean {
  return variant === "body" || variant === "small";
}

export interface WebBackgroundImage {
  asset_id: string;
  fit: "cover" | "contain";
  position: "center" | "top" | "right" | "bottom" | "left";
  scrim?: WebBackgroundScrim | null;
}

export interface WebBackgroundScrim {
  color: "dark" | "light" | "primary" | "accent" | "black" | "white";
  opacity: number;
}

export type CustomComponentPropValue = string | number | boolean;

export interface CustomComponentPropSchema {
  type: "string" | "number" | "boolean";
  enum?: string[];
  default?: CustomComponentPropValue;
}

export interface CustomComponentManifest {
  schema_version: 2;
  meta: { name: string; description: string };
  props_schema: {
    type: "object";
    properties: Record<string, CustomComponentPropSchema>;
    required?: string[];
    additionalProperties: false;
  };
  defaults: Record<string, CustomComponentPropValue>;
  warnings: Array<{
    code?: string;
    severity?: string;
    category?: string;
    message?: string;
  }>;
  browser: {
    format: "esm";
    react: "host-singleton";
    target?: string;
  };
}

export interface CustomComponentArtifact {
  artifact_id: string;
  account_id: string;
  slug: string;
  manifest: CustomComponentManifest;
  provenance: {
    source_revision_id?: string;
    source_version?: number;
    compiler_version?: string;
    [key: string]: unknown;
  };
  created_at?: string;
}

export interface CustomComponentCatalogItem {
  accountId: string;
  slug: string;
  sourceVersion: number;
  artifactCount: number;
  latestArtifact: CustomComponentArtifact;
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
  /** Personalization (P5) passthrough for web docs: this doc is a template
   * (drives the topbar "Template" badge + "Generate for accounts…" action). */
  isTemplate: boolean;
  /** The template this doc was derived from, and the account it was derived
   * for — both null on a plain (non-derived) web doc. */
  templateDocumentId: string | null;
  accountId: string | null;
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
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
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
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
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
    is_template?: unknown;
    template_document_id?: unknown;
    account_id?: unknown;
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
    redoDepth: Array.isArray(payload.redo_stack) ? payload.redo_stack.length : 0,
    isTemplate: payload.is_template === true || payload.is_template === 1,
    templateDocumentId:
      typeof payload.template_document_id === "string" ? payload.template_document_id : null,
    accountId: typeof payload.account_id === "string" ? payload.account_id : null
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
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  documentId: string,
  prompt: string,
  baseVersion: number,
  model?: string | null,
  targetNodeIds?: string[]
): Promise<StartedWebTurn> {
  const body: Record<string, unknown> = { prompt, base_version: baseVersion };
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

export interface WebRunSnapshot {
  /** `queued` (D5): the run row exists but no fleet worker has claimed it yet.
   * Non-terminal — every consumer treats it exactly like `running`. */
  status: "queued" | "running" | "succeeded" | "failed";
  result: Record<string, unknown> | null;
}

/** Fetch a run's durable snapshot (`GET /agent/runs/{runId}`). Used by the
 * turn hook when the SSE stream errors: the DB row distinguishes a transient
 * connection blip (status still `queued`/`running` — let EventSource reconnect)
 * from a run that actually settled or was failed by the server's orphan sweep. */
export async function fetchWebRunSnapshot(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  runId: string
): Promise<WebRunSnapshot> {
  const response = await fetchImpl(
    new URL(`/agent/runs/${encodeURIComponent(runId)}`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Run lookup failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { status?: unknown; result?: unknown };
  const status = payload.status;
  if (
    status !== "queued" &&
    status !== "running" &&
    status !== "succeeded" &&
    status !== "failed"
  ) {
    throw new Error("Run lookup returned an unreadable status.");
  }
  return {
    status,
    result:
      payload.result && typeof payload.result === "object"
        ? (payload.result as Record<string, unknown>)
        : null
  };
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
 * blocks navigation, and posts nonce-tagged selection events to the parent.
 *
 * F5 addendum (2026-09-02): the endpoint is page-aware. `pageId` names which
 * page of a multi-page site to render; OMITTING it is the endpoint's own
 * first-page default, so an absent/empty id sends no `page_id` param at all
 * rather than an empty one (an unknown id is a typed 404 server-side). */
export async function fetchWebRenderHtml(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  documentId: string,
  runtimeSrc: string,
  bridge?: { nonce?: string },
  pageId?: string
): Promise<WebRenderResult> {
  const url = new URL(`/documents/${encodeURIComponent(documentId)}/web/render`, apiBaseUrl);
  url.searchParams.set("mode", "editor");
  url.searchParams.set("runtime_src", runtimeSrc);
  if (pageId) {
    url.searchParams.set("page_id", pageId);
  }
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
    }
  | { kind: "component"; component: "nav_menu" }
  | { kind: "component"; component: "carousel"; show_arrows: boolean; autoplay_s?: number }
  | { kind: "component"; component: "tabs"; default_tab: number };

/** An embed's whole-props payload. The URL form carries the provider (calendly
 * allowlisted, else custom) + url and an empty html; the snippet form carries
 * custom html with no url. */
export type WebEmbedProps = { kind: "embed"; provider?: "calendly" | "custom"; url?: string; html: string };

export type WebCustomComponentProps = {
  kind: "custom_component";
  slug: string;
  artifact_id: string;
  props: Record<string, CustomComponentPropValue>;
};

export type WebNodeProps =
  | { kind: "text"; variant: string; content: RichTextDocument | string }
  | WebButtonProps
  | { kind: "image"; asset_id: string; alt: string; href?: string | null; new_tab: boolean }
  | {
      kind: "section";
      tag: string;
      anchor_id?: string | null;
      background?: WebBackgroundImage | null;
    }
  | {
      kind: "container";
      href?: string | null;
      new_tab: boolean;
      background?: WebBackgroundImage | null;
    }
  | { kind: "icon"; icon: string }
  | WebEmbedProps
  | WebComponentProps
  | WebCustomComponentProps
  | WebFragmentProps;

/** A cloned section's whole-props write (clone-fidelity F3.2). The artifact pin is repeated
 * because SetNodeProps replaces the node's props wholesale — and it is the ONE thing the
 * inspector never varies: editing a frozen artifact's identity would produce a different
 * fragment wearing this one's name (D-F3 / R1: slot VALUES only). */
export interface WebFragmentProps {
  kind: "fragment";
  fragment_id: string;
  slots: Record<string, WebFragmentSlotValue>;
}

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
 * The inspector + contenteditable commit path emit set_node_classes/set_text/
 * set_node_props; the insert palette and structural edits emit the tree ops
 * (insert/move/remove) and asset ops (replace/upsert). */
export type WebOperation =
  | { kind: "set_node_classes"; page_id: string; id: string; classes: string }
  | { kind: "set_text"; page_id: string; id: string; content: string }
  | { kind: "set_rich_text"; page_id: string; id: string; content: RichTextDocument }
  | { kind: "set_node_props"; page_id: string; id: string; props: WebNodeProps }
  | {
      kind: "insert_node";
      page_id: string;
      parent: string;
      index: number;
      nodes: WebNode[];
      root: string;
    }
  | { kind: "move_node"; page_id: string; id: string; new_parent: string; index: number }
  | { kind: "remove_node"; page_id: string; id: string }
  | { kind: "replace_asset"; page_id: string; id: string; asset_id: string }
  | { kind: "upsert_asset"; record: AssetRecord }
  | { kind: "set_slot_key"; page_id: string; id: string; slot_key: string | null }
  | { kind: "set_page_meta"; page_id: string; name?: string; route?: string }
  | {
      kind: "add_page";
      page: WebPageSummary & { root: string; nodes: Record<string, WebNode> };
      index?: number;
    }
  | { kind: "remove_page"; page_id: string };

/** Op builders — the one place a manual-edit payload is shaped, so panels bind
 * fields and call these rather than spelling out op objects inline. */
export function setNodeClassesOp(pageId: string, id: string, classes: string): WebOperation {
  return { kind: "set_node_classes", page_id: pageId, id, classes };
}

export function setTextOp(pageId: string, id: string, content: string): WebOperation {
  return { kind: "set_text", page_id: pageId, id, content };
}

export function setRichTextOp(
  pageId: string,
  id: string,
  content: RichTextDocument
): WebOperation {
  return { kind: "set_rich_text", page_id: pageId, id, content };
}

export function setNodePropsOp(pageId: string, id: string, props: WebNodeProps): WebOperation {
  return { kind: "set_node_props", page_id: pageId, id, props };
}

export function insertNodeOp(
  pageId: string,
  parent: string,
  index: number,
  nodes: WebNode[],
  root: string
): WebOperation {
  return { kind: "insert_node", page_id: pageId, parent, index, nodes, root };
}

export function moveNodeOp(
  pageId: string,
  id: string,
  newParent: string,
  index: number
): WebOperation {
  return { kind: "move_node", page_id: pageId, id, new_parent: newParent, index };
}

export function removeNodeOp(pageId: string, id: string): WebOperation {
  return { kind: "remove_node", page_id: pageId, id };
}

export function replaceAssetOp(pageId: string, id: string, assetId: string): WebOperation {
  return { kind: "replace_asset", page_id: pageId, id, asset_id: assetId };
}

export function upsertAssetOp(record: AssetRecord): WebOperation {
  return { kind: "upsert_asset", record };
}

/** Set (or clear, with `null`) a node's personalization slot key — the derive
 * carrier the account binding substitutes into. A `when:{key}` value gates a
 * Section/Container on binding presence (see {@link slotKeyParts}). */
export function setSlotKeyOp(pageId: string, id: string, slotKey: string | null): WebOperation {
  return { kind: "set_slot_key", page_id: pageId, id, slot_key: slotKey };
}

/** Rename a page and/or repoint its route. Only the keys actually supplied are
 * emitted — the engine's `Option<String>` fields are
 * `skip_serializing_if = "Option::is_none"`, and a `name: undefined` property
 * would still serialize as a present `"name": null`-shaped absence in some
 * encoders, so the object is built conditionally. */
export function setPageMetaOp(
  pageId: string,
  meta: { name?: string; route?: string }
): WebOperation {
  const op: { kind: "set_page_meta"; page_id: string; name?: string; route?: string } = {
    kind: "set_page_meta",
    page_id: pageId
  };
  if (meta.name !== undefined) {
    op.name = meta.name;
  }
  if (meta.route !== undefined) {
    op.route = meta.route;
  }
  return op;
}

/** Add a new, empty page: its root is a single `root_<id>` Container holding no
 * children (every other node kind is inserted later by insert_node). `index`
 * is omitted when absent, which the engine reads as "append". */
export function addPageOp(
  page: { id: string; name: string; route: string },
  index?: number
): WebOperation {
  const root = `root_${page.id}`;
  const op: {
    kind: "add_page";
    page: WebPageSummary & { root: string; nodes: Record<string, WebNode> };
    index?: number;
  } = {
    kind: "add_page",
    page: {
      id: page.id,
      name: page.name,
      route: page.route,
      root,
      nodes: { [root]: { id: root, kind: "container", classes: "", children: [] } }
    }
  };
  if (index !== undefined) {
    op.index = index;
  }
  return op;
}

/** Remove a page. The engine refuses this for a document's last page. */
export function removePageOp(pageId: string): WebOperation {
  return { kind: "remove_page", page_id: pageId };
}

/** Exact mirror of the engine's `route_is_valid` (lumen-web `validate.rs`):
 * `/` or `/seg(/seg)*` where a segment is `[a-z0-9]+(-[a-z0-9]+)*`; no trailing
 * slash; total length <= 128; `manifest.json` is never a segment, and
 * `p-assets` / `asset-store` are never the FIRST one (both are served beside a
 * published site and would shadow it). Kept in lockstep with the Rust so the
 * editor refuses a route before the round trip does. */
export function routeIsValid(route: string): boolean {
  if (route === "/") {
    return true;
  }
  if (route.length > 128 || !route.startsWith("/") || route.endsWith("/")) {
    return false;
  }
  const segments = route.slice(1).split("/");
  const first = segments[0];
  if (first === "p-assets" || first === "asset-store") {
    return false;
  }
  return segments.every(routeSegmentIsValid);
}

function routeSegmentIsValid(segment: string): boolean {
  if (segment.length === 0 || segment === "manifest.json") {
    return false;
  }
  return segment
    .split("-")
    .every((run) => run.length > 0 && /^[a-z0-9]+$/.test(run));
}

/** Which page the shell is looking at, given what the user last asked for.
 *
 * The requested id wins only while the loaded document still HAS that page —
 * an agent turn, an undo, or a remove can retire it underneath the switcher —
 * otherwise the first page does. A document with no pages at all resolves to
 * the empty string, which is what makes the render fetch send no `page_id` and
 * fall back to the endpoint's own first-page default. */
export function resolveActivePageId(
  pages: readonly WebPageSummary[] | undefined,
  requested: string | null | undefined
): string {
  const list = pages ?? [];
  if (requested && list.some((page) => page.id === requested)) {
    return requested;
  }
  return list[0]?.id ?? "";
}

/** Locate a node (and the page it lives on) by id across the loaded WebDoc.
 *
 * CROSS-PAGE ID RULE (F5): node ids are NOT unique across pages — two pages of
 * one site can both carry `hero`. So the ACTIVE page is searched first, and the
 * first-match walk over the remaining pages is only the fallback for a node the
 * active page does not have (a selection that arrived from elsewhere). Without
 * the active-page probe, selecting `hero` on page two would hand the inspector,
 * the move planner, and the rich-text commit page one's node — and every
 * resulting op would carry the wrong `page_id`. */
export function findWebNode(
  webDoc: WebDoc | null,
  nodeId: string | null,
  activePageId: string
): { node: WebNode; pageId: string } | null {
  if (!webDoc || !nodeId || !Array.isArray(webDoc.pages)) {
    return null;
  }
  const active = webDoc.pages.find((page) => page.id === activePageId);
  const onActive = active?.nodes?.[nodeId];
  if (active && onActive) {
    return { node: onActive, pageId: active.id };
  }
  for (const page of webDoc.pages) {
    const node = page.nodes?.[nodeId];
    if (node) {
      return { node, pageId: page.id };
    }
  }
  return null;
}

/** The slot-key charset the engine enforces (`SlotKey` rules, D2): lowercase
 * alnum plus `_ . -`, 1–64 chars. The `when:` presence prefix is NOT part of a
 * key — it is stripped/added around a valid key by the inspector. */
/** True when `key` (without any `when:` prefix) is a legal slot key. */
export function isValidSlotKey(key: string): boolean {
  return webBindingKeyIsAllowed(key);
}

/** Split a stored `slot_key` into its editable key + presence-gate flag. A
 * `when:{key}` value reads as `{ key, whenBound: true }`; a bare key reads as
 * `{ key, whenBound: false }`; an absent/empty value reads as an empty key. */
export function slotKeyParts(slotKey: string | null | undefined): {
  key: string;
  whenBound: boolean;
} {
  if (!slotKey) {
    return { key: "", whenBound: false };
  }
  if (slotKey.startsWith("when:")) {
    return { key: slotKey.slice("when:".length), whenBound: true };
  }
  return { key: slotKey, whenBound: false };
}

/** Compose an editable key + presence-gate flag back into a stored `slot_key`,
 * or `null` when the key is blank (clearing the slot). The `when:` prefix is
 * only applied when `whenBound` — the caller gates that toggle to
 * Section/Container nodes, where the engine allows it. */
export function composeSlotKey(key: string, whenBound: boolean): string | null {
  const trimmed = key.trim();
  if (!trimmed) {
    return null;
  }
  return whenBound ? `when:${trimmed}` : trimmed;
}

// ── structural editing: id minting, tree lookup, insert placement, subtrees ───

const HEX_DIGITS = "0123456789abcdef";

/** Six random hex characters — the mint suffix. */
function hex6(rng: () => number = Math.random): string {
  let out = "";
  for (let i = 0; i < 6; i += 1) {
    out += HEX_DIGITS[Math.floor(rng() * 16)];
  }
  return out;
}

/**
 * Mint a fresh node id `${prefix}_${6 hex}`, re-rolling while the candidate
 * already lives in `existing` (any id in the page, plus ids minted earlier in
 * the same batch). The chosen id is added to `existing` so a caller minting a
 * whole subtree keeps every id distinct. `gen` is injectable for deterministic
 * tests (defaults to random hex).
 */
export function mint(
  prefix: string,
  existing: Set<string>,
  gen: () => string = () => hex6()
): string {
  let candidate = `${prefix}_${gen()}`;
  while (existing.has(candidate)) {
    candidate = `${prefix}_${gen()}`;
  }
  existing.add(candidate);
  return candidate;
}

/** Every node id in a page (the mint collision set). */
export function pageNodeIds(page: WebPageSummary): Set<string> {
  return new Set(Object.keys(page.nodes ?? {}));
}

/** The node whose `children` list contains `id`, or null when `id` is the root
 * / detached. The arena stores no parent pointers, so this scans the map. */
export function parentOfInPage(page: WebPageSummary, id: string): WebNode | null {
  const nodes = page.nodes ?? {};
  for (const node of Object.values(nodes)) {
    if (node.children?.includes(id)) {
      return node;
    }
  }
  return null;
}

/** The top-level section that contains `id` (walking up the arena), or null
 * when `id` is not inside one. Sections may only live at root level, so a
 * Section insertable resolves its placement against this. */
export function enclosingSectionOf(page: WebPageSummary, id: string): WebNode | null {
  const nodes = page.nodes ?? {};
  const rootId = page.root ?? "root";
  let current: WebNode | undefined | null = nodes[id];
  while (current) {
    const parent = parentOfInPage(page, current.id);
    if (parent?.id === rootId) {
      return current;
    }
    current = parent;
  }
  return null;
}

/**
 * Where a palette insert lands, per the placement rule:
 *   • no selection (or a stale id) → end of the page root's children;
 *   • a Section selected → its next sibling (under the root);
 *   • a Container/Component (branch) selected → appended into it;
 *   • a leaf selected → after that leaf, inside its parent.
 * A SECTION insertable overrides all of this (`forSection`): sections may
 * only live at root level, so it lands after the selection's enclosing
 * top-level section (or at the root's end) — never inside a container.
 */
export function deriveInsertPlacement(
  page: WebPageSummary,
  selectedNodeId: string | null,
  forSection = false
): { parent: string; index: number } {
  if (forSection) {
    const rootId = page.root ?? "root";
    const nodes = page.nodes ?? {};
    const rootChildren = nodes[rootId]?.children ?? [];
    const enclosing = selectedNodeId ? enclosingSectionOf(page, selectedNodeId) : null;
    const at = enclosing ? rootChildren.indexOf(enclosing.id) : -1;
    return { parent: rootId, index: at >= 0 ? at + 1 : rootChildren.length };
  }
  const rootId = page.root ?? "root";
  const nodes = page.nodes ?? {};
  const rootChildren = nodes[rootId]?.children ?? [];
  const selected = selectedNodeId ? nodes[selectedNodeId] : undefined;
  if (!selectedNodeId || !selected) {
    return { parent: rootId, index: rootChildren.length };
  }
  if (selected.kind === "section") {
    const parent = parentOfInPage(page, selectedNodeId);
    const parentId = parent?.id ?? rootId;
    const siblings = parent?.children ?? rootChildren;
    const at = siblings.indexOf(selectedNodeId);
    return { parent: parentId, index: at >= 0 ? at + 1 : siblings.length };
  }
  if (selected.kind === "container" || selected.kind === "component") {
    return { parent: selectedNodeId, index: selected.children?.length ?? 0 };
  }
  // A leaf: insert after it inside its parent.
  const parent = parentOfInPage(page, selectedNodeId);
  if (!parent) {
    return { parent: rootId, index: rootChildren.length };
  }
  const at = parent.children?.indexOf(selectedNodeId) ?? -1;
  return { parent: parent.id, index: at >= 0 ? at + 1 : parent.children?.length ?? 0 };
}

/** The insertables the palette offers. Kept beside the subtree builder so the
 * menu labels and the built nodes never drift. */
export type InsertableKind =
  | "section"
  | "row"
  | "column"
  | "text"
  | "button"
  | "icon"
  | "image"
  | "dialog"
  | "accordion"
  | "marquee"
  | "nav_menu"
  | "carousel"
  | "tabs"
  | "embed";

/** The asset an Image insert binds to. */
export interface InsertImageInput {
  assetId: string;
  alt: string;
}

export interface InsertCustomComponentInput {
  slug: string;
  artifactId: string;
  props: Record<string, CustomComponentPropValue>;
}

/** A built subtree ready for an insert_node op: every node (children before or
 * after parents, any order) plus the id of its root. */
export interface BuiltSubtree {
  nodes: WebNode[];
  root: string;
}

/** The wrap-scaffold container classes — a centered content column. Reused by
 * the Section insertable and the root-wrap rule. */
const WRAP_CONTAINER_CLASSES = "mx-auto max-w-[1180px] px-6 py-20 flex flex-col gap-6";

/** Build one insertable's default subtree, minting fresh ids into `existing`.
 * Classes are theme-token-only so the result is lint-clean. */
function buildInsertableSubtree(
  kind: InsertableKind,
  existing: Set<string>,
  gen: () => string,
  image?: InsertImageInput
): BuiltSubtree {
  const id = (prefix: string) => mint(prefix, existing, gen);
  const text = (variant: string, content: string, classes = ""): WebNode => ({
    id: id("txt"),
    kind: "text",
    variant,
    content,
    classes
  });

  switch (kind) {
    case "section": {
      const heading = text("h2", "New section");
      const container: WebNode = {
        id: id("box"),
        kind: "container",
        classes: WRAP_CONTAINER_CLASSES,
        children: [heading.id]
      };
      const section: WebNode = {
        id: id("sec"),
        kind: "section",
        tag: "section",
        classes: "",
        children: [container.id]
      };
      return { nodes: [heading, container, section], root: section.id };
    }
    case "row": {
      const container: WebNode = {
        id: id("row"),
        kind: "container",
        classes: "flex flex-col gap-6 md:flex-row md:items-center",
        children: []
      };
      return { nodes: [container], root: container.id };
    }
    case "column": {
      const container: WebNode = {
        id: id("col"),
        kind: "container",
        classes: "flex flex-col gap-4",
        children: []
      };
      return { nodes: [container], root: container.id };
    }
    case "text": {
      const node = text("body", "New text");
      return { nodes: [node], root: node.id };
    }
    case "button": {
      const node: WebNode = {
        id: id("btn"),
        kind: "button",
        label: "New button",
        variant: "secondary",
        href: "#",
        new_tab: false,
        classes: ""
      };
      return { nodes: [node], root: node.id };
    }
    case "icon": {
      const node: WebNode = {
        id: id("icn"),
        kind: "icon",
        icon: "sparkles",
        classes: "size-6 text-primary"
      };
      return { nodes: [node], root: node.id };
    }
    case "image": {
      const node: WebNode = {
        id: id("img"),
        kind: "image",
        asset_id: image?.assetId ?? "",
        alt: image?.alt ?? "",
        classes: ""
      };
      return { nodes: [node], root: node.id };
    }
    case "dialog": {
      const title = text("h3", "Dialog title");
      const copy = text("body", "Dialog copy.");
      const container: WebNode = {
        id: id("box"),
        kind: "container",
        classes: "p-8 flex flex-col gap-4",
        children: [title.id, copy.id]
      };
      const dialog: WebNode = {
        id: id("dlg"),
        kind: "component",
        component: "dialog",
        aria_label: "Dialog",
        classes: "",
        children: [container.id]
      };
      return { nodes: [title, copy, container, dialog], root: dialog.id };
    }
    case "accordion": {
      const items: WebNode[] = [];
      const itemIds: string[] = [];
      for (let i = 0; i < 2; i += 1) {
        const question = text("h4", "Question");
        const answer = text("body", "Answer.");
        const item: WebNode = {
          id: id("box"),
          kind: "container",
          classes: "flex flex-col gap-2",
          children: [question.id, answer.id]
        };
        items.push(question, answer, item);
        itemIds.push(item.id);
      }
      const accordion: WebNode = {
        id: id("acc"),
        kind: "component",
        component: "accordion",
        single_open: true,
        classes: "",
        children: itemIds
      };
      return { nodes: [...items, accordion], root: accordion.id };
    }
    case "marquee": {
      const one = text("small", "Logo one");
      const two = text("small", "Logo two");
      const marquee: WebNode = {
        id: id("mrq"),
        kind: "component",
        component: "marquee",
        classes: "",
        children: [one.id, two.id]
      };
      return { nodes: [one, two, marquee], root: marquee.id };
    }
    case "nav_menu": {
      const one: WebNode = {
        id: id("btn"),
        kind: "button",
        label: "Item one",
        variant: "link",
        href: "#",
        new_tab: false,
        classes: ""
      };
      const two: WebNode = {
        id: id("btn"),
        kind: "button",
        label: "Item two",
        variant: "link",
        href: "#",
        new_tab: false,
        classes: ""
      };
      const nav: WebNode = {
        id: id("nav"),
        kind: "component",
        component: "nav_menu",
        classes: "",
        children: [one.id, two.id]
      };
      return { nodes: [one, two, nav], root: nav.id };
    }
    case "carousel": {
      const slides: WebNode[] = [];
      const slideIds: string[] = [];
      for (let i = 0; i < 2; i += 1) {
        const heading = text("h4", "Slide title");
        const copy = text("body", "Slide copy.");
        const slide: WebNode = {
          id: id("box"),
          kind: "container",
          classes: "w-72 p-6 rounded-2xl bg-card flex flex-col gap-2",
          children: [heading.id, copy.id]
        };
        slides.push(heading, copy, slide);
        slideIds.push(slide.id);
      }
      const carousel: WebNode = {
        id: id("car"),
        kind: "component",
        component: "carousel",
        show_arrows: true,
        classes: "",
        children: slideIds
      };
      return { nodes: [...slides, carousel], root: carousel.id };
    }
    case "tabs": {
      const items: WebNode[] = [];
      const itemIds: string[] = [];
      const labels = ["Tab one", "Tab two"];
      for (let i = 0; i < 2; i += 1) {
        const label = text("small", labels[i]);
        const panel = text("body", "Panel copy.");
        const item: WebNode = {
          id: id("box"),
          kind: "container",
          classes: "flex flex-col gap-2",
          children: [label.id, panel.id]
        };
        items.push(label, panel, item);
        itemIds.push(item.id);
      }
      const tabs: WebNode = {
        id: id("tab"),
        kind: "component",
        component: "tabs",
        default_tab: 0,
        classes: "",
        children: itemIds
      };
      return { nodes: [...items, tabs], root: tabs.id };
    }
    case "embed": {
      const node: WebNode = {
        id: id("emb"),
        kind: "embed",
        provider: "custom",
        html: "",
        classes: "h-[480px]"
      };
      return { nodes: [node], root: node.id };
    }
    default: {
      const node = text("body", "New text");
      return { nodes: [node], root: node.id };
    }
  }
}

/**
 * Build the insert_node op for one palette choice: derive placement from the
 * current selection, build the subtree, and — when landing directly under the
 * page root with a non-Section insertable — wrap it in a Section+Container
 * scaffold so the root's children stay sections (validation enforces this).
 */
export function buildInsertNodeOp(params: {
  page: WebPageSummary;
  selectedNodeId: string | null;
  kind: InsertableKind;
  image?: InsertImageInput;
  gen?: () => string;
}): WebOperation {
  const { page, selectedNodeId, kind, image } = params;
  const gen = params.gen ?? (() => hex6());
  const existing = pageNodeIds(page);
  let subtree = buildInsertableSubtree(kind, existing, gen, image);
  return placeInsertableSubtree({
    page,
    selectedNodeId,
    forSection: kind === "section",
    subtree,
    existing,
    gen
  });
}

function placeInsertableSubtree(params: {
  page: WebPageSummary;
  selectedNodeId: string | null;
  forSection: boolean;
  subtree: BuiltSubtree;
  existing: Set<string>;
  gen: () => string;
}): WebOperation {
  const { page, selectedNodeId, forSection, existing, gen } = params;
  const placement = deriveInsertPlacement(page, selectedNodeId, forSection);
  const rootId = page.root ?? "root";
  let subtree = params.subtree;

  if (placement.parent === rootId && !forSection) {
    const container: WebNode = {
      id: mint("box", existing, gen),
      kind: "container",
      classes: WRAP_CONTAINER_CLASSES,
      children: [subtree.root]
    };
    const section: WebNode = {
      id: mint("sec", existing, gen),
      kind: "section",
      tag: "section",
      classes: "",
      children: [container.id]
    };
    subtree = { nodes: [...subtree.nodes, container, section], root: section.id };
  }

  return insertNodeOp(page.id, placement.parent, placement.index, subtree.nodes, subtree.root);
}

/** Build one canonical leaf insertion for a picker-selected immutable artifact.
 * Required props without compiler defaults receive a deterministic neutral
 * value so the new node satisfies its generated schema immediately. */
export function initialCustomComponentProps(
  artifact: CustomComponentArtifact
): Record<string, CustomComponentPropValue> {
  const properties = artifact.manifest.props_schema.properties;
  const required = new Set(artifact.manifest.props_schema.required ?? []);
  const values: Record<string, CustomComponentPropValue> = {};
  for (const [name, schema] of Object.entries(properties)) {
    const declaredDefault = artifact.manifest.defaults[name] ?? schema.default;
    if (
      (schema.type === "string" && typeof declaredDefault === "string") ||
      (schema.type === "number" && typeof declaredDefault === "number") ||
      (schema.type === "boolean" && typeof declaredDefault === "boolean")
    ) {
      values[name] = declaredDefault;
      continue;
    }
    if (!required.has(name)) {
      continue;
    }
    if (schema.type === "boolean") {
      values[name] = false;
    } else if (schema.type === "number") {
      values[name] = 0;
    } else {
      values[name] = schema.enum?.[0] ?? "";
    }
  }
  return values;
}

export function buildInsertCustomComponentOp(params: {
  page: WebPageSummary;
  selectedNodeId: string | null;
  component: InsertCustomComponentInput;
  gen?: () => string;
}): WebOperation {
  const gen = params.gen ?? (() => hex6());
  const existing = pageNodeIds(params.page);
  const node: WebNode = {
    id: mint("cc", existing, gen),
    kind: "custom_component",
    classes: "w-full min-h-[160px]",
    slug: params.component.slug,
    artifact_id: params.component.artifactId,
    props: { ...params.component.props }
  };
  return placeInsertableSubtree({
    page: params.page,
    selectedNodeId: params.selectedNodeId,
    forSection: false,
    subtree: { nodes: [node], root: node.id },
    existing,
    gen
  });
}

/**
 * Deep-copy a node's subtree from the page, reminting EVERY id (children arrays
 * remapped through the old→new map), for a Duplicate. Returns the fresh nodes
 * plus the new root id, or null when the node isn't in the page.
 */
export function duplicateSubtree(
  page: WebPageSummary,
  nodeId: string,
  gen: () => string = () => hex6()
): BuiltSubtree | null {
  const nodes = page.nodes ?? {};
  if (!nodes[nodeId]) {
    return null;
  }
  // Collect the subtree (preorder), guarding against a malformed cycle.
  const collected: WebNode[] = [];
  const seen = new Set<string>();
  const stack = [nodeId];
  while (stack.length > 0) {
    const current = stack.pop() as string;
    const node = nodes[current];
    if (!node || seen.has(current)) {
      continue;
    }
    seen.add(current);
    collected.push(node);
    const children = node.children ?? [];
    for (let i = children.length - 1; i >= 0; i -= 1) {
      stack.push(children[i]);
    }
  }
  const existing = new Set(Object.keys(nodes));
  const idMap = new Map<string, string>();
  for (const node of collected) {
    const cut = node.id.indexOf("_");
    const prefix = cut > 0 ? node.id.slice(0, cut) : node.id;
    idMap.set(node.id, mint(prefix, existing, gen));
  }
  const cloned = collected.map((node) => ({
    ...node,
    id: idMap.get(node.id) as string,
    children: node.children ? node.children.map((child) => idMap.get(child) ?? child) : undefined
  }));
  return { nodes: cloned, root: idMap.get(nodeId) as string };
}

/** The MoveNode target index for a move to `boundary` among the current
 * top-level sections: dropping below the source shifts the boundary down one
 * (the source is removed before the insert). See the section drag-reorder. */
export function moveSectionIndex(from: number, boundary: number): number {
  return boundary > from ? boundary - 1 : boundary;
}

export interface CanvasNodeMovePlan {
  operation: WebOperation;
  intent: "reorder_node" | "reparent_node";
}

// `fragment` is movable and is in NEITHER set below — founder ruling D-F3 (Option A, top-level
// reordering only), the same one wired into the bridge's allowlists (`web_bridge.py`). A whole
// cloned band moves up or down the page; it is never manually resized (its proportions ARE the
// clone), never a drop target (an ordinary node dropped inside would be an internal edit of
// somebody else's section), and it stays a leaf, so there is nothing in it to re-lay-out.
// These two sides must agree: the bridge decides which nodes the iframe OFFERS a gesture, this
// decides which gestures become an operation, and a fragment offered a drag the planner then
// refuses is a dead handle.
const CANVAS_MOVABLE_KINDS = new Set([
  "section",
  "container",
  "text",
  "button",
  "image",
  "custom_component",
  "fragment"
]);
const CANVAS_DROP_PARENT_KINDS = new Set(["section", "container"]);
const CANVAS_RESIZABLE_KINDS = new Set([
  "container",
  "text",
  "button",
  "image",
  "custom_component"
]);
const CANVAS_RESIZE_MIN_PX = 16;
const CANVAS_RESIZE_MAX_PX = 10_000;

function subtreeContains(page: WebPageSummary, rootId: string, candidateId: string): boolean {
  const nodes = page.nodes ?? {};
  const pending = [...(nodes[rootId]?.children ?? [])];
  const visited = new Set<string>();
  while (pending.length > 0) {
    const current = pending.pop() as string;
    if (current === candidateId) {
      return true;
    }
    if (visited.has(current)) {
      continue;
    }
    visited.add(current);
    pending.push(...(nodes[current]?.children ?? []));
  }
  return false;
}

/**
 * Turn a generic canvas drop into the one canonical MoveNode contract used by
 * both sibling reorder and cross-container reparent.
 *
 * `index` is measured against the destination's children after the source has
 * been removed. The iframe computes that directly, so same-parent and
 * cross-parent drops share identical semantics. This planner rejects malformed
 * or structurally impossible intents before they reach the checked core.
 */
export function planCanvasNodeMove(
  page: WebPageSummary,
  nodeId: string,
  newParentNodeId: string,
  index: number
): CanvasNodeMovePlan | null {
  const nodes = page.nodes ?? {};
  const rootId = page.root ?? "root";
  const source = nodes[nodeId];
  const newParent = nodes[newParentNodeId];
  const oldParent = source ? parentOfInPage(page, nodeId) : null;

  if (
    !source ||
    !newParent ||
    !oldParent ||
    nodeId === rootId ||
    !CANVAS_MOVABLE_KINDS.has(source.kind) ||
    !Number.isInteger(index) ||
    index < 0
  ) {
    return null;
  }
  if (newParentNodeId === rootId) {
    if (source.kind !== "section") {
      return null;
    }
  } else if (
    source.kind === "section" ||
    !CANVAS_DROP_PARENT_KINDS.has(newParent.kind)
  ) {
    return null;
  }
  if (newParentNodeId === nodeId || subtreeContains(page, nodeId, newParentNodeId)) {
    return null;
  }

  const sameParent = oldParent.id === newParentNodeId;
  const oldIndex = oldParent.children?.indexOf(nodeId) ?? -1;
  const targetLength =
    (newParent.children?.length ?? 0) - (sameParent ? 1 : 0);
  if (oldIndex < 0 || index > targetLength || (sameParent && index === oldIndex)) {
    return null;
  }

  return {
    operation: moveNodeOp(page.id, nodeId, newParentNodeId, index),
    intent: sameParent ? "reorder_node" : "reparent_node"
  };
}

export interface CanvasNodeResizePlan {
  operation: WebOperation;
  intent: "resize_node";
}

/**
 * Turn a bridge resize into a class-backed manual edit. The bridge reports CSS
 * width/height pixels (not transient inline styles); this planner validates
 * node capability and bounds, then rewrites only the base `w-*`/`h-*`/`size-*`
 * utilities. Responsive and unknown classes survive through the partial lens.
 */
export function planCanvasNodeResize(
  page: WebPageSummary,
  nodeId: string,
  widthPx: number | null,
  heightPx: number | null
): CanvasNodeResizePlan | null {
  const node = page.nodes?.[nodeId];
  if (!node || !CANVAS_RESIZABLE_KINDS.has(node.kind)) {
    return null;
  }
  const dimensions = [widthPx, heightPx].filter(
    (value): value is number => value !== null
  );
  if (
    dimensions.length === 0 ||
    dimensions.some(
      (value) =>
        !Number.isFinite(value) ||
        value < CANVAS_RESIZE_MIN_PX ||
        value > CANVAS_RESIZE_MAX_PX
    )
  ) {
    return null;
  }
  const classes = setElementSizePixels(node.classes, { widthPx, heightPx });
  if (classes === node.classes) {
    return null;
  }
  return {
    operation: setNodeClassesOp(page.id, nodeId, classes),
    intent: "resize_node"
  };
}

/** Classify a committed embed URL into whole-props: a calendly.com link →
 * calendly provider; any other https:// URL → custom; a non-https URL is
 * rejected (returns null so the card shows an inline error and does not
 * commit). */
export function classifyEmbedUrl(raw: string): WebEmbedProps | null {
  const url = raw.trim();
  if (!/^https:\/\//i.test(url)) {
    return null;
  }
  if (/^https:\/\/([a-z0-9-]+\.)?calendly\.com\//i.test(url)) {
    return { kind: "embed", provider: "calendly", url, html: "" };
  }
  return { kind: "embed", provider: "custom", url, html: "" };
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
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
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
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
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
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
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

// ── publish + export ─────────────────────────────────────────────────────────

/** The slug charset the server enforces (`^[a-z0-9][a-z0-9-]{2,63}$`): a
 * lowercase alnum lead, then alnum/hyphens, total length 3–64. */
const PUBLISH_SLUG_MAX = 64;

/**
 * A client-side publish-slug suggestion: the slugified title joined to the
 * document id's last four characters, conforming to the server's slug charset
 * (`^[a-z0-9][a-z0-9-]{2,63}$`). Non-alnum runs collapse to a single hyphen and
 * leading/trailing hyphens are trimmed; a title with no latin/digit characters
 * (or an empty one) falls back to `"site"`. The result is clamped to 64 chars.
 * Pure — the publish dialog prefills its input with this and the server
 * re-validates on POST.
 */
export function suggestPublishSlug(title: string, documentId: string): string {
  const slugify = (raw: string): string =>
    raw
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  const base = slugify(title) || "site";
  const suffix = slugify(documentId.slice(-4));
  let slug = suffix ? `${base}-${suffix}` : base;
  if (slug.length > PUBLISH_SLUG_MAX) {
    slug = slug.slice(0, PUBLISH_SLUG_MAX).replace(/-+$/g, "");
  }
  return slug;
}

/** The document's current publish state (`GET /documents/{id}/web/publish`).
 * `published: false` is the unpublished case; the slug/url/version fields carry
 * values only when `published` is true. */
export interface WebPublishState {
  published: boolean;
  slug: string | null;
  url: string | null;
  docVersion: number | null;
  status: string | null;
  previousAvailable: boolean;
  updatedAt: string | null;
  publishId: string | null;
  manifestDigest: string | null;
  packageDigest: string | null;
  htmlDigest: string | null;
}

/** Read the document's publish state. Throws (with the server message) on any
 * non-2xx so the dialog surfaces it inline. */
export async function fetchWebPublishInfo(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  documentId: string
): Promise<WebPublishState> {
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/publish`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Publish status failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as {
    published?: unknown;
    slug?: unknown;
    url?: unknown;
    doc_version?: unknown;
    status?: unknown;
    previous_available?: unknown;
    updated_at?: unknown;
    publish_id?: unknown;
    manifest_digest?: unknown;
    package_digest?: unknown;
    html_digest?: unknown;
  };
  return {
    published: payload.published === true,
    slug: typeof payload.slug === "string" ? payload.slug : null,
    url: typeof payload.url === "string" ? payload.url : null,
    docVersion: typeof payload.doc_version === "number" ? payload.doc_version : null,
    status: typeof payload.status === "string" ? payload.status : null,
    previousAvailable: payload.previous_available === true,
    updatedAt: typeof payload.updated_at === "string" ? payload.updated_at : null,
    publishId: typeof payload.publish_id === "string" ? payload.publish_id : null,
    manifestDigest: typeof payload.manifest_digest === "string" ? payload.manifest_digest : null,
    packageDigest: typeof payload.package_digest === "string" ? payload.package_digest : null,
    htmlDigest: typeof payload.html_digest === "string" ? payload.html_digest : null
  };
}

/** The result of a `POST /documents/{id}/web/publish`. */
export interface WebPublishResult {
  schemaVersion: number | null;
  slug: string;
  url: string;
  docVersion: number | null;
  runtimeVersion: string | null;
  previousAvailable: boolean;
  publishId: string | null;
  manifestDigest: string | null;
  packageDigest: string | null;
  htmlDigest: string | null;
}

/** Publish (or republish) a website (`POST /documents/{id}/web/publish`). Pass
 * the desired slug; omit it to let the server keep the current one. A 422 (bad
 * slug) or 409 (slug taken by another document) throws with the server's
 * message so the dialog can surface it inline. */
export async function publishWebDocument(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  documentId: string,
  slug?: string
): Promise<WebPublishResult> {
  const body: Record<string, unknown> = {};
  if (slug != null && slug.length > 0) {
    body.slug = slug;
  }
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/publish`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Publish failed (HTTP ${response.status}).`));
  }
  const payload = (await response.json()) as {
    schema_version?: unknown;
    slug?: unknown;
    url?: unknown;
    doc_version?: unknown;
    runtime_version?: unknown;
    previous_available?: unknown;
    publish_id?: unknown;
    manifest_digest?: unknown;
    package_digest?: unknown;
    html_digest?: unknown;
  };
  return {
    schemaVersion: typeof payload.schema_version === "number" ? payload.schema_version : null,
    slug: typeof payload.slug === "string" ? payload.slug : "",
    url: typeof payload.url === "string" ? payload.url : "",
    docVersion: typeof payload.doc_version === "number" ? payload.doc_version : null,
    runtimeVersion:
      typeof payload.runtime_version === "string"
        ? payload.runtime_version
        : typeof payload.runtime_version === "number"
          ? String(payload.runtime_version)
          : null,
    previousAvailable: payload.previous_available === true,
    publishId: typeof payload.publish_id === "string" ? payload.publish_id : null,
    manifestDigest: typeof payload.manifest_digest === "string" ? payload.manifest_digest : null,
    packageDigest: typeof payload.package_digest === "string" ? payload.package_digest : null,
    htmlDigest: typeof payload.html_digest === "string" ? payload.html_digest : null
  };
}

/** The result of an unpublish (`DELETE /web/publishes/{slug}`). */
export interface WebUnpublishResult {
  slug: string;
  status: string;
}

/** Take a published site offline (`DELETE /web/publishes/{slug}`). */
export async function unpublishWebSite(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  slug: string
): Promise<WebUnpublishResult> {
  const response = await fetchImpl(
    new URL(`/web/publishes/${encodeURIComponent(slug)}`, apiBaseUrl),
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Unpublish failed (HTTP ${response.status}).`));
  }
  const payload = (await response.json()) as { slug?: unknown; status?: unknown };
  return {
    slug: typeof payload.slug === "string" ? payload.slug : slug,
    status: typeof payload.status === "string" ? payload.status : "unpublished"
  };
}

/** The result of a rollback (`POST /web/publishes/{slug}/rollback`). */
export interface WebRollbackResult {
  slug: string;
  docVersion: number | null;
  status: string;
}

/** Roll a published site back to its previous version
 * (`POST /web/publishes/{slug}/rollback`). A 409 (no previous version) throws
 * with the server message. */
export async function rollbackWebPublish(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  slug: string
): Promise<WebRollbackResult> {
  const response = await fetchImpl(
    new URL(`/web/publishes/${encodeURIComponent(slug)}/rollback`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}"
    }
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Roll back failed (HTTP ${response.status}).`));
  }
  const payload = (await response.json()) as {
    slug?: unknown;
    doc_version?: unknown;
    status?: unknown;
  };
  return {
    slug: typeof payload.slug === "string" ? payload.slug : slug,
    docVersion: typeof payload.doc_version === "number" ? payload.doc_version : null,
    status: typeof payload.status === "string" ? payload.status : "published"
  };
}

// ── personalization (P5): accounts, templates, derive, batch ─────────────────

/** The slugified base of a title — the same lead the publish slug uses, without
 * the document-id suffix. Prefills the batch dialog's slug-base input; the
 * server appends `-{account-slug}` per variant. Falls back to `"site"`. */
export function suggestSlugBase(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "site"
  );
}

/** An account record (D3). `data` is the flat string→string custom-var map that
 * becomes `account.<key>` bindings; `notes` are agent-context only (never a
 * substitution value). */
export interface WebAccount {
  accountId: string;
  name: string;
  domain: string | null;
  logoAssetId: string | null;
  data: Record<string, string>;
  notes: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

/** The create/update payload for an account. `accountId` is server-minted when
 * absent on create; a PATCH sends only the changed fields. */
export interface WebAccountInput {
  accountId?: string;
  name?: string;
  domain?: string | null;
  logoAssetId?: string | null;
  data?: Record<string, string>;
  notes?: string | null;
}

/** One text-valued personalization variable the rich-text toolbar may insert.
 * Asset values (currently `account.logo`) are deliberately absent: inline
 * variable nodes derive text only. `example` is an account-backed suggestion,
 * never an implicit fallback — the human must keep visible fallback copy. */
export interface WebRichTextVariable {
  key: string;
  label: string;
  example: string | null;
}

/** Build the variable catalog from the exact account model used by derivation.
 * A derived page sees only its own account. A template/accountless page sees
 * the union of currently persisted account text fields. With no applicable
 * account rows the result is empty, allowing the toolbar to explain why the
 * variable control is disabled. */
export function buildWebRichTextVariableCatalog(
  accounts: WebAccount[],
  accountId: string | null
): WebRichTextVariable[] {
  const applicable = accountId
    ? accounts.filter((account) => account.accountId === accountId)
    : accounts;
  if (applicable.length === 0) {
    return [];
  }

  const examples = new Map<string, string>();
  const add = (key: string, value: string | null | undefined) => {
    const trimmed = value?.trim() ?? "";
    if (isValidSlotKey(key) && !examples.has(key)) {
      examples.set(key, trimmed);
    } else if (isValidSlotKey(key) && !examples.get(key) && trimmed) {
      examples.set(key, trimmed);
    }
  };

  for (const account of applicable) {
    add("account.name", account.name);
    if (account.domain) {
      add("account.domain", account.domain);
    }
    for (const [name, value] of Object.entries(account.data)) {
      add(`account.${name}`, value);
    }
  }

  return Array.from(examples, ([key, example]) => ({
    key,
    label: key
      .replace(/^account\./, "")
      .split(/[._-]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" "),
    example: example || null
  })).sort((left, right) => left.key.localeCompare(right.key));
}

/** Read one account row from a server payload (snake_case → camelCase). */
function readWebAccount(payload: Record<string, unknown>): WebAccount {
  const rawData = payload.data;
  const data: Record<string, string> = {};
  if (rawData && typeof rawData === "object") {
    for (const [key, value] of Object.entries(rawData as Record<string, unknown>)) {
      if (typeof value === "string") {
        data[key] = value;
      }
    }
  }
  return {
    accountId: typeof payload.account_id === "string" ? payload.account_id : "",
    name: typeof payload.name === "string" ? payload.name : "",
    domain: typeof payload.domain === "string" ? payload.domain : null,
    logoAssetId: typeof payload.logo_asset_id === "string" ? payload.logo_asset_id : null,
    data,
    notes: typeof payload.notes === "string" ? payload.notes : null,
    createdAt: typeof payload.created_at === "string" ? payload.created_at : null,
    updatedAt: typeof payload.updated_at === "string" ? payload.updated_at : null
  };
}

/** Shape an account input into the server's snake_case JSON body, omitting
 * fields the caller did not set (so a PATCH is a partial update). */
function accountRequestBody(input: WebAccountInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.accountId != null) {
    body.account_id = input.accountId;
  }
  if (input.name != null) {
    body.name = input.name;
  }
  if (input.domain !== undefined) {
    body.domain = input.domain;
  }
  if (input.logoAssetId !== undefined) {
    body.logo_asset_id = input.logoAssetId;
  }
  if (input.data !== undefined) {
    body.data = input.data;
  }
  if (input.notes !== undefined) {
    body.notes = input.notes;
  }
  return body;
}

/** List every account (`GET /web/accounts`, name-sorted). */
export async function listWebAccounts({
  apiBaseUrl,
  fetchImpl = lumenFetch
}: WebDocumentOptions): Promise<WebAccount[]> {
  const response = await fetchImpl(new URL("/web/accounts", apiBaseUrl));
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Account list failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { accounts?: unknown };
  const accounts = Array.isArray(payload.accounts) ? payload.accounts : [];
  return accounts
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
    .map(readWebAccount);
}

function customComponentPropValueMatches(
  value: unknown,
  schema: CustomComponentPropSchema
): value is CustomComponentPropValue {
  return (
    (schema.type === "string" && typeof value === "string") ||
    (schema.type === "number" &&
      typeof value === "number" &&
      Number.isFinite(value)) ||
    (schema.type === "boolean" && typeof value === "boolean")
  );
}

function readCustomComponentArtifact(value: unknown): CustomComponentArtifact | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const artifact = value as Record<string, unknown>;
  const manifest = artifact.manifest;
  if (!manifest || typeof manifest !== "object") {
    return null;
  }
  const contract = manifest as Record<string, unknown>;
  const meta = contract.meta;
  const propsSchema = contract.props_schema;
  const browser = contract.browser;
  const properties =
    propsSchema && typeof propsSchema === "object"
      ? (propsSchema as Record<string, unknown>).properties
      : null;
  const required =
    propsSchema && typeof propsSchema === "object"
      ? (propsSchema as Record<string, unknown>).required
      : null;
  const defaults = contract.defaults;
  const warnings = contract.warnings;
  if (
    contract.schema_version !== 2 ||
    !meta ||
    typeof meta !== "object" ||
    typeof (meta as Record<string, unknown>).name !== "string" ||
    !(meta as Record<string, unknown>).name ||
    typeof (meta as Record<string, unknown>).description !== "string" ||
    !propsSchema ||
    typeof propsSchema !== "object" ||
    (propsSchema as Record<string, unknown>).type !== "object" ||
    (propsSchema as Record<string, unknown>).additionalProperties !== false ||
    !properties ||
    typeof properties !== "object" ||
    Array.isArray(properties) ||
    (required !== undefined &&
      (!Array.isArray(required) ||
        required.some((name) => typeof name !== "string"))) ||
    !defaults ||
    typeof defaults !== "object" ||
    Array.isArray(defaults) ||
    !Array.isArray(warnings) ||
    warnings.some(
      (warning) =>
        !warning || typeof warning !== "object" || Array.isArray(warning)
    ) ||
    !browser ||
    typeof browser !== "object" ||
    (browser as Record<string, unknown>).format !== "esm" ||
    (browser as Record<string, unknown>).react !== "host-singleton" ||
    typeof artifact.artifact_id !== "string" ||
    !/^ccart_[0-9a-f]{64}$/.test(artifact.artifact_id) ||
    typeof artifact.account_id !== "string" ||
    artifact.account_id.length === 0 ||
    typeof artifact.slug !== "string" ||
    artifact.slug.length === 0 ||
    !artifact.provenance ||
    typeof artifact.provenance !== "object" ||
    Array.isArray(artifact.provenance)
  ) {
    return null;
  }
  const fields = properties as Record<string, unknown>;
  const parsedFields: Record<string, CustomComponentPropSchema> = {};
  for (const [name, raw] of Object.entries(fields)) {
    if (
      !raw ||
      typeof raw !== "object" ||
      Array.isArray(raw) ||
      !["string", "number", "boolean"].includes(
        String((raw as Record<string, unknown>).type)
      )
    ) {
      return null;
    }
    const field = raw as unknown as CustomComponentPropSchema;
    if (
      (field.enum !== undefined &&
        (field.type !== "string" ||
          !Array.isArray(field.enum) ||
          field.enum.length === 0 ||
          field.enum.some((option) => typeof option !== "string"))) ||
      (field.default !== undefined &&
        (!customComponentPropValueMatches(field.default, field) ||
          (field.enum !== undefined &&
            typeof field.default === "string" &&
            !field.enum.includes(field.default))))
    ) {
      return null;
    }
    parsedFields[name] = field;
  }
  if (
    Array.isArray(required) &&
    required.some((name) => !Object.hasOwn(parsedFields, name))
  ) {
    return null;
  }
  for (const [name, defaultValue] of Object.entries(
    defaults as Record<string, unknown>
  )) {
    const field = parsedFields[name];
    if (
      !field ||
      !customComponentPropValueMatches(defaultValue, field) ||
      (field.enum !== undefined &&
        typeof defaultValue === "string" &&
        !field.enum.includes(defaultValue))
    ) {
      return null;
    }
  }
  return artifact as unknown as CustomComponentArtifact;
}

/** Account-local, successfully compiled custom components available to the
 * editor picker. Families whose newest artifact predates runtime contract 1
 * remain inspectable through the API but are not offered as executable UI. */
export async function listCustomComponents(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  accountId: string
): Promise<CustomComponentCatalogItem[]> {
  const response = await fetchImpl(
    new URL(
      `/web/accounts/${encodeURIComponent(accountId)}/custom-components`,
      apiBaseUrl
    )
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(
        response,
        `Custom-component list failed (HTTP ${response.status}).`
      )
    );
  }
  const payload = (await response.json()) as { components?: unknown };
  return (Array.isArray(payload.components) ? payload.components : [])
    .map((value): CustomComponentCatalogItem | null => {
      if (!value || typeof value !== "object") {
        return null;
      }
      const component = value as Record<string, unknown>;
      const artifact = readCustomComponentArtifact(component.latest_artifact);
      if (
        !artifact ||
        typeof component.slug !== "string" ||
        typeof component.account_id !== "string"
      ) {
        return null;
      }
      return {
        accountId: component.account_id,
        slug: component.slug,
        sourceVersion:
          typeof component.source_version === "number" ? component.source_version : 0,
        artifactCount:
          typeof component.artifact_count === "number" ? component.artifact_count : 0,
        latestArtifact: artifact
      };
    })
    .filter((value): value is CustomComponentCatalogItem => value !== null);
}

export async function fetchCustomComponentArtifact(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  accountId: string,
  artifactId: string
): Promise<CustomComponentArtifact> {
  const response = await fetchImpl(
    new URL(
      `/web/accounts/${encodeURIComponent(accountId)}/custom-component-artifacts/${encodeURIComponent(artifactId)}`,
      apiBaseUrl
    )
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(
        response,
        `Custom-component artifact failed to load (HTTP ${response.status}).`
      )
    );
  }
  const payload = (await response.json()) as { artifact?: unknown };
  const artifact = readCustomComponentArtifact(payload.artifact);
  if (!artifact) {
    throw new Error("Custom-component artifact uses an unsupported runtime contract.");
  }
  return artifact;
}

/** Create an account (`POST /web/accounts`). A 409 (duplicate id) or 422
 * (unresolvable logo) throws with the server message. */
export async function createWebAccount(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  input: WebAccountInput
): Promise<WebAccount> {
  const response = await fetchImpl(new URL("/web/accounts", apiBaseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(accountRequestBody(input))
  });
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Account create failed (HTTP ${response.status}).`)
    );
  }
  return readWebAccount((await response.json()) as Record<string, unknown>);
}

/** Update an account (`PATCH /web/accounts/{id}` — partial). */
export async function updateWebAccount(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  accountId: string,
  patch: WebAccountInput
): Promise<WebAccount> {
  const response = await fetchImpl(
    new URL(`/web/accounts/${encodeURIComponent(accountId)}`, apiBaseUrl),
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(accountRequestBody(patch))
    }
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Account update failed (HTTP ${response.status}).`)
    );
  }
  return readWebAccount((await response.json()) as Record<string, unknown>);
}

/** Delete an account (`DELETE /web/accounts/{id}`). Derived docs keep their
 * `account_id` string (no FK). */
export async function deleteWebAccount(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  accountId: string
): Promise<{ deleted: boolean }> {
  const response = await fetchImpl(
    new URL(`/web/accounts/${encodeURIComponent(accountId)}`, apiBaseUrl),
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Account delete failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { deleted?: unknown };
  return { deleted: payload.deleted === true };
}

/** The result of saving the current doc as a template
 * (`POST /documents/{id}/web/template`). */
export interface SavedWebTemplate {
  documentId: string;
  title: string;
}

/** Clone the current doc into a fresh template document. Response carries the
 * new `document_id` + title; the topbar links to `/web/{document_id}`. */
export async function saveWebTemplate(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  documentId: string,
  title?: string
): Promise<SavedWebTemplate> {
  const body: Record<string, unknown> = {};
  if (title != null && title.length > 0) {
    body.title = title;
  }
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/template`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Save as template failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { document_id?: unknown; title?: unknown };
  const newId = payload.document_id;
  if (typeof newId !== "string" || newId.length === 0) {
    throw new Error("Save as template returned no document id.");
  }
  return { documentId: newId, title: typeof payload.title === "string" ? payload.title : "" };
}

/** A template listed by `GET /web/templates`. */
export interface WebTemplateSummary {
  documentId: string;
  title: string;
  version: number | null;
  updatedAt: string | null;
  brandKitRef: BrandKitRefInput | null;
}

/** List every template document (`GET /web/templates`). */
export async function listWebTemplates({
  apiBaseUrl,
  fetchImpl = lumenFetch
}: WebDocumentOptions): Promise<WebTemplateSummary[]> {
  const response = await fetchImpl(new URL("/web/templates", apiBaseUrl));
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Template list failed (HTTP ${response.status}).`)
    );
  }
  const payload = (await response.json()) as { templates?: unknown };
  const templates = Array.isArray(payload.templates) ? payload.templates : [];
  return templates
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
    .map((row) => {
      const ref = row.brand_kit_ref;
      let brandKitRef: BrandKitRefInput | null = null;
      if (ref && typeof ref === "object") {
        const record = ref as Record<string, unknown>;
        if (typeof record.id === "string" && typeof record.version === "number") {
          brandKitRef = { id: record.id, version: record.version };
        }
      }
      return {
        documentId: typeof row.document_id === "string" ? row.document_id : "",
        title: typeof row.title === "string" ? row.title : "",
        version: typeof row.version === "number" ? row.version : null,
        updatedAt: typeof row.updated_at === "string" ? row.updated_at : null,
        brandKitRef
      };
    });
}

/** One coverage entry: a key and the node ids that referenced it unbound. */
export interface WebDeriveUnboundEntry {
  key: string;
  nodeIds: string[];
}

/** The derive coverage report (D2). Honest accounting of what a binding did and
 * did not cover — surfaced as the manifest's unbound count. */
export interface WebDeriveCoverage {
  bound: string[];
  unboundSlots: WebDeriveUnboundEntry[];
  unboundVars: WebDeriveUnboundEntry[];
  unusedValues: string[];
  removedNodeIds: string[];
}

/** Read a coverage report from a server payload (snake_case → camelCase). */
function readDeriveCoverage(payload: unknown): WebDeriveCoverage | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const stringList = (value: unknown): string[] =>
    Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  const entryList = (value: unknown): WebDeriveUnboundEntry[] =>
    Array.isArray(value)
      ? value
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .map((item) => ({
            key: typeof item.key === "string" ? item.key : "",
            nodeIds: stringList(item.node_ids)
          }))
      : [];
  return {
    bound: stringList(record.bound),
    unboundSlots: entryList(record.unbound_slots),
    unboundVars: entryList(record.unbound_vars),
    unusedValues: stringList(record.unused_values),
    removedNodeIds: stringList(record.removed_node_ids)
  };
}

/** The result of deriving one document for an account
 * (`POST /documents/{id}/web/derive`). */
export interface DerivedWebDocument {
  documentId: string;
  title: string;
  coverage: WebDeriveCoverage | null;
  diagnostics: WebOperationDiagnostic[];
}

/** Derive a new web document from a template (or any web doc) for an account.
 * `accountId` is optional per the /new gate contract (a template chosen without
 * an account). A 422 (`web_derive.rejected`) or 404 throws the server message. */
export async function deriveWebDocument(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  templateId: string,
  params: { accountId?: string | null; title?: string }
): Promise<DerivedWebDocument> {
  const body: Record<string, unknown> = {};
  if (params.accountId != null && params.accountId.length > 0) {
    body.account_id = params.accountId;
  }
  if (params.title != null && params.title.length > 0) {
    body.title = params.title;
  }
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(templateId)}/web/derive`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Derive failed (HTTP ${response.status}).`));
  }
  const payload = (await response.json()) as {
    document_id?: unknown;
    title?: unknown;
    coverage?: unknown;
    diagnostics?: unknown;
  };
  const newId = payload.document_id;
  if (typeof newId !== "string" || newId.length === 0) {
    throw new Error("Derive returned no document id.");
  }
  return {
    documentId: newId,
    title: typeof payload.title === "string" ? payload.title : "",
    coverage: readDeriveCoverage(payload.coverage),
    diagnostics: Array.isArray(payload.diagnostics)
      ? (payload.diagnostics as WebOperationDiagnostic[])
      : []
  };
}

/** One account's outcome in a batch manifest (D5). */
export type WebBatchRowStatus = "derived" | "published" | "failed";

/** A single manifest row: the account, its derived doc + published URL (when
 * published), the per-account status, its unbound binding keys, and any error. */
export interface WebBatchManifestRow {
  accountId: string;
  accountName: string;
  documentId: string | null;
  slug: string | null;
  url: string | null;
  status: WebBatchRowStatus;
  unbound: string[];
  error: string | null;
}

/** The batch's tally across accounts. */
export interface WebBatchCounts {
  total: number;
  derived: number;
  published: number;
  failed: number;
}

/** A batch snapshot: the id, overall status, counts, manifest, and the resume
 * cursor (the chunked-loop position — see {@link webBatchIsUnfinished}). */
export interface WebBatchResult {
  batchId: string;
  status: string;
  counts: WebBatchCounts;
  manifest: WebBatchManifestRow[];
  cursor: number | null;
}

/** True when a batch stopped short of every account and can be resumed. Reads
 * the persisted `cursor` (position in the account list) against the total; a
 * cursor below the total means unfinished. Falls back to a non-terminal
 * `status` string when the server omits the cursor. */
export function webBatchIsUnfinished(result: WebBatchResult): boolean {
  if (result.cursor != null && result.counts.total > 0) {
    return result.cursor < result.counts.total;
  }
  const status = result.status.toLowerCase();
  return status === "running" || status === "partial" || status === "interrupted";
}

/** Read a batch payload (snake_case → camelCase), tolerating the documented
 * `{batch_id, status, counts, manifest}` shape plus the row's `cursor`. */
function readWebBatch(payload: Record<string, unknown>): WebBatchResult {
  const countsRaw = (payload.counts ?? {}) as Record<string, unknown>;
  const num = (value: unknown): number => (typeof value === "number" ? value : 0);
  const manifest = Array.isArray(payload.manifest) ? payload.manifest : [];
  return {
    batchId: typeof payload.batch_id === "string" ? payload.batch_id : "",
    status: typeof payload.status === "string" ? payload.status : "",
    counts: {
      total: num(countsRaw.total),
      derived: num(countsRaw.derived),
      published: num(countsRaw.published),
      failed: num(countsRaw.failed)
    },
    manifest: manifest
      .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
      .map((row) => {
        const status = row.status;
        const rowStatus: WebBatchRowStatus =
          status === "published" || status === "failed" ? status : "derived";
        return {
          accountId: typeof row.account_id === "string" ? row.account_id : "",
          accountName: typeof row.account_name === "string" ? row.account_name : "",
          documentId: typeof row.document_id === "string" ? row.document_id : null,
          slug: typeof row.slug === "string" ? row.slug : null,
          url: typeof row.url === "string" ? row.url : null,
          status: rowStatus,
          unbound: Array.isArray(row.unbound)
            ? row.unbound.filter((key): key is string => typeof key === "string")
            : [],
          error: typeof row.error === "string" ? row.error : null
        };
      }),
    cursor: typeof payload.cursor === "number" ? payload.cursor : null
  };
}

/** Start a generate-for-accounts batch (`POST /documents/{id}/web/batch`). The
 * server derives (and optionally publishes) each account synchronously in
 * chunks, persisting a resumable cursor. Returns the manifest snapshot. */
export async function startWebBatch(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  documentId: string,
  params: { accountIds: string[]; publish: boolean; slugBase?: string }
): Promise<WebBatchResult> {
  const body: Record<string, unknown> = {
    account_ids: params.accountIds,
    publish: params.publish
  };
  if (params.slugBase != null && params.slugBase.length > 0) {
    body.slug_base = params.slugBase;
  }
  const response = await fetchImpl(
    new URL(`/documents/${encodeURIComponent(documentId)}/web/batch`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Batch failed (HTTP ${response.status}).`));
  }
  return readWebBatch((await response.json()) as Record<string, unknown>);
}

/** Resume an interrupted batch from its cursor
 * (`POST /web/batches/{batch_id}/resume`). */
export async function resumeWebBatch(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  batchId: string
): Promise<WebBatchResult> {
  const response = await fetchImpl(
    new URL(`/web/batches/${encodeURIComponent(batchId)}/resume`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}"
    }
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Batch resume failed (HTTP ${response.status}).`)
    );
  }
  return readWebBatch((await response.json()) as Record<string, unknown>);
}

/** Fetch a batch snapshot (`GET /web/batches/{batch_id}`). */
export async function fetchWebBatch(
  { apiBaseUrl, fetchImpl = lumenFetch }: WebDocumentOptions,
  batchId: string
): Promise<WebBatchResult> {
  const response = await fetchImpl(
    new URL(`/web/batches/${encodeURIComponent(batchId)}`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(
      await readErrorMessage(response, `Batch lookup failed (HTTP ${response.status}).`)
    );
  }
  return readWebBatch((await response.json()) as Record<string, unknown>);
}
