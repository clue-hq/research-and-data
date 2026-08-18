"use client";

import { useEffect, useRef, type RefObject } from "react";
import { createPortal } from "react-dom";
import type {
  RichTextCommand,
  RichTextSelectionState,
  WebSelection,
} from "../engine/webBridge";
import type { RichTextDocument, WebTheme } from "../engine/webDocuments";
import { useWebBridgeSelection } from "../hooks/use-web-bridge-selection";
import { useWebRender } from "../hooks/use-web-render";
import styles from "./web-artifact-canvas.module.css";
import { WebRichTextToolbar } from "./web-rich-text-toolbar";

/** W2.3: imperative controls the canvas publishes for its owner — layer-row
 * clicks send `selectNode` INTO the iframe (the frame echoes the normal
 * `select` message back, driving the ordinary selection path).
 *
 * W4.8b adds the two rich-text senders the inspector's range-bound Link-to
 * needs. They stay HERE (the bridge hook is not moved, per the task contract):
 * the hook owns the iframe window and the render nonce, so a sender that left
 * this component would have to carry both. */
export interface WebArtifactCanvasControls {
  selectNode: (nodeId: string) => void;
  /** W4.8b: one range-link command (`set_link` / `remove_link`) into the live
   * session. The whole write path for a text link — a range link is never a
   * node prop (contract item 3). */
  commandRichText: (nodeId: string, command: RichTextCommand) => void;
  /** W4.8b: focus is moving into (true) or out of (false) a PARENT surface
   * that is part of the session. Load-bearing, not politeness: the injected
   * bridge schedules a commit 180ms after the frame's contenteditable loses
   * focus (`web_bridge.py:415-422,548-555`) unless `editingToolbarActive` is
   * set — so without this, clicking into the inspector's URL field would
   * settle the very session the field is editing. The frame clears the flag
   * itself once a command arrives (`web_bridge.py:577-591`). */
  setRichTextInteractionActive: (nodeId: string, active: boolean) => void;
}

/** W4.8a: the in-iframe rich-text session's state, mirrored up for surfaces
 * outside the canvas (the inline error slot today; the inspector's conditional
 * Link-to next). */
export interface WebRichTextSessionState {
  editingNodeId: string | null;
  richTextSelection: RichTextSelectionState | null;
  richTextError: string | null;
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
  onRichTextCommit,
  onRichTextSessionChange,
  onSelect,
  reloadToken = 0,
  richTextBusy = false,
  richTextEnabled = false,
  richTextTheme = null,
  selectedNodeId = null,
}: {
  /** W2.3: receives the canvas's imperative controls while mounted. */
  controlsRef?: RefObject<WebArtifactCanvasControls | null>;
  documentId: string;
  /** W4.8a: a text node's in-iframe session committed — the owner persists ONE
   * `set_rich_text` op through the manual-edits controller. */
  onRichTextCommit?: (nodeId: string, content: RichTextDocument) => void;
  /** W4.8a: the session state mirrored up on every change. */
  onRichTextSessionChange?: (state: WebRichTextSessionState) => void;
  /** W2.2: canvas selection events from the injected bridge, nonce-validated
   * by the ported listener. */
  onSelect?: (selection: WebSelection | null) => void;
  /** W3.2: bump to quietly refetch the render after a committed write. The
   * new HTML swaps into the SAME mounted iframe (no keyed remount, no
   * loading flash) — the source shell's post-edit behavior. */
  reloadToken?: number;
  /** W4.8a: a write is already in flight — the toolbar disables itself, as the
   * source shell's `disabled={manualEdits.busy}` does. */
  richTextBusy?: boolean;
  /** W4.8a: the editing gate. Falsy → a double-click session that starts in
   * the frame is cancelled immediately and the render stays read-only. */
  richTextEnabled?: boolean;
  /** W4.8a: the document's compiled theme — the toolbar's color panels. */
  richTextTheme?: WebTheme | null;
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
      onRichTextCommit={onRichTextCommit}
      onRichTextSessionChange={onRichTextSessionChange}
      onSelect={onSelect}
      reloadToken={reloadToken}
      richTextBusy={richTextBusy}
      richTextEnabled={richTextEnabled}
      richTextTheme={richTextTheme}
      selectedNodeId={selectedNodeId}
    />
  );
}

function DocumentRender({
  controlsRef,
  documentId,
  onRichTextCommit,
  onRichTextSessionChange,
  onSelect,
  reloadToken,
  richTextBusy,
  richTextEnabled,
  richTextTheme,
  selectedNodeId,
}: {
  controlsRef?: RefObject<WebArtifactCanvasControls | null>;
  documentId: string;
  onRichTextCommit?: (nodeId: string, content: RichTextDocument) => void;
  onRichTextSessionChange?: (state: WebRichTextSessionState) => void;
  onSelect?: (selection: WebSelection | null) => void;
  reloadToken: number;
  richTextBusy: boolean;
  richTextEnabled: boolean;
  richTextTheme: WebTheme | null;
  selectedNodeId: string | null;
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const { nonceRef, state } = useWebRender(documentId, reloadToken);
  // The ported bridge listener (source-window + nonce validation). Selection
  // state itself lives with the join owner (useWebArtifactSelection); this
  // canvas only forwards validated events upward.
  const bridge = useWebBridgeSelection({
    iframeRef,
    nonceRef,
    onRichTextCommit,
    onSelect,
  });

  const {
    commandRichText,
    editingNodeId,
    ready,
    resetSelection,
    richTextError,
    richTextSelection,
    selectNode,
    setRichTextToolbarActive,
    settleRichText,
  } = bridge;
  useEffect(() => {
    if (!controlsRef) return;
    controlsRef.current = {
      commandRichText,
      selectNode,
      setRichTextInteractionActive: setRichTextToolbarActive,
    };
    return () => {
      controlsRef.current = null;
    };
  }, [commandRichText, controlsRef, selectNode, setRichTextToolbarActive]);

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

  // W4.8a editing gate (lane ruling, 2026-08-18): the injected bridge starts a
  // rich-text session on ANY double-click of a text node — it has no notion of
  // our view/edit modes, because the source dev shell had none. So when a
  // session opens outside editing, cancel it at once: the frame restores the
  // node's pristine HTML and posts `edit-end` with `committed:false`, leaving
  // the render read-only (the founder's Edit-button-is-the-only-entry rule).
  // Passive effect, no setState — `settleRichText` only posts a message.
  useEffect(() => {
    if (!richTextEnabled && editingNodeId)
      settleRichText(editingNodeId, "cancel");
  }, [editingNodeId, richTextEnabled, settleRichText]);

  // W4.8a: mirror the session up. A passive effect (never a setState in an
  // effect, never a render-time write) — same discipline as the callback-ref
  // updates in use-web-bridge-selection.ts:144-149.
  const onSessionChangeRef = useRef(onRichTextSessionChange);
  useEffect(() => {
    onSessionChangeRef.current = onRichTextSessionChange;
  });
  useEffect(() => {
    onSessionChangeRef.current?.({
      editingNodeId,
      richTextSelection,
      richTextError,
    });
  }, [editingNodeId, richTextError, richTextSelection]);

  if (state.kind === "ready") {
    return (
      <>
        <iframe
          ref={iframeRef}
          className={styles.frame}
          sandbox="allow-scripts"
          srcDoc={state.html}
          title="Website preview"
        />
        {/* Ruling 24: the toolbar is CANVAS UI, so it is OWNED here — the
         * `iframeRef` it positions against never leaves this component. It
         * mounts only for an enabled session with a live selection snapshot,
         * mirroring the source shell's `editingNodeId && richTextSelection`
         * gate (WebEditorApp.tsx:1166-1178).
         *
         * It is RENDERED through a portal to <body>, and that is load-bearing,
         * not tidiness: the toolbar's positioning math (ported verbatim) is in
         * VIEWPORT coordinates, but `.artifactWorkspace` carries a
         * `transform: translateX(...)` for the dummy's slide-in — and a
         * non-`none` transform makes an element the containing block for its
         * `position: fixed` descendants AND clips them by its
         * `overflow: hidden`. Rendered in place, the toolbar would land at the
         * wrong origin and be cut off. The source shell had no such ancestor.
         * Portaling keeps the ported math correct without touching it. The
         * portal is only reached once the render has resolved (never during
         * SSR), so `document` is live here. */}
        {richTextEnabled && editingNodeId && richTextSelection
          ? createPortal(
              <WebRichTextToolbar
                // Keyed on the edited node: a new session starts with every panel
                // closed and every inline error cleared. This REPLACES the
                // source's nodeId-keyed reset effect, which this repo's lint
                // forbids (see the note in the component).
                key={editingNodeId}
                iframeRef={iframeRef}
                nodeId={editingNodeId}
                selection={richTextSelection}
                theme={richTextTheme}
                // The personalization catalog is agent-only scope for now; with no
                // variables the insert-variable control disables itself and
                // explains why — the source's own behaviour for an accountless doc.
                variables={[]}
                disabled={richTextBusy}
                command={commandRichText}
                setInteractionActive={setRichTextToolbarActive}
                settle={settleRichText}
              />,
              window.document.body,
            )
          : null}
      </>
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
