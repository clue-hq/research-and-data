"use client";

import { useCallback, useEffect, useMemo, useRef, type RefObject } from "react";
import { createPortal } from "react-dom";
import type { PendingAnnotation } from "../adapter/annotations";
import type { VeilRenderKind } from "../adapter/generating-veil";
import { canvasSandbox } from "../adapter/view-mode-html";
import {
  addressKey,
  type RichTextCommand,
  type RichTextSelectionState,
  type WebAnnotateEvent,
  type WebElementAddress,
  type WebSelection,
} from "../engine/webBridge";
import type {
  RichTextDocument,
  WebFragmentTextOverride,
  WebTheme,
} from "../engine/webDocuments";
import { useWebBridgeSelection } from "../hooks/use-web-bridge-selection";
import { useWebRender } from "../hooks/use-web-render";
import { CanvasEmptyState, CanvasErrorState, CanvasLoadingState } from "./canvas-states";
import { WebAnnotationPopover } from "./web-annotation-popover";
import styles from "./web-artifact-canvas.module.css";
import { WebRichTextToolbar } from "./web-rich-text-toolbar";

/**
 * Slice 2 (R-A1..R-A3): the annotation session, as the CANVAS needs it. The
 * state itself is owned by `useWebAnnotations` up in the editing session (the
 * composer chips read the same list); the canvas only opens the box on a click,
 * renders it, and draws the badges the list implies.
 *
 * `onSend` is optional and its control is simply absent without it — "Send to
 * chat" belongs to the composer (task 7).
 *
 * Slice 4 (R-A6): "Edit text" is NOT part of this binding at all. The CANVAS
 * owns that quick action — it dismisses the box and posts `edit-text` into the
 * frame with its own bridge sender — so the button is there whenever the box is
 * open on a text-like element, whoever owns the session. There is deliberately
 * no slot for it here: a session owner has nothing to say about it.
 */
export interface WebAnnotationsCanvasBinding {
  pending: PendingAnnotation | null;
  itemsForPage: (pageId: string) => { address: WebElementAddress; n: number }[];
  open: (pending: Omit<PendingAnnotation, "pageId" | "note">) => void;
  editNote: (note: string) => void;
  dismiss: () => void;
  add: (note?: string) => void;
  onSend?: (note: string) => void;
}

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
 *
 * W4 addendum (founder rulings, 2026-08-19) — the canvas now has TWO modes,
 * and `editing` is the whole switch:
 *
 * - **Edit ON** — everything described above, unchanged: the bridged render,
 *   the selection outlines, the re-select-after-write sequence, the rich-text
 *   session, `sandbox="allow-scripts"`.
 * - **Edit OFF** — an actual website. The bridge is opt-in server-side, so the
 *   view fetch simply omits it and the render arrives with no editor chrome of
 *   any kind (no hover rectangles, no outlines). Every link opens a new tab via
 *   the injected `<base target="_blank">` (`adapter/view-mode-html.ts`), which
 *   is why the sandbox gains `allow-popups` and
 *   `allow-popups-to-escape-sandbox` — see {@link canvasSandbox} for why both
 *   are load-bearing and why `allow-scripts` stays in both modes.
 *
 * Toggling refetches into the SAME iframe (the reloadToken quiet-swap
 * discipline): no keyed remount, no loading flash.
 */
export function WebArtifactCanvas({
  annotations,
  controlsRef,
  documentId,
  editing = false,
  onCloneTextCommit,
  onNavigate,
  onRenderKindChange,
  onRichTextCommit,
  onRichTextSessionChange,
  onSelect,
  pageId,
  reloadToken = 0,
  richTextBusy = false,
  richTextEnabled = false,
  richTextTheme = null,
  selectedNodeId = null,
}: {
  /** Slice 2 (R-A1): the annotation session. Absent → no comment box and no
   * badges, exactly as before this slice. */
  annotations?: WebAnnotationsCanvasBinding;
  /** W2.3: receives the canvas's imperative controls while mounted. */
  controlsRef?: RefObject<WebArtifactCanvasControls | null>;
  documentId: string;
  /** W4 addendum: the mode switch. False (the default) mounts the bridge-free
   * view render — an actual website, links opening in new tabs. */
  editing?: boolean;
  /** Slice 3 (R-A6): the in-frame clone text editor committed — the owner
   * persists ONE `set_fragment_text_override` op. The address always carries a
   * structural path (the validator drops one that does not). */
  onCloneTextCommit?: (
    address: WebElementAddress,
    override: WebFragmentTextOverride,
  ) => void;
  /** F5 task 20: the user clicked a site-internal link in the canvas. The
   * injected bridge always prevents the iframe navigation; when the link's raw
   * href is one of the document's routes it reports the page it points at, and
   * the owner switches the active page (which also clears the selection). */
  onNavigate?: (pageId: string) => void;
  /** W4.8a: a text node's in-iframe session committed — the owner persists ONE
   * `set_rich_text` op through the manual-edits controller. */
  onRichTextCommit?: (nodeId: string, content: RichTextDocument) => void;
  /** The render state, mirrored up on every change. The output stage owns the
   * "agent is generating" veil (it has to: the veil must show from leg-open,
   * before any document exists to mount this canvas at all), and its hold rule
   * needs to know when the render that a turn produced has actually landed.
   * Nothing here reads it back — this canvas is only the reporter. */
  onRenderKindChange?: (kind: VeilRenderKind) => void;
  /** W4.8a: the session state mirrored up on every change. */
  onRichTextSessionChange?: (state: WebRichTextSessionState) => void;
  /** W2.2: canvas selection events from the injected bridge, nonce-validated
   * by the ported listener. */
  onSelect?: (selection: WebSelection | null) => void;
  /** F5: which page of a multi-page site to render. Undefined (the default)
   * renders the document's first page — the endpoint's own default. A change
   * refetches into the SAME iframe under the reloadToken quiet-swap
   * discipline; only the DOCUMENT keys the remount, never the page. */
  pageId?: string;
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
      annotations={annotations}
      controlsRef={controlsRef}
      documentId={documentId}
      editing={editing}
      onCloneTextCommit={onCloneTextCommit}
      onNavigate={onNavigate}
      onRenderKindChange={onRenderKindChange}
      onRichTextCommit={onRichTextCommit}
      onRichTextSessionChange={onRichTextSessionChange}
      onSelect={onSelect}
      pageId={pageId}
      reloadToken={reloadToken}
      richTextBusy={richTextBusy}
      richTextEnabled={richTextEnabled}
      richTextTheme={richTextTheme}
      selectedNodeId={selectedNodeId}
    />
  );
}

function DocumentRender({
  annotations,
  controlsRef,
  documentId,
  editing,
  onCloneTextCommit,
  onNavigate,
  onRenderKindChange,
  onRichTextCommit,
  onRichTextSessionChange,
  onSelect,
  pageId,
  reloadToken,
  richTextBusy,
  richTextEnabled,
  richTextTheme,
  selectedNodeId,
}: {
  annotations?: WebAnnotationsCanvasBinding;
  controlsRef?: RefObject<WebArtifactCanvasControls | null>;
  documentId: string;
  editing: boolean;
  onCloneTextCommit?: (
    address: WebElementAddress,
    override: WebFragmentTextOverride,
  ) => void;
  onNavigate?: (pageId: string) => void;
  onRenderKindChange?: (kind: VeilRenderKind) => void;
  onRichTextCommit?: (nodeId: string, content: RichTextDocument) => void;
  onRichTextSessionChange?: (state: WebRichTextSessionState) => void;
  onSelect?: (selection: WebSelection | null) => void;
  pageId?: string;
  reloadToken: number;
  richTextBusy: boolean;
  richTextEnabled: boolean;
  richTextTheme: WebTheme | null;
  selectedNodeId: string | null;
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const { nonceRef, state } = useWebRender(documentId, reloadToken, editing, pageId);
  // The ported bridge listener (source-window + nonce validation). Selection
  // state itself lives with the join owner (useWebArtifactSelection); this
  // canvas only forwards validated events upward.
  // Slice 2 (R-A1): the element-level click report opens the comment box. The
  // ordinary `select` for the OWNING node still fires beside it, so the
  // inspector and the layers panel are untouched by annotating.
  const openAnnotation = annotations?.open;
  const onAnnotate = useCallback(
    (event: WebAnnotateEvent) => {
      openAnnotation?.({
        address: event.address,
        name: event.name,
        textLike: event.textLike,
        geometry: event.geometry,
      });
    },
    [openAnnotation],
  );
  const bridge = useWebBridgeSelection({
    iframeRef,
    nonceRef,
    onAnnotate,
    onCloneTextCommit,
    onNavigate,
    onRichTextCommit,
    onSelect,
  });

  const {
    commandRichText,
    editingNodeId,
    postAnnotations,
    postEditText,
    ready,
    resetSelection,
    richTextError,
    richTextSelection,
    selectNode,
    setRichTextToolbarActive,
    settleRichText,
  } = bridge;

  // Slice 2: the badges. Posted on every change of the list AND on every
  // `ready` — a post-write reload rebuilds the frame's DOM (and rotates the
  // nonce), so the badges have to be drawn again against the new render.
  // An empty list is the clear, so a removed annotation erases its badge
  // through the very same message.
  const itemsForPage = annotations?.itemsForPage;
  const annotationItems = useMemo(
    () => (itemsForPage && pageId ? itemsForPage(pageId) : []),
    [itemsForPage, pageId],
  );
  useEffect(() => {
    if (!ready) return;
    postAnnotations(annotationItems);
  }, [annotationItems, postAnnotations, ready]);

  // Slice 4 (R-A6): the comment box's "Edit text" quick action. It is defined
  // HERE, not up in the annotation session, because the sender it needs
  // (`postEditText`) belongs to the bridge hook this component owns — a handler
  // that lived anywhere else would have to carry the iframe window and the
  // render nonce with it.
  //
  // Order is load-bearing: DISMISS the pending box first, then post. The
  // frame's `edit-text` handler starts `beginCloneEditing` (or the vocabulary
  // rich-text session for a bare `[data-tv]` node), which hides its hover box
  // and takes focus — a comment box left open beside/over the element would sit
  // on top of the editor it just opened.
  //
  // Which editor opens is the FRAME's decision, made from the address alone
  // (path present → the clone's constrained editor; no path → `beginEditing`),
  // so this quick action treats both cases identically.
  const dismissAnnotation = annotations?.dismiss;
  const onEditText = useCallback(
    (address: WebElementAddress) => {
      dismissAnnotation?.();
      postEditText(address);
    },
    [dismissAnnotation, postEditText],
  );

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
  //
  // W4 addendum: editor-only, and explicitly so. A view render carries no
  // bridge, so it never posts `ready` and its nonce is empty — the re-select
  // would already be a double no-op — but the gate states the intent rather
  // than relying on two accidents of the bridgeless path.
  useEffect(() => {
    if (editing && ready && selectedNodeId) selectNode(selectedNodeId);
  }, [editing, ready, selectedNodeId, selectNode]);

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

  // Turning Edit OFF unlatches the bridge. Reviewed defect (2026-08-18): the
  // view refetch empties `nonceRef` synchronously inside `useWebRender`'s own
  // effect, which runs BEFORE the cancel effect above — so `settleRichText`
  // posts nothing (it is guarded on a live nonce) and the departing frame's
  // `edit-end`/`rich-text-commit` are rejected inbound against an empty
  // expected nonce. Nothing else cleared the LOCAL state, which only
  // `reloadToken` bumps reach, so `editingRef` stayed latched true and every
  // inbound `select` after Edit came back was dropped: dead selection, an
  // inspector stuck on a stale node, property writes landing on the WRONG one,
  // and a dead toolbar portal able to re-mount from the stale session.
  //
  // The in-progress rich-text edit is DELIBERATELY discarded here — leaving the
  // editing dock is a cancel (the W4.8a ledgered ruling) — and the cancel
  // message could not reach the frame anyway. This reset IS the unlatch.
  // `resetSelection` never calls `onSelect`, so the owner's persisted selection
  // survives and the editing-gated re-select effect above restores the outline
  // when Edit returns. Same bridge-owned state clearing as the reloadToken path
  // at :218-222, so no setState-in-effect violation.
  useEffect(() => {
    if (!editing) resetSelection();
  }, [editing, resetSelection]);

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

  // The render state, mirrored up to the stage's generating veil. Same
  // discipline as the session mirror directly above and as the callback-ref
  // updates in use-web-bridge-selection.ts: a passive effect calling the
  // PARENT's setter, never a setState of this component's own state (which this
  // repo's react-hooks lint bars, and which would paint one stale frame first).
  // The latest callback lives in a ref so a caller passing an inline closure
  // cannot make this re-fire on every render.
  const onRenderKindChangeRef = useRef(onRenderKindChange);
  useEffect(() => {
    onRenderKindChangeRef.current = onRenderKindChange;
  });
  useEffect(() => {
    onRenderKindChangeRef.current?.(state.kind);
  }, [state.kind]);

  if (state.kind === "ready") {
    return (
      <>
        <iframe
          ref={iframeRef}
          className={styles.frame}
          sandbox={canvasSandbox(editing)}
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
        {/* Slice 2 (R-A1/R-A2): the comment box. Portalled to <body> for the
         * very reason the toolbar above is — `.artifactWorkspace`'s transform
         * would otherwise become the containing block for its `position: fixed`
         * and clip it. Keyed on the element address, so clicking a second
         * element starts a genuinely empty box rather than carrying the first
         * one's half-typed note across. */}
        {editing && annotations?.pending
          ? createPortal(
              <WebAnnotationPopover
                key={addressKey(annotations.pending.address)}
                iframeRef={iframeRef}
                onAdd={annotations.add}
                onDismiss={annotations.dismiss}
                onEditNote={annotations.editNote}
                onEditText={onEditText}
                onSend={annotations.onSend}
                pending={annotations.pending}
              />,
              window.document.body,
            )
          : null}
      </>
    );
  }

  if (state.kind === "error") return <CanvasErrorState message={state.message} />;
  if (state.kind === "loading") return <CanvasLoadingState />;
  return <CanvasEmptyState />;
}
