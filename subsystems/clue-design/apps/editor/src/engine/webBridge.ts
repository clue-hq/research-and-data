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

export const WEB_BRIDGE_CHANNEL = "lumen-web-bridge";

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

/** A validated inbound bridge message.
 *   • `ready` — the bridge is live.
 *   • `select` — the current selection (or `null` when cleared).
 *   • `edit-start` — a text node entered in-iframe contenteditable (dblclick);
 *     the shell suppresses selection-chip churn until it commits.
 *   • `text-commit` — the edited text was committed (blur/Enter); `html` is the
 *     iframe's current inner markup, which the shell persists via a `set_text`
 *     op (the server sanitizes). Esc cancels in-iframe and sends nothing. */
export type WebBridgeInbound =
  | { type: "ready" }
  | { type: "select"; selection: WebSelection | null }
  | { type: "node-info"; node: WebNodeInfo }
  | { type: "edit-start"; nodeId: string }
  | { type: "text-commit"; nodeId: string; html: string }
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
    };

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

function coerceNodeInfo(node: unknown): WebNodeInfo | null {
  if (!node || typeof node !== "object") {
    return null;
  }
  const record = node as Record<string, unknown>;
  const nodeId = typeof record.nodeId === "string" ? record.nodeId : "";
  if (!nodeId) {
    return null;
  }
  const geometry =
    record.geometry && typeof record.geometry === "object"
      ? (record.geometry as Record<string, unknown>)
      : {};
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
    geometry: {
      viewport: coerceRect(geometry.viewport),
      document: coerceRect(geometry.document)
    },
    computedStyle: coerceComputedStyle(record.computedStyle)
  };
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
  if (data.type === "text-commit") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    if (!nodeId) {
      return null;
    }
    return { type: "text-commit", nodeId, html: typeof data.html === "string" ? data.html : "" };
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
