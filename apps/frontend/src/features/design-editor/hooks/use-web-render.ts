"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { designBffConfig } from "../data/design-bff";
import { fetchWebRenderHtml } from "../engine/webDocuments";

/** Served by this app's vendor pipeline (W1.4); the srcdoc iframe resolves
 * this relative URL against the parent origin. */
const TAILWIND_RUNTIME_SRC = "/vendor/tailwind-browser.js";

export type WebRenderState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "error"; message: string }
  | { kind: "ready"; html: string };

/**
 * W2.1/W2.2: the render transport for one mounted document — fetches the
 * editor-mode render (bridge injected) through the BFF and rotates the
 * per-render bridge nonce BEFORE each fetch, per WebEditorApp semantics.
 * Callers mount one instance per document (keyed remount), so the born state
 * is `loading` and no state is reset inside the effect.
 *
 * A `reloadToken` bump (post-write quiet refresh, W3.2) refetches WITHOUT
 * resetting state: the current render keeps showing until the new HTML lands
 * and swaps into the SAME iframe — the source shell's behavior. The loading
 * interstitial exists only for the initial per-document mount; a keyed
 * remount per write was the defect the founder observed (full canvas
 * teardown + flash on every edit) and must not come back.
 *
 * Lives in hooks/ (not the presentation component) per the repo seam rule:
 * presentation receives typed props/hook state and never imports data/.
 */
export function useWebRender(
  documentId: string,
  reloadToken = 0,
): {
  state: WebRenderState;
  /** The current render's bridge nonce — the ported selection listener
   * validates inbound messages against it. */
  nonceRef: RefObject<string>;
} {
  const [state, setState] = useState<WebRenderState>({ kind: "loading" });
  const nonceRef = useRef<string>("");

  useEffect(() => {
    let cancelled = false;
    const nonce = crypto.randomUUID();
    nonceRef.current = nonce;
    fetchWebRenderHtml(designBffConfig(), documentId, TAILWIND_RUNTIME_SRC, {
      nonce,
    })
      .then(({ html }) => {
        if (cancelled) return;
        setState(html ? { kind: "ready", html } : { kind: "empty" });
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message:
            cause instanceof Error ? cause.message : "Website render failed.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, reloadToken]);

  return { nonceRef, state };
}
