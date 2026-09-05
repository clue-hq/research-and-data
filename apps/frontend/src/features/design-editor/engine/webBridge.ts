/**
 * Website-mode canvas-bridge contract — the editor side of the iframe bridge.
 *
 * The render endpoint (`?bridge=1&nonce=…`) injects a small script into the
 * sandboxed preview document that draws its own hover/selection outlines,
 * blocks link navigation, and reports the selected node to the parent via
 * `postMessage`. A `srcdoc` sandbox frame has a null origin, so its messages
 * arrive with `event.origin === "null"` (the literal string) and are otherwise
 * indistinguishable from a hostile frame — hence the four-way trust check in
 * {@link validateBridgeMessage}: source identity, null origin, channel tag, and
 * a per-render nonce. Messages carrying a stale nonce (from a previous render,
 * whose DOM was rebuilt) fail the nonce check and are dropped.
 *
 * Pure + framework-free so it is unit-testable with a jsdom `MessageEvent`; the
 * hook (`useWebBridgeSelection`) owns the listener + nonce lifecycle around it.
 */

import type { RichTextDocument, WebFragmentTextOverride } from "./webDocuments";

export const WEB_BRIDGE_CHANNEL = "lumen-web-bridge";

export type RichTextFormat = "bold" | "italic" | "underline" | "strikethrough";
export type RichTextFormatValue = "on" | "off" | "mixed";
export type RichTextFormatState = Record<RichTextFormat, RichTextFormatValue>;
export type RichTextBlockType =
  | "paragraph"
  | "ordered_list"
  | "unordered_list"
  | "mixed";

export interface RichTextLinkSelection {
  state: RichTextFormatValue;
  href: string | null;
  newTab: boolean | null;
}

/** The iframe-local selection snapshot driving the floating toolbar. `rect` is
 * measured in iframe viewport coordinates and translated by the parent against
 * the iframe's current bounding rect. */
export interface RichTextSelectionState {
  collapsed: boolean;
  selectedText: string;
  rect: WebNodeRect | null;
  formats: RichTextFormatState;
  commonClasses: string[];
  mixedClasses: string[];
  link: RichTextLinkSelection;
  blockType: RichTextBlockType;
  structured: boolean;
  canIndent: boolean;
  canOutdent: boolean;
}

export type RichTextCommand =
  | { type: "format"; format: RichTextFormat }
  | {
      type: "set_class_facet";
      facet: "text_color" | "highlight";
      token: string | null;
      knownTokens: string[];
    }
  | { type: "set_link"; href: string; newTab: boolean }
  | { type: "remove_link" }
  | { type: "insert_variable"; key: string; fallback: string }
  | { type: "clear_formatting" }
  | {
      type: "set_block";
      block: Exclude<RichTextBlockType, "mixed">;
    }
  | { type: "indent_list" }
  | { type: "outdent_list" }
  | { type: "refresh_selection" };

export interface WebNodeRect {
  x: number;
  y: number;
  top: number;
  right: number;
  bottom: number;
  left: number;
  width: number;
  height: number;
}

export interface WebNodeGeometry {
  viewport: WebNodeRect;
  document: WebNodeRect;
}

/** Allowlisted getComputedStyle values reported by the sandbox bridge. The
 * rendered DOM is an observation surface only; authored mutations still go
 * through canonical WebOperations. */
export interface WebNodeComputedStyle {
  authoredClasses: string;
  display: string;
  position: string;
  boxSizing: string;
  width: string;
  height: string;
  minWidth: string;
  minHeight: string;
  maxWidth: string;
  maxHeight: string;
  marginTop: string;
  marginRight: string;
  marginBottom: string;
  marginLeft: string;
  paddingTop: string;
  paddingRight: string;
  paddingBottom: string;
  paddingLeft: string;
  gap: string;
  rowGap: string;
  columnGap: string;
  flexDirection: string;
  flexWrap: string;
  flexGrow: string;
  flexShrink: string;
  justifyContent: string;
  alignItems: string;
  alignSelf: string;
  gridTemplateColumns: string;
  gridTemplateRows: string;
  fontFamily: string;
  fontSize: string;
  fontWeight: string;
  lineHeight: string;
  textAlign: string;
  color: string;
  backgroundColor: string;
  borderTopWidth: string;
  borderRightWidth: string;
  borderBottomWidth: string;
  borderLeftWidth: string;
  borderRadius: string;
  objectFit: string;
  objectPosition: string;
  overflowX: string;
  overflowY: string;
  opacity: string;
}

/** A generic rendered-node snapshot reported by the canvas bridge. */
export interface WebNodeInfo {
  nodeId: string;
  tag: string;
  tv: boolean;
  btn: boolean;
  text: string;
  parentNodeId: string | null;
  childNodeIds: string[];
  geometry: WebNodeGeometry;
  computedStyle: WebNodeComputedStyle;
}

export type WebSelection = WebNodeInfo;

/**
 * Spec §3.1 — the ONE element-address grammar every consumer shares.
 *
 * `nodeId` is the WebDoc node that owns the DOM subtree; `path` is a structural
 * `:nth-child(…)` chain from that node's rendered root down to the exact
 * element, and exists ONLY for an element inside a cloned band (a vocabulary
 * node's descendants have no path — see the bridge's `addressOf`). `slot` is
 * the element's `data-lumen-slot` key when it carries one, and `tag` is display
 * only.
 */
export interface WebElementAddress {
  nodeId: string;
  path?: string;
  slot?: string;
  tag: string;
}

/** Ruling R-A1: one click in Edit mode reports the exact element under the
 * cursor — a SECOND, finer report beside the ordinary `select` of the owning
 * node. `textLike` says the element carries editable copy (the comment box's
 * "Edit text" quick action); `geometry` anchors the box to the element. */
export interface WebAnnotateEvent {
  address: WebElementAddress;
  name: string;
  textLike: boolean;
  geometry: WebNodeGeometry;
}

/** The bridge's own path grammar (`elementPath` in `web_bridge.py`). Anything
 * else is not a path this shell can hand back for resolution, so it is dropped
 * rather than carried — the address then addresses the owning node, which is
 * always resolvable. */
const ELEMENT_PATH_PATTERN = /^(:nth-child\(\d+\)( > )?)+$/;

/** Coerce the bridge's `address` payload into a {@link WebElementAddress}.
 * Shared by every element-addressed message (`annotate`, the clone text-edit
 * pair) so the three can never disagree about what a valid address is. A
 * malformed path is DROPPED rather than failing the whole address — the address
 * then names the owning node, which is always resolvable. */
function coerceAddress(raw: unknown): WebElementAddress | null {
  const address = (raw ?? null) as Partial<WebElementAddress> | null;
  if (
    !address ||
    typeof address !== "object" ||
    typeof address.nodeId !== "string" ||
    address.nodeId.length === 0 ||
    typeof address.tag !== "string" ||
    address.tag.length === 0
  ) {
    return null;
  }
  const path =
    typeof address.path === "string" && ELEMENT_PATH_PATTERN.test(address.path)
      ? address.path
      : undefined;
  const slot =
    typeof address.slot === "string" && address.slot.length > 0
      ? address.slot
      : undefined;
  return { nodeId: address.nodeId, path, slot, tag: address.tag };
}

/** R-A6: an override's text is ONE line of plain copy, and the server stores it
 * as UTF-8 — so the cap is measured in bytes, not code units. */
const MAX_OVERRIDE_TEXT_BYTES = 8192;

/** Truncate to at most {@link MAX_OVERRIDE_TEXT_BYTES} UTF-8 bytes, by CODE
 * POINT: a multi-byte character straddling the cap is dropped whole rather than
 * split into a lone surrogate or a dangling continuation byte. */
function capOverrideText(text: string): string {
  const encoder = new TextEncoder();
  if (encoder.encode(text).length <= MAX_OVERRIDE_TEXT_BYTES) {
    return text;
  }
  let out = "";
  let bytes = 0;
  for (const point of Array.from(text)) {
    const size = encoder.encode(point).length;
    if (bytes + size > MAX_OVERRIDE_TEXT_BYTES) {
      break;
    }
    out += point;
    bytes += size;
  }
  return out;
}

/** Coerce the bridge's `override` payload into a {@link WebFragmentTextOverride}.
 * The frame is untrusted, so only a literal `true` is a mark; `size` is a STEP
 * on the engine's own −3…+3 ramp and is OMITTED when it is 0 (the engine's field
 * is optional, and 0 means "the clone's own type size stands"). */
function coerceFragmentTextOverride(
  raw: unknown
): WebFragmentTextOverride | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const source = raw as Record<string, unknown>;
  if (typeof source.text !== "string") {
    return null;
  }
  const override: WebFragmentTextOverride = {
    text: capOverrideText(source.text),
    bold: source.bold === true,
    italic: source.italic === true,
    underline: source.underline === true
  };
  if (typeof source.size === "number" && Number.isFinite(source.size)) {
    const step = Math.max(-3, Math.min(3, Math.trunc(source.size)));
    if (step !== 0) {
      override.size = step;
    }
  }
  return override;
}

/** The address's stable identity within a render — `${nodeId}#${path ?? ""}`.
 * Used to key annotations; the trailing `#` keeps a node-level address from
 * ever colliding with an inner-element one. */
export function addressKey(a: WebElementAddress): string {
  return `${a.nodeId}#${a.path ?? ""}`;
}

/** Spec §3.5 — the `design_node` context-ref `object_id` an annotation submits:
 * the bare node id, or `${nodeId}#${path}` for an element inside a clone. `#`
 * is illegal in both a node id and the path grammar, so the split is
 * unambiguous on the server. */
export function addressObjectId(a: WebElementAddress): string {
  return a.path ? `${a.nodeId}#${a.path}` : a.nodeId;
}

export interface WebCustomComponentRuntimeState {
  nodeId: string;
  artifactId: string;
  state: "ready" | "error" | "recoverable-error" | "height";
  height: number | null;
  message: string | null;
}

/** A validated inbound bridge message.
 *   • `ready` — the bridge is live.
 *   • `select` — the current selection (or `null` when cleared).
 *   • `edit-start` / `edit-end` — one local Lexical session lifecycle.
 *   • `rich-text-selection` — range geometry plus marks/classes/link state.
 *   • `rich-text-commit` — one canonical RichTextDocument for the whole local
 *     session; the server validates it before a SetRichText commit. */
export type WebBridgeInbound =
  | { type: "ready" }
  | { type: "select"; selection: WebSelection | null }
  | { type: "node-info"; node: WebNodeInfo }
  | { type: "edit-start"; nodeId: string }
  | { type: "edit-end"; nodeId: string; committed: boolean; changed: boolean }
  | { type: "edit-error"; nodeId: string; message: string }
  | {
      type: "rich-text-selection";
      nodeId: string;
      selection: RichTextSelectionState;
    }
  | { type: "rich-text-commit"; nodeId: string; content: RichTextDocument }
  | {
      type: "move-node";
      nodeId: string;
      newParentNodeId: string;
      index: number;
    }
  | {
      type: "resize-node";
      nodeId: string;
      widthPx: number | null;
      heightPx: number | null;
    }
  | {
      type: "custom-component-runtime";
      runtime: WebCustomComponentRuntimeState;
    }
  /** F5 task 20: a click on a site-internal link. The bridge swallows every
   * anchor click (the canvas must never navigate the iframe); when the raw
   * href matches one of the document's routes it re-posts the click as this
   * intent, and the shell switches the active page. */
  | { type: "navigate"; pageId: string }
  /** Slice 2 (R-A1): a single click in Edit mode, reported at ELEMENT
   * granularity so a headline inside a cloned band — which has no node id of
   * its own — can still be commented on. Arrives alongside the ordinary
   * `select` for the owning node. */
  | { type: "annotate"; event: WebAnnotateEvent }
  /** Slice 3 (R-A6): the human retyped one element inside a cloned band and
   * settled the in-frame editor. The address ALWAYS carries a path — a clone
   * edit has no meaning on a vocabulary node, whose copy is the engine's own
   * and is edited through the rich-text session instead. */
  | {
      type: "clone-text-commit";
      address: WebElementAddress;
      override: WebFragmentTextOverride;
    }
  /** The same session abandoned (Escape). The frame has already restored its
   * own DOM; the shell needs no write, only the chance to drop any local
   * editing state it was holding. */
  | { type: "clone-text-cancel"; address: WebElementAddress };

/** Coerce the bridge's `node` payload into a {@link WebSelection}, tolerating a
 * missing/partial shape. Returns `null` for an absent node (a cleared
 * selection) or one without an id. */
const RECT_KEYS = [
  "x",
  "y",
  "top",
  "right",
  "bottom",
  "left",
  "width",
  "height"
] as const;

const COMPUTED_STYLE_KEYS = [
  "authoredClasses",
  "display",
  "position",
  "boxSizing",
  "width",
  "height",
  "minWidth",
  "minHeight",
  "maxWidth",
  "maxHeight",
  "marginTop",
  "marginRight",
  "marginBottom",
  "marginLeft",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "gap",
  "rowGap",
  "columnGap",
  "flexDirection",
  "flexWrap",
  "flexGrow",
  "flexShrink",
  "justifyContent",
  "alignItems",
  "alignSelf",
  "gridTemplateColumns",
  "gridTemplateRows",
  "fontFamily",
  "fontSize",
  "fontWeight",
  "lineHeight",
  "textAlign",
  "color",
  "backgroundColor",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "borderRadius",
  "objectFit",
  "objectPosition",
  "overflowX",
  "overflowY",
  "opacity"
] as const;

function coerceRect(value: unknown): WebNodeRect {
  const record =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return Object.fromEntries(
    RECT_KEYS.map((key) => [
      key,
      typeof record[key] === "number" && Number.isFinite(record[key]) ? record[key] : 0
    ])
  ) as unknown as WebNodeRect;
}

function coerceComputedStyle(value: unknown): WebNodeComputedStyle {
  const record =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return Object.fromEntries(
    COMPUTED_STYLE_KEYS.map((key) => [key, typeof record[key] === "string" ? record[key] : ""])
  ) as unknown as WebNodeComputedStyle;
}

/** The bridge's `{viewport, document}` rect pair, tolerant of a missing or
 * partial shape (every absent number folds to 0, as `coerceRect` does). Shared
 * by the node-info snapshot and the element-level `annotate` report, so the two
 * can never disagree about what a geometry payload means. */
function coerceGeometry(value: unknown): WebNodeGeometry {
  const record =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    viewport: coerceRect(record.viewport),
    document: coerceRect(record.document)
  };
}

function coerceNodeInfo(node: unknown): WebNodeInfo | null {
  if (!node || typeof node !== "object") {
    return null;
  }
  const record = node as Record<string, unknown>;
  const nodeId = typeof record.nodeId === "string" ? record.nodeId : "";
  if (!nodeId) {
    return null;
  }
  return {
    nodeId,
    tag: typeof record.tag === "string" ? record.tag : "",
    tv: Boolean(record.tv),
    btn: Boolean(record.btn),
    text: typeof record.text === "string" ? record.text : "",
    parentNodeId: typeof record.parentNodeId === "string" ? record.parentNodeId : null,
    childNodeIds: Array.isArray(record.childNodeIds)
      ? record.childNodeIds.filter((value): value is string => typeof value === "string")
      : [],
    geometry: coerceGeometry(record.geometry),
    computedStyle: coerceComputedStyle(record.computedStyle)
  };
}

const RICH_TEXT_FORMATS: RichTextFormat[] = [
  "bold",
  "italic",
  "underline",
  "strikethrough"
];

function coerceRichTextFormatState(value: unknown): RichTextFormatState | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const entries = RICH_TEXT_FORMATS.map((format) => {
    const state = record[format];
    return state === "on" || state === "off" || state === "mixed"
      ? [format, state]
      : null;
  });
  if (entries.some((entry) => entry === null)) {
    return null;
  }
  return Object.fromEntries(entries as [RichTextFormat, RichTextFormatValue][]) as RichTextFormatState;
}

function coerceStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    return null;
  }
  return Array.from(new Set(value));
}

function coerceRichTextSelectionState(value: unknown): RichTextSelectionState | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const formats = coerceRichTextFormatState(record.formats);
  const commonClasses = coerceStringArray(record.commonClasses);
  const mixedClasses = coerceStringArray(record.mixedClasses);
  const rect =
    record.rect === null
      ? null
      : record.rect && typeof record.rect === "object"
        ? coerceRect(record.rect)
        : null;
  const linkRecord =
    record.link && typeof record.link === "object"
      ? (record.link as Record<string, unknown>)
      : null;
  const linkState = linkRecord?.state;
  const blockType = record.blockType;
  if (
    typeof record.collapsed !== "boolean" ||
    typeof record.selectedText !== "string" ||
    (blockType !== "paragraph" &&
      blockType !== "ordered_list" &&
      blockType !== "unordered_list" &&
      blockType !== "mixed") ||
    typeof record.structured !== "boolean" ||
    typeof record.canIndent !== "boolean" ||
    typeof record.canOutdent !== "boolean" ||
    !formats ||
    !commonClasses ||
    !mixedClasses ||
    (record.rect !== null && !rect) ||
    !linkRecord ||
    (linkState !== "on" && linkState !== "off" && linkState !== "mixed")
  ) {
    return null;
  }
  const href =
    linkRecord.href === null || typeof linkRecord.href === "string"
      ? linkRecord.href
      : null;
  const newTab =
    linkRecord.newTab === null || typeof linkRecord.newTab === "boolean"
      ? linkRecord.newTab
      : null;
  if (
    (linkState === "on" && (typeof href !== "string" || typeof newTab !== "boolean")) ||
    (linkState !== "on" && (linkRecord.href !== null || linkRecord.newTab !== null))
  ) {
    return null;
  }
  return {
    collapsed: record.collapsed,
    selectedText: record.selectedText,
    rect,
    formats,
    commonClasses,
    mixedClasses,
    link: { state: linkState, href, newTab },
    blockType,
    structured: record.structured,
    canIndent: record.canIndent,
    canOutdent: record.canOutdent
  };
}

function coerceRichTextDocument(value: unknown): RichTextDocument | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (record.schema_version !== 1 || !Array.isArray(record.blocks)) {
    return null;
  }
  return value as RichTextDocument;
}

/**
 * Validate a `message` event against the bridge trust checks, in order:
 * source identity → null origin → channel tag → nonce. Only a message passing
 * all four is trusted and parsed; anything else (including a stale nonce from a
 * previous render) returns `null`. `expectedSource` is the current iframe's
 * `contentWindow`; a nullish one never matches, so messages before the frame
 * mounts are rejected.
 */
export function validateBridgeMessage(
  event: MessageEvent,
  expectedNonce: string,
  expectedSource: unknown
): WebBridgeInbound | null {
  if (expectedSource == null || event.source !== expectedSource) {
    return null;
  }
  // srcdoc sandbox frames post from a null origin, serialized as the string.
  if (event.origin !== "null") {
    return null;
  }
  const data = event.data as Record<string, unknown> | null | undefined;
  if (!data || typeof data !== "object") {
    return null;
  }
  if (data.channel !== WEB_BRIDGE_CHANNEL) {
    return null;
  }
  if (typeof expectedNonce !== "string" || expectedNonce.length === 0) {
    return null;
  }
  if (data.nonce !== expectedNonce) {
    return null;
  }
  if (data.type === "ready") {
    return { type: "ready" };
  }
  if (data.type === "select") {
    return { type: "select", selection: coerceNodeInfo(data.node) };
  }
  if (data.type === "node-info") {
    const node = coerceNodeInfo(data.node);
    return node ? { type: "node-info", node } : null;
  }
  if (data.type === "edit-start") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    return nodeId ? { type: "edit-start", nodeId } : null;
  }
  if (data.type === "edit-end") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    return nodeId
      ? {
          type: "edit-end",
          nodeId,
          committed: data.committed === true,
          changed: data.changed === true
        }
      : null;
  }
  if (data.type === "edit-error") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    return nodeId
      ? {
          type: "edit-error",
          nodeId,
          message: typeof data.message === "string" ? data.message : "Rich-text editing failed."
        }
      : null;
  }
  if (data.type === "rich-text-selection") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    const selection = coerceRichTextSelectionState(data.selection);
    return nodeId && selection
      ? { type: "rich-text-selection", nodeId, selection }
      : null;
  }
  if (data.type === "rich-text-commit") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    const content = coerceRichTextDocument(data.content);
    return nodeId && content ? { type: "rich-text-commit", nodeId, content } : null;
  }
  if (data.type === "move-node") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    const newParentNodeId =
      typeof data.newParentNodeId === "string" ? data.newParentNodeId : "";
    if (
      !nodeId ||
      !newParentNodeId ||
      typeof data.index !== "number" ||
      !Number.isInteger(data.index) ||
      data.index < 0
    ) {
      return null;
    }
    return { type: "move-node", nodeId, newParentNodeId, index: data.index };
  }
  if (data.type === "resize-node") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    const widthPx =
      data.widthPx === null || data.widthPx === undefined
        ? null
        : typeof data.widthPx === "number" && Number.isFinite(data.widthPx)
          ? data.widthPx
          : Number.NaN;
    const heightPx =
      data.heightPx === null || data.heightPx === undefined
        ? null
        : typeof data.heightPx === "number" && Number.isFinite(data.heightPx)
          ? data.heightPx
          : Number.NaN;
    if (
      !nodeId ||
      Number.isNaN(widthPx) ||
      Number.isNaN(heightPx) ||
      (widthPx === null && heightPx === null) ||
      (widthPx !== null && widthPx <= 0) ||
      (heightPx !== null && heightPx <= 0)
    ) {
      return null;
    }
    return { type: "resize-node", nodeId, widthPx, heightPx };
  }
  // F5 task 20: the bridge's `lumen:navigate` — a site-internal link click it
  // already prevented, translated to the page it points at. Admitted under the
  // very same source/origin/channel/nonce checks as every selection message
  // above, so a message from a torn-down render can never move the page.
  if (data.type === "lumen:navigate") {
    const pageId = typeof data.pageId === "string" ? data.pageId : "";
    return pageId ? { type: "navigate", pageId } : null;
  }
  // Slice 2 (R-A1): the element-level click report. Admitted under the very
  // same source/origin/channel/nonce checks as every message above.
  if (data.type === "annotate") {
    const address = coerceAddress(data.address);
    if (!address) {
      return null;
    }
    return {
      type: "annotate",
      event: {
        address,
        // A nameless report falls back to the tag — the label is display copy,
        // never an identity, so an absent one must not drop the annotation.
        name:
          typeof data.name === "string" && data.name.length > 0
            ? data.name
            : address.tag,
        textLike: data.textLike === true,
        geometry: coerceGeometry(data.geometry)
      }
    };
  }
  // Slice 3 (R-A6): the clone text-edit session's two settlements. Admitted
  // under the very same source/origin/channel/nonce checks as every message
  // above, and BOTH require a structural path: an override addresses one
  // element inside somebody else's markup, so an address without a path is not
  // an override's address at all.
  if (data.type === "clone-text-commit" || data.type === "clone-text-cancel") {
    const address = coerceAddress(data.address);
    if (!address || !address.path) {
      return null;
    }
    if (data.type === "clone-text-cancel") {
      return { type: "clone-text-cancel", address };
    }
    const override = coerceFragmentTextOverride(data.override);
    return override ? { type: "clone-text-commit", address, override } : null;
  }
  if (data.type === "custom-component-runtime") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    const artifactId =
      typeof data.artifactId === "string" ? data.artifactId : "";
    const state = data.state;
    const height =
      data.height === null
        ? null
        : typeof data.height === "number" &&
            Number.isFinite(data.height) &&
            data.height >= 1 &&
            data.height <= 10_000
          ? data.height
          : Number.NaN;
    const message =
      data.message === null
        ? null
        : typeof data.message === "string"
          ? data.message.slice(0, 500)
          : null;
    if (
      !nodeId ||
      !/^ccart_[0-9a-f]{64}$/.test(artifactId) ||
      (state !== "ready" &&
        state !== "error" &&
        state !== "recoverable-error" &&
        state !== "height") ||
      Number.isNaN(height) ||
      (data.message !== null && typeof data.message !== "string")
    ) {
      return null;
    }
    return {
      type: "custom-component-runtime",
      runtime: { nodeId, artifactId, state, height, message }
    };
  }
  return null;
}

/** The kind label shown in the context chip: a button, a text node, else the
 * bare DOM tag (falling back to "element" for an unknown/empty tag). */
export function selectionKindLabel(selection: WebSelection): string {
  if (selection.btn) {
    return "button";
  }
  if (selection.tv) {
    return "text";
  }
  return selection.tag || "element";
}

/** The chip's primary label — `${nodeId} · ${kind}` (Moda-style id + kind). */
export function selectionChipLabel(selection: WebSelection): string {
  return `${selection.nodeId} · ${selectionKindLabel(selection)}`;
}

/** The `clear` message posted INTO the iframe to drop its selection highlight.
 * Carries the current nonce so the frame ignores a message meant for a prior
 * render. */
export function webBridgeClearMessage(nonce: string): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "clear";
} {
  return { channel: WEB_BRIDGE_CHANNEL, nonce, type: "clear" };
}

/** Slice 2 (R-A1): the numbered annotation badges posted INTO the iframe. The
 * SHELL owns the numbering; the frame only draws it — and an empty `items` list
 * IS the clear, so a settled turn erases every badge through this one message.
 * Same nonce-tagging as {@link webBridgeClearMessage}. */
export function webBridgeAnnotationsMessage(
  nonce: string,
  items: { address: WebElementAddress; n: number }[]
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "annotations";
  items: { address: WebElementAddress; n: number }[];
} {
  return { channel: WEB_BRIDGE_CHANNEL, nonce, type: "annotations", items };
}

/** Slice 3 (R-A6): start the in-frame text editor on one addressed element
 * programmatically — the comment box's "Edit text" quick action, which is the
 * same gesture as a double-click on that element. An address WITH a path opens
 * the constrained clone editor; one without opens the ordinary rich-text
 * session on the owning node. Same nonce-tagging as
 * {@link webBridgeClearMessage}. */
export function webBridgeEditTextMessage(
  nonce: string,
  address: WebElementAddress
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "edit-text";
  address: WebElementAddress;
} {
  return { channel: WEB_BRIDGE_CHANNEL, nonce, type: "edit-text", address };
}

/** The `component-preview` message posted INTO the iframe to open/close a
 * `<dialog>` component node (the inspector's Preview open / Close preview).
 * Same nonce-tagging as {@link webBridgeClearMessage}. */
export function webBridgeComponentPreviewMessage(
  nonce: string,
  nodeId: string,
  action: "open" | "close"
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "component-preview";
  nodeId: string;
  action: "open" | "close";
} {
  return { channel: WEB_BRIDGE_CHANNEL, nonce, type: "component-preview", nodeId, action };
}

/** The `select-node` message posted INTO the iframe to select a node
 * programmatically (the button command form's "Select dialog" affordance). The
 * frame echoes the normal `select` message back, which repopulates the
 * inspector. Same nonce-tagging as {@link webBridgeClearMessage}. */
export function webBridgeSelectNodeMessage(
  nonce: string,
  nodeId: string
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "select-node";
  nodeId: string;
} {
  return { channel: WEB_BRIDGE_CHANNEL, nonce, type: "select-node", nodeId };
}

/** Ask the current iframe render for geometry/computed style for any canonical
 * node id without changing selection or canvas highlight state. */
export function webBridgeInspectNodeMessage(
  nonce: string,
  nodeId: string
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "inspect-node";
  nodeId: string;
} {
  return { channel: WEB_BRIDGE_CHANNEL, nonce, type: "inspect-node", nodeId };
}

/** Apply one selected-range format inside the active iframe-local edit
 * session. No WebOperation is emitted until the session settles. */
export function webBridgeRichTextCommandMessage(
  nonce: string,
  nodeId: string,
  command: RichTextCommand
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "rich-text-command";
  nodeId: string;
  command: RichTextCommand;
} {
  return {
    channel: WEB_BRIDGE_CHANNEL,
    nonce,
    type: "rich-text-command",
    nodeId,
    command
  };
}

/** Tell the iframe that focus is intentionally moving into/out of the parent
 * toolbar. While active, iframe focusout must not settle the local edit. */
export function webBridgeRichTextToolbarMessage(
  nonce: string,
  nodeId: string,
  active: boolean
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "rich-text-toolbar";
  nodeId: string;
  active: boolean;
} {
  return {
    channel: WEB_BRIDGE_CHANNEL,
    nonce,
    type: "rich-text-toolbar",
    nodeId,
    active
  };
}

/** Explicitly settle an iframe-local edit while parent toolbar focus is active.
 * Escape cancels; clicking outside the toolbar commits before the new action. */
export function webBridgeRichTextSettleMessage(
  nonce: string,
  nodeId: string,
  action: "commit" | "cancel"
): {
  channel: typeof WEB_BRIDGE_CHANNEL;
  nonce: string;
  type: "rich-text-settle";
  nodeId: string;
  action: "commit" | "cancel";
} {
  return {
    channel: WEB_BRIDGE_CHANNEL,
    nonce,
    type: "rich-text-settle",
    nodeId,
    action
  };
}
