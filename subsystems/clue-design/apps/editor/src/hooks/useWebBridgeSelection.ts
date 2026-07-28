import { useCallback, useEffect, useState, type RefObject } from "react";

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
}): WebBridgeSelection {
  const { iframeRef, nonceRef } = params;
  const [selection, setSelection] = useState<WebSelection | null>(null);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const message = validateBridgeMessage(
        event,
        nonceRef.current ?? "",
        iframeRef.current?.contentWindow ?? null
      );
      if (message && message.type === "select") {
        setSelection(message.selection);
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
    setSelection(null);
  }, []);

  return { selection, clearSelection, resetSelection };
}
