"use client";

// W2.2: the bridge listener, ported verbatim from the design editor's
// `apps/editor/src/hooks/useWebBridgeSelection.ts` — the ONLY changes are
// this header, the "use client" directive, the two import paths (the
// engine modules were extracted to ../engine in W1.1), and one mechanical
// adaptation this repo's stricter react-hooks lint forces: the source
// updated its callback refs during render (`ref.current = callback` inline);
// here the same four writes happen in a passive effect (react-hooks/refs).
// The nonce ref it validates against is the one useWebRender rotates per
// render fetch.

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import {
  validateBridgeMessage,
  webBridgeAnnotationsMessage,
  webBridgeClearMessage,
  webBridgeComponentPreviewMessage,
  webBridgeEditTextMessage,
  webBridgeInspectNodeMessage,
  webBridgeRichTextCommandMessage,
  webBridgeRichTextSettleMessage,
  webBridgeRichTextToolbarMessage,
  webBridgeSelectNodeMessage,
  type RichTextCommand,
  type RichTextFormat,
  type RichTextFormatState,
  type RichTextSelectionState,
  type WebAnnotateEvent,
  type WebElementAddress,
  type WebNodeInfo,
  type WebCustomComponentRuntimeState,
  type WebSelection
} from "../engine/webBridge";
import type {
  RichTextDocument,
  WebFragmentTextOverride
} from "../engine/webDocuments";

/**
 * Owns the website preview's selection state: a single persistent `message`
 * listener that trusts only messages from the current iframe carrying the
 * current render nonce (via {@link validateBridgeMessage}), and the two clear
 * paths. The nonce lives in a ref the shell rotates on every render fetch — the
 * listener reads it live, so a message from a torn-down render (stale nonce) is
 * dropped without re-arming the listener. Workflow policy per
 * docs/frontend-practices.md rule 2; the shell only renders `selection`.
 *
 * The same channel carries the in-iframe rich-text lifecycle:
 * `edit-start` suppresses selection-chip churn while the user types, and
 * `rich-text-commit` fires the shell's `onRichTextCommit` (which persists one
 * `set_rich_text` op). `edit-end` settles both commit and Escape-cancel paths.
 */
export interface WebBridgeSelection {
  /** The currently selected node, or `null` when nothing is selected. */
  selection: WebSelection | null;
  /** Latest geometry/computed-style snapshot for a selected or inspected node. */
  nodeInfo: WebNodeInfo | null;
  /** True after the current iframe render has installed its message listener. */
  ready: boolean;
  /** Canonical node id of the active iframe-local rich-text session. */
  editingNodeId: string | null;
  /** Marks covering the current range (`mixed` when only part is marked). */
  richTextFormats: RichTextFormatState | null;
  /** Full selected-range state driving the floating toolbar. */
  richTextSelection: RichTextSelectionState | null;
  /** A runtime-load/session failure from the iframe, if any. */
  richTextError: string | null;
  /** Latest authenticated nested-runtime status for each custom-component
   * node in the current outer render. */
  customComponentRuntime: Record<string, WebCustomComponentRuntimeState>;
  /** Drop the selection locally AND tell the iframe to clear its highlight
   * (the chip's × button). */
  clearSelection: () => void;
  /** Drop the selection locally only — used when a new render is fetched and
   * the frame's DOM (and any highlight) is rebuilt from scratch. */
  resetSelection: () => void;
  /** Open/close a `<dialog>` component node in the preview (inspector preview
   * buttons). No-op until the frame + nonce are live. */
  previewComponent: (nodeId: string, action: "open" | "close") => void;
  /** Select a node programmatically — the frame echoes the normal `select`
   * message back, repopulating the inspector (button command form's "Select
   * dialog"). No-op until the frame + nonce are live. */
  selectNode: (nodeId: string) => void;
  /** Request a read-only snapshot without changing the canvas selection. */
  inspectNode: (nodeId: string) => void;
  /** Apply one mark to the active selected range without committing yet. */
  formatRichText: (nodeId: string, format: RichTextFormat) => void;
  /** Apply one semantic selected-range command without committing yet. */
  commandRichText: (nodeId: string, command: RichTextCommand) => void;
  /** Suppress/resume iframe focusout settlement while a parent toolbar control
   * owns focus. */
  setRichTextToolbarActive: (nodeId: string, active: boolean) => void;
  /** Commit or cancel the active iframe-local session from parent focus. */
  settleRichText: (nodeId: string, action: "commit" | "cancel") => void;
  /** Slice 2 (R-A1): draw the shell's numbered annotation badges in the frame.
   * An empty list IS the clear. No-op until the frame + nonce are live. */
  postAnnotations: (items: { address: WebElementAddress; n: number }[]) => void;
  /** Slice 3 (R-A6): start the in-frame text editor on one addressed element
   * (the comment box's "Edit text" quick action). No-op until the frame +
   * nonce are live. */
  postEditText: (address: WebElementAddress) => void;
}

export function useWebBridgeSelection(params: {
  iframeRef: RefObject<HTMLIFrameElement | null>;
  nonceRef: RefObject<string>;
  /** Invoked when a text node commits its in-iframe edit — the shell persists
   * one canonical rich-text operation. Kept in a ref so a changing callback never
   * re-arms the listener. */
  onRichTextCommit?: (nodeId: string, content: RichTextDocument) => void;
  /** Invoked on every inbound `select` message (including a null clear), so the
   * shell can mirror the selection into its persisted inspector id — and, on a
   * null, empty the inspector. NOT called by `resetSelection` (a render rebuild
   * keeps the inspector on the same stable node id). Kept in a ref so a
   * changing callback never re-arms the listener. */
  onSelect?: (selection: WebSelection | null) => void;
  /** F5 task 20: invoked when the user clicks a site-internal link in the
   * canvas — the bridge prevented the iframe navigation and reported the page
   * that link points at, so the SHELL performs the switch. Kept in a ref so a
   * changing callback never re-arms the listener. */
  onNavigate?: (pageId: string) => void;
  /** Slice 2 (R-A1): invoked on the bridge's element-level click report — the
   * shell opens its comment box on that element. Kept in a ref so a changing
   * callback never re-arms the listener. */
  onAnnotate?: (event: WebAnnotateEvent) => void;
  /** Slice 3 (R-A6): invoked when the in-frame clone text editor commits — the
   * shell persists ONE `set_fragment_text_override` op. Kept in a ref so a
   * changing callback never re-arms the listener. */
  onCloneTextCommit?: (
    address: WebElementAddress,
    override: WebFragmentTextOverride
  ) => void;
  /** The same session abandoned. The frame has already restored its own DOM, so
   * there is nothing to write — this exists for a shell that holds local
   * editing state. Kept in a ref so a changing callback never re-arms the
   * listener. */
  onCloneTextCancel?: (address: WebElementAddress) => void;
  /** Invoked when the bridge posts a generic `move-node` intent. `index` is
   * measured against the destination parent's children after source removal,
   * so the same callback covers reorder and reparent. */
  onMoveNode?: (nodeId: string, newParentNodeId: string, index: number) => void;
  /** Invoked after an in-frame handle resize settles. Null means that axis was
   * not changed (right edge = width, bottom edge = height, corner = both). */
  onResizeNode?: (
    nodeId: string,
    widthPx: number | null,
    heightPx: number | null
  ) => void;
}): WebBridgeSelection {
  const {
    iframeRef,
    nonceRef,
    onRichTextCommit,
    onSelect,
    onNavigate,
    onAnnotate,
    onCloneTextCommit,
    onCloneTextCancel,
    onMoveNode,
    onResizeNode
  } = params;
  const [selection, setSelection] = useState<WebSelection | null>(null);
  const [nodeInfo, setNodeInfo] = useState<WebNodeInfo | null>(null);
  const [ready, setReady] = useState(false);
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [richTextFormats, setRichTextFormats] = useState<RichTextFormatState | null>(null);
  const [richTextSelection, setRichTextSelection] =
    useState<RichTextSelectionState | null>(null);
  const [richTextError, setRichTextError] = useState<string | null>(null);
  const [customComponentRuntime, setCustomComponentRuntime] = useState<
    Record<string, WebCustomComponentRuntimeState>
  >({});

  // While a text node is in contenteditable, the frame keeps posting `select`
  // as the caret moves; suppress that churn until the edit commits/cancels.
  const editingRef = useRef(false);
  const onRichTextCommitRef = useRef(onRichTextCommit);
  const onSelectRef = useRef(onSelect);
  const onNavigateRef = useRef(onNavigate);
  const onAnnotateRef = useRef(onAnnotate);
  const onCloneTextCommitRef = useRef(onCloneTextCommit);
  const onCloneTextCancelRef = useRef(onCloneTextCancel);
  const onMoveNodeRef = useRef(onMoveNode);
  const onResizeNodeRef = useRef(onResizeNode);
  useEffect(() => {
    onRichTextCommitRef.current = onRichTextCommit;
    onSelectRef.current = onSelect;
    onNavigateRef.current = onNavigate;
    onAnnotateRef.current = onAnnotate;
    onCloneTextCommitRef.current = onCloneTextCommit;
    onCloneTextCancelRef.current = onCloneTextCancel;
    onMoveNodeRef.current = onMoveNode;
    onResizeNodeRef.current = onResizeNode;
  });

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
      if (message.type === "ready") {
        setReady(true);
        return;
      }
      if (message.type === "select") {
        if (editingRef.current) {
          return;
        }
        setSelection(message.selection);
        setNodeInfo(message.selection);
        onSelectRef.current?.(message.selection);
        return;
      }
      if (message.type === "node-info") {
        setNodeInfo(message.node);
        return;
      }
      if (message.type === "edit-start") {
        editingRef.current = true;
        setEditingNodeId(message.nodeId);
        setRichTextFormats(null);
        setRichTextSelection(null);
        setRichTextError(null);
        return;
      }
      if (message.type === "edit-end") {
        editingRef.current = false;
        setEditingNodeId((current) => (current === message.nodeId ? null : current));
        setRichTextFormats(null);
        setRichTextSelection(null);
        return;
      }
      if (message.type === "edit-error") {
        setRichTextError(message.message);
        return;
      }
      if (message.type === "rich-text-selection") {
        setEditingNodeId(message.nodeId);
        setRichTextFormats(message.selection.formats);
        setRichTextSelection(message.selection);
        return;
      }
      if (message.type === "rich-text-commit") {
        onRichTextCommitRef.current?.(message.nodeId, message.content);
        return;
      }
      if (message.type === "navigate") {
        onNavigateRef.current?.(message.pageId);
        return;
      }
      if (message.type === "annotate") {
        // The frame posts `annotate` on the very click that settles an open
        // rich-text session, so `editingRef` is already false by the time it
        // arrives — the guard is for the caret-move case, where a click inside
        // the node being edited must not pop a comment box over the caret.
        if (editingRef.current) {
          return;
        }
        onAnnotateRef.current?.(message.event);
        return;
      }
      if (message.type === "clone-text-commit") {
        onCloneTextCommitRef.current?.(message.address, message.override);
        return;
      }
      if (message.type === "clone-text-cancel") {
        onCloneTextCancelRef.current?.(message.address);
        return;
      }
      if (message.type === "move-node") {
        onMoveNodeRef.current?.(
          message.nodeId,
          message.newParentNodeId,
          message.index
        );
        return;
      }
      if (message.type === "resize-node") {
        onResizeNodeRef.current?.(
          message.nodeId,
          message.widthPx,
          message.heightPx
        );
        return;
      }
      if (message.type === "custom-component-runtime") {
        setCustomComponentRuntime((current) => ({
          ...current,
          [message.runtime.nodeId]: message.runtime
        }));
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [iframeRef, nonceRef]);

  const clearSelection = useCallback(() => {
    editingRef.current = false;
    setEditingNodeId(null);
    setRichTextFormats(null);
    setRichTextSelection(null);
    setSelection(null);
    setNodeInfo(null);
    const win = iframeRef.current?.contentWindow;
    const nonce = nonceRef.current;
    if (win && nonce) {
      win.postMessage(webBridgeClearMessage(nonce), "*");
    }
  }, [iframeRef, nonceRef]);

  const resetSelection = useCallback(() => {
    editingRef.current = false;
    setReady(false);
    setEditingNodeId(null);
    setRichTextFormats(null);
    setRichTextSelection(null);
    setRichTextError(null);
    setSelection(null);
    setNodeInfo(null);
    setCustomComponentRuntime({});
  }, []);

  const previewComponent = useCallback(
    (nodeId: string, action: "open" | "close") => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce) {
        win.postMessage(webBridgeComponentPreviewMessage(nonce, nodeId, action), "*");
      }
    },
    [iframeRef, nonceRef]
  );

  const selectNode = useCallback(
    (nodeId: string) => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce) {
        win.postMessage(webBridgeSelectNodeMessage(nonce, nodeId), "*");
      }
    },
    [iframeRef, nonceRef]
  );

  const inspectNode = useCallback(
    (nodeId: string) => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce) {
        win.postMessage(webBridgeInspectNodeMessage(nonce, nodeId), "*");
      }
    },
    [iframeRef, nonceRef]
  );

  const commandRichText = useCallback(
    (nodeId: string, command: RichTextCommand) => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce && editingRef.current) {
        win.postMessage(
          webBridgeRichTextCommandMessage(nonce, nodeId, command),
          "*"
        );
      }
    },
    [iframeRef, nonceRef]
  );

  const formatRichText = useCallback(
    (nodeId: string, format: RichTextFormat) => {
      commandRichText(nodeId, { type: "format", format });
    },
    [commandRichText]
  );

  const setRichTextToolbarActive = useCallback(
    (nodeId: string, active: boolean) => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce && editingRef.current) {
        win.postMessage(
          webBridgeRichTextToolbarMessage(nonce, nodeId, active),
          "*"
        );
      }
    },
    [iframeRef, nonceRef]
  );

  const postAnnotations = useCallback(
    (items: { address: WebElementAddress; n: number }[]) => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce) {
        win.postMessage(webBridgeAnnotationsMessage(nonce, items), "*");
      }
    },
    [iframeRef, nonceRef]
  );

  const postEditText = useCallback(
    (address: WebElementAddress) => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce) {
        win.postMessage(webBridgeEditTextMessage(nonce, address), "*");
      }
    },
    [iframeRef, nonceRef]
  );

  const settleRichText = useCallback(
    (nodeId: string, action: "commit" | "cancel") => {
      const win = iframeRef.current?.contentWindow;
      const nonce = nonceRef.current;
      if (win && nonce && editingRef.current) {
        win.postMessage(
          webBridgeRichTextSettleMessage(nonce, nodeId, action),
          "*"
        );
      }
    },
    [iframeRef, nonceRef]
  );

  return {
    selection,
    nodeInfo,
    ready,
    editingNodeId,
    richTextFormats,
    richTextSelection,
    richTextError,
    customComponentRuntime,
    clearSelection,
    resetSelection,
    previewComponent,
    selectNode,
    inspectNode,
    formatRichText,
    commandRichText,
    setRichTextToolbarActive,
    settleRichText,
    postAnnotations,
    postEditText
  };
}
