"use client";

import { useRef } from "react";
import type { WebSelection } from "../engine/webBridge";
import { useWebBridgeSelection } from "../hooks/use-web-bridge-selection";
import { useWebRender } from "../hooks/use-web-render";
import styles from "./web-artifact-canvas.module.css";

/**
 * W2.1: the sandboxed srcdoc render of a real web document, mounted inside
 * the dummy's flush `.webCanvas` viewport by the artifact stage.
 *
 * Semantics ported from WebEditorApp.tsx:979-1036 (the design subsystem's dev
 * shell): `sandbox="allow-scripts"`, a per-render bridge nonce (owned by
 * `useWebRender`), and the loading/ready/error/empty state set. The
 * empty/error copy is the source's verbatim; the loading line is neutral
 * ("Loading preview…") because the source's "Generating your website…"
 * describes its agent-turn loads, which this read path does not perform — the
 * one copy deviation, deliberate.
 *
 * The render is fetched in editor mode with the bridge injected: the server
 * embeds the selection bridge (hover/selection outlines, navigation blocking,
 * nonce-tagged postMessage selection events). W2.2 attaches the ported
 * listener here and forwards validated selections via `onSelect`; the join
 * with the document lives in `useWebArtifactSelection`.
 */
export function WebArtifactCanvas({
  documentId,
  onSelect,
}: {
  documentId: string;
  /** W2.2: canvas selection events from the injected bridge, nonce-validated
   * by the ported listener. */
  onSelect?: (selection: WebSelection | null) => void;
}) {
  // Keyed remount: switching documents resets render state to born-loading
  // without a synchronous setState inside an effect (react-hooks/
  // set-state-in-effect). A future reload affordance (W2.2+) extends the key.
  return (
    <DocumentRender key={documentId} documentId={documentId} onSelect={onSelect} />
  );
}

function DocumentRender({
  documentId,
  onSelect,
}: {
  documentId: string;
  onSelect?: (selection: WebSelection | null) => void;
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const { nonceRef, state } = useWebRender(documentId);
  // The ported bridge listener (source-window + nonce validation). Selection
  // state itself lives with the join owner (useWebArtifactSelection); this
  // canvas only forwards validated events upward.
  useWebBridgeSelection({ iframeRef, nonceRef, onSelect });

  if (state.kind === "ready") {
    return (
      <iframe
        ref={iframeRef}
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
