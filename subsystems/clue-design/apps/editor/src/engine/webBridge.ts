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

/** A node the canvas bridge reported as selected. Mirrors the render bridge's
 * `node` payload: `tag` is the DOM tag, `tv`/`btn` flag a text-value/button
 * node, `text` is the node's trimmed text (used for the chip excerpt). */
export interface WebSelection {
  nodeId: string;
  tag: string;
  tv: boolean;
  btn: boolean;
  text: string;
}

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
  | { type: "edit-start"; nodeId: string }
  | { type: "text-commit"; nodeId: string; html: string }
  | { type: "move-section"; nodeId: string; boundary: number };

/** Coerce the bridge's `node` payload into a {@link WebSelection}, tolerating a
 * missing/partial shape. Returns `null` for an absent node (a cleared
 * selection) or one without an id. */
function coerceSelection(node: unknown): WebSelection | null {
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
    text: typeof record.text === "string" ? record.text : ""
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
    return { type: "select", selection: coerceSelection(data.node) };
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
  if (data.type === "move-section") {
    const nodeId = typeof data.nodeId === "string" ? data.nodeId : "";
    if (!nodeId || typeof data.boundary !== "number" || !Number.isInteger(data.boundary)) {
      return null;
    }
    return { type: "move-section", nodeId, boundary: data.boundary };
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
