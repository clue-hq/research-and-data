import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import {
  validateBridgeMessage,
  webBridgeClearMessage,
  type WebSelection
} from "@/engine/webBridge";

/**
 * Owns the website preview's selection state: a single persistent `message`
 * listener that trusts only messages from the current iframe carrying the
 * current render nonce (via {@link validateBridgeMessage}), and the two clear
 * paths. The nonce lives in a ref the shell rotates on every render fetch — the
 * listener reads it live, so a message from a torn-down render (stale nonce) is
 * dropped without re-arming the listener. Workflow policy per
 * docs/frontend-practices.md rule 2; the shell only renders `selection`.
 *
 * The same channel carries the in-iframe contenteditable lifecycle:
 * `edit-start` suppresses selection-chip churn while the user types, and
 * `text-commit` fires the shell's `onTextCommit` (which persists a `set_text`
 * op). Esc cancels in-iframe and sends nothing, so a stale `edit-start` is
 * cleared on the next `select` or render.
 */
export interface WebBridgeSelection {
  /** The currently selected node, or `null` when nothing is selected. */
  selection: WebSelection | null;
  /** Drop the selection locally AND tell the iframe to clear its highlight
   * (the chip's × button). */
  clearSelection: () => void;
  /** Drop the selection locally only — used when a new render is fetched and
   * the frame's DOM (and any highlight) is rebuilt from scratch. */
  resetSelection: () => void;
}

export function useWebBridgeSelection(params: {
  iframeRef: RefObject<HTMLIFrameElement | null>;
  nonceRef: RefObject<string>;
  /** Invoked when a text node commits its in-iframe edit — the shell persists
   * a `set_text` op with `html`. Kept in a ref so a changing callback never
   * re-arms the listener. */
  onTextCommit?: (nodeId: string, html: string) => void;
}): WebBridgeSelection {
  const { iframeRef, nonceRef, onTextCommit } = params;
  const [selection, setSelection] = useState<WebSelection | null>(null);

  // While a text node is in contenteditable, the frame keeps posting `select`
  // as the caret moves; suppress that churn until the edit commits/cancels.
  const editingRef = useRef(false);
  const onTextCommitRef = useRef(onTextCommit);
  onTextCommitRef.current = onTextCommit;

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const message = validateBridgeMessage(
        event,
        nonceRef.current ?? "",
        iframeRef.current?.contentWindow ?? null
      );
      if (!message) {
        return;
      }
      if (message.type === "select") {
        if (editingRef.current) {
          return;
        }
        setSelection(message.selection);
        return;
      }
      if (message.type === "edit-start") {
        editingRef.current = true;
        return;
      }
      if (message.type === "text-commit") {
        editingRef.current = false;
        onTextCommitRef.current?.(message.nodeId, message.html);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [iframeRef, nonceRef]);

  const clearSelection = useCallback(() => {
    setSelection(null);
    const win = iframeRef.current?.contentWindow;
    const nonce = nonceRef.current;
    if (win && nonce) {
      win.postMessage(webBridgeClearMessage(nonce), "*");
    }
  }, [iframeRef, nonceRef]);

  const resetSelection = useCallback(() => {
    editingRef.current = false;
    setSelection(null);
  }, []);

  return { selection, clearSelection, resetSelection };
}
