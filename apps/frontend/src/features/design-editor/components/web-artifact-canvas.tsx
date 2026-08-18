"use client";

import { useEffect, useRef, type RefObject } from "react";
import type { WebSelection } from "../engine/webBridge";
import { useWebBridgeSelection } from "../hooks/use-web-bridge-selection";
import { useWebRender } from "../hooks/use-web-render";
import styles from "./web-artifact-canvas.module.css";

/** W2.3: imperative controls the canvas publishes for its owner — layer-row
 * clicks send `selectNode` INTO the iframe (the frame echoes the normal
 * `select` message back, driving the ordinary selection path). */
export interface WebArtifactCanvasControls {
  selectNode: (nodeId: string) => void;
}

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
  controlsRef,
  documentId,
  onSelect,
  reloadToken = 0,
  selectedNodeId = null,
}: {
  /** W2.3: receives the canvas's imperative controls while mounted. */
  controlsRef?: RefObject<WebArtifactCanvasControls | null>;
  documentId: string;
  /** W2.2: canvas selection events from the injected bridge, nonce-validated
   * by the ported listener. */
  onSelect?: (selection: WebSelection | null) => void;
  /** W3.2: bump to quietly refetch the render after a committed write. The
   * new HTML swaps into the SAME mounted iframe (no keyed remount, no
   * loading flash) — the source shell's post-edit behavior. */
  reloadToken?: number;
  /** The owner's persisted selection: re-sent to the frame after each
   * render rebuild so the selection outline survives a write (the source's
   * ready → re-select pattern; a render rebuild keeps the inspector on the
   * same stable node id). */
  selectedNodeId?: string | null;
}) {
  // Keyed remount per DOCUMENT only: switching documents resets render state
  // to born-loading without a synchronous setState inside an effect
  // (react-hooks/set-state-in-effect). Post-write reloads deliberately do
  // NOT remount — see reloadToken above.
  return (
    <DocumentRender
      key={documentId}
      controlsRef={controlsRef}
      documentId={documentId}
      onSelect={onSelect}
      reloadToken={reloadToken}
      selectedNodeId={selectedNodeId}
    />
  );
}

function DocumentRender({
  controlsRef,
  documentId,
  onSelect,
  reloadToken,
  selectedNodeId,
}: {
  controlsRef?: RefObject<WebArtifactCanvasControls | null>;
  documentId: string;
  onSelect?: (selection: WebSelection | null) => void;
  reloadToken: number;
  selectedNodeId: string | null;
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const { nonceRef, state } = useWebRender(documentId, reloadToken);
  // The ported bridge listener (source-window + nonce validation). Selection
  // state itself lives with the join owner (useWebArtifactSelection); this
  // canvas only forwards validated events upward.
  const bridge = useWebBridgeSelection({ iframeRef, nonceRef, onSelect });

  const { ready, resetSelection, selectNode } = bridge;
  useEffect(() => {
    if (!controlsRef) return;
    controlsRef.current = { selectNode };
    return () => {
      controlsRef.current = null;
    };
  }, [controlsRef, selectNode]);

  // The source's render-rebuild sequence: a post-write reload rebuilds the
  // frame DOM, so drop the LOCAL bridge state (resetSelection never calls
  // onSelect — the owner's persisted selection survives) and, once the new
  // frame posts ready, re-send selectNode so the outline and geometry
  // snapshot come back for the same stable node id.
  const previousReload = useRef(reloadToken);
  useEffect(() => {
    if (previousReload.current === reloadToken) return;
    previousReload.current = reloadToken;
    resetSelection();
  }, [reloadToken, resetSelection]);
  useEffect(() => {
    if (ready && selectedNodeId) selectNode(selectedNodeId);
  }, [ready, selectedNodeId, selectNode]);

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
