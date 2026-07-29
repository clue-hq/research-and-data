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
  // personalization hedge — carried by the schema, ignored by every v0 path.
  slot_key?: string | null;
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
    }
  | { kind: "component"; component: "nav_menu" }
  | { kind: "component"; component: "carousel"; show_arrows: boolean; autoplay_s?: number }
  | { kind: "component"; component: "tabs"; default_tab: number };

/** An embed's whole-props payload. The URL form carries the provider (calendly
 * allowlisted, else custom) + url and an empty html; the snippet form carries
 * custom html with no url. */
export type WebEmbedProps = { kind: "embed"; provider?: "calendly" | "custom"; url?: string; html: string };

export type WebNodeProps =
  | { kind: "text"; variant: string; content: string }
  | WebButtonProps
  | { kind: "image"; asset_id: string; alt: string; href?: string | null; new_tab: boolean }
  | { kind: "section"; tag: string; anchor_id?: string | null }
  | { kind: "container" }
  | { kind: "icon"; icon: string }
  | WebEmbedProps
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
 * The inspector + contenteditable commit path emit set_node_classes/set_text/
 * set_node_props; the insert palette and structural edits emit the tree ops
 * (insert/move/remove) and asset ops (replace/upsert). */
export type WebOperation =
  | { kind: "set_node_classes"; page_id: string; id: string; classes: string }
  | { kind: "set_text"; page_id: string; id: string; content: string }
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
  | { kind: "upsert_asset"; record: AssetRecord };

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
  const placement = deriveInsertPlacement(page, selectedNodeId, kind === "section");
  const rootId = page.root ?? "root";
  let subtree = buildInsertableSubtree(kind, existing, gen, image);

  if (placement.parent === rootId && kind !== "section") {
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
}

/** Read the document's publish state. Throws (with the server message) on any
 * non-2xx so the dialog surfaces it inline. */
export async function fetchWebPublishInfo(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
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
  };
  return {
    published: payload.published === true,
    slug: typeof payload.slug === "string" ? payload.slug : null,
    url: typeof payload.url === "string" ? payload.url : null,
    docVersion: typeof payload.doc_version === "number" ? payload.doc_version : null,
    status: typeof payload.status === "string" ? payload.status : null,
    previousAvailable: payload.previous_available === true,
    updatedAt: typeof payload.updated_at === "string" ? payload.updated_at : null
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
}

/** Publish (or republish) a website (`POST /documents/{id}/web/publish`). Pass
 * the desired slug; omit it to let the server keep the current one. A 422 (bad
 * slug) or 409 (slug taken by another document) throws with the server's
 * message so the dialog can surface it inline. */
export async function publishWebDocument(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
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
  };
  return {
    schemaVersion: typeof payload.schema_version === "number" ? payload.schema_version : null,
    slug: typeof payload.slug === "string" ? payload.slug : "",
    url: typeof payload.url === "string" ? payload.url : "",
    docVersion: typeof payload.doc_version === "number" ? payload.doc_version : null,
    runtimeVersion: typeof payload.runtime_version === "string" ? payload.runtime_version : null,
    previousAvailable: payload.previous_available === true
  };
}

/** The result of an unpublish (`DELETE /web/publishes/{slug}`). */
export interface WebUnpublishResult {
  slug: string;
  status: string;
}

/** Take a published site offline (`DELETE /web/publishes/{slug}`). */
export async function unpublishWebSite(
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
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
  { apiBaseUrl, fetchImpl = (input, init) => fetch(input, init) }: WebDocumentOptions,
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
