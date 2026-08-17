"use client";

import { useEffect, useRef, useState } from "react";
import { designBffConfig } from "../data/design-bff";
import { fetchWebRenderHtml } from "../engine/webDocuments";
import styles from "./web-artifact-canvas.module.css";

/**
 * W2.1: the sandboxed srcdoc render of a real web document, mounted inside
 * the dummy's flush `.webCanvas` viewport by the artifact stage.
 *
 * Semantics ported from WebEditorApp.tsx:979-1036 (the design subsystem's dev
 * shell): `sandbox="allow-scripts"`, a per-render bridge nonce, and the
 * loading/ready/error/empty state set. The empty/error copy is the source's
 * verbatim; the loading line is neutral ("Loading preview…") because the
 * source's "Generating your website…" describes its agent-turn loads, which
 * this read path does not perform — the one copy deviation, deliberate.
 *
 * The render is fetched in editor mode with the bridge injected: the server
 * embeds the selection bridge (hover/selection outlines, navigation blocking,
 * nonce-tagged postMessage selection events). W2.2 attaches the listener; the
 * nonce ref below is its seam — rotated BEFORE every render so a message
 * tagged with a prior render's nonce is dropped.
 */

/** Served by this app's vendor pipeline (W1.4); the srcdoc iframe resolves
 * this relative URL against the parent origin. */
const TAILWIND_RUNTIME_SRC = "/vendor/tailwind-browser.js";

type CanvasState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "error"; message: string }
  | { kind: "ready"; html: string };

export function WebArtifactCanvas({ documentId }: { documentId: string }) {
  // Keyed remount: switching documents resets the canvas to its born-loading
  // state without a synchronous setState inside the effect (react-hooks/
  // set-state-in-effect). A future reload affordance (W2.2+) extends the key.
  return <DocumentRender key={documentId} documentId={documentId} />;
}

function DocumentRender({ documentId }: { documentId: string }) {
  const [state, setState] = useState<CanvasState>({ kind: "loading" });
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
            cause instanceof Error
              ? cause.message
              : "Website render failed.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  if (state.kind === "ready") {
    return (
      <iframe
        className={styles.frame}
        sandbox="allow-scripts"
        srcDoc={state.html}
        title="Website preview"
      />
    );
  }

  if (state.kind === "error") {
    return (
      <div className={styles.stateFrame} role="alert">
        <p className={styles.stateTitle}>Preview failed</p>
        <p className={styles.stateHint}>{state.message}</p>
      </div>
    );
  }

  if (state.kind === "loading") {
    return (
      <div className={styles.stateFrame} role="status">
        <p className={styles.stateHint}>Loading preview…</p>
      </div>
    );
  }

  return (
    <div className={styles.stateFrame}>
      <p className={styles.stateTitle}>Your website will render here</p>
      <p className={styles.stateHint}>
        Describe what you want in the chat and the agent will build it.
      </p>
    </div>
  );
}
