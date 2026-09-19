"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { viewModeHtml } from "../adapter/view-mode-html";
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
 *
 * W4 addendum (founder ruling, 2026-08-19): `editing` picks the render. Edit ON
 * is the path above, verbatim. Edit OFF fetches the CLEAN render — no bridge,
 * no nonce to rotate — and runs it through `viewModeHtml` so every link opens
 * a new tab. The Tailwind BROWSER RUNTIME rides in BOTH modes: the server's
 * static CSS carries theme tokens and font-faces but NO utility rules, so the
 * runtime is what compiles the document's classes (`bg-accent` on a rich-text
 * highlight, every layout utility) AND ships the preflight reset that keeps a
 * linked phrase in its authored formatting instead of browser-default blue
 * underline. Omitting it was the original task-6 spec's error — browser-caught
 * 2026-08-19 (highlights vanished, link CSS changed, both same root cause).
 * `editing` is an effect dep, so toggling the mode refetches into the SAME
 * iframe under the reloadToken discipline: no keyed remount, no loading flash,
 * and the old render keeps showing until the new html lands.
 *
 * F5 addendum (2026-09-02): `pageId` picks WHICH page of a multi-page site
 * this canvas renders. It is an effect dep alongside the reload nonce, so
 * navigating to another page refetches into the SAME iframe under the exact
 * discipline above — no keyed remount, no loading flash. Leaving it undefined
 * keeps the endpoint's first-page default, which is what every single-page
 * caller (and the shell before task 18 supplies a value) relies on.
 */
export function useWebRender(
  documentId: string,
  reloadToken = 0,
  editing = false,
  pageId?: string,
): {
  state: WebRenderState;
  /** The current render's bridge nonce — the ported selection listener
   * validates inbound messages against it. Empty while viewing: that render
   * carries no bridge, so there is nothing to validate and nothing to post. */
  nonceRef: RefObject<string>;
} {
  const [state, setState] = useState<WebRenderState>({ kind: "loading" });
  const nonceRef = useRef<string>("");

  useEffect(() => {
    let cancelled = false;
    // Viewing has no bridge, so there is no nonce to rotate — and the ref is
    // EMPTIED rather than left holding the last edit session's value, because
    // every bridge sender is a no-op on a falsy nonce. A bridgeless frame can
    // then never be posted into, whichever way the mode was reached.
    const nonce = editing ? crypto.randomUUID() : "";
    nonceRef.current = nonce;
    fetchWebRenderHtml(
      designBffConfig(),
      documentId,
      TAILWIND_RUNTIME_SRC,
      nonce ? { nonce } : undefined,
      pageId,
    )
      .then(({ html: fetched }) => {
        if (cancelled) return;
        const html = editing ? fetched : viewModeHtml(fetched);
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
  }, [documentId, editing, pageId, reloadToken]);

  return { nonceRef, state };
}
