"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  buildWebRichTextVariableCatalog,
  buildInsertCustomComponentOp,
  buildInsertNodeOp,
  fetchCustomComponentArtifact,
  fetchWebDocument,
  fetchWebPublishInfo,
  fetchWebRenderHtml,
  fetchWebTheme,
  findWebNode,
  initialCustomComponentProps,
  listCustomComponents,
  listDialogComponents,
  listWebAccounts,
  planCanvasNodeMove,
  planCanvasNodeResize,
  replaceAssetOp,
  resolveActivePageId,
  saveWebTemplate,
  setNodePropsOp,
  setRichTextOp,
  upsertAssetOp,
  webDocumentHasContent,
  webPromptStorageKey,
  type InsertableKind,
  type CustomComponentArtifact,
  type CustomComponentCatalogItem,
  type LoadedWebDocument,
  type RichTextDocument,
  type WebAccount,
  type WebDoc,
  type WebNode,
  type WebNodeProps,
  type WebPageSummary,
  type WebTheme
} from "@/engine/webDocuments";
import type { AssetRecord } from "@/engine/contracts";
import {
  useWebAgentTurn,
  type WebRunEvent,
  type WebTurnDoneEnvelope
} from "@/hooks/useWebAgentTurn";
import { useWebBridgeSelection } from "@/hooks/useWebBridgeSelection";
import { useWebManualEdits } from "@/hooks/useWebManualEdits";
import { WebInspectorPanel } from "@/components/web/WebInspectorPanel";
import type { FragmentAssetOption } from "@/components/web/WebFragmentInspector";
import {
  activateFragment,
  fetchDormantFragments,
  fetchFragmentCard,
  generateFragmentPreview,
  retireFragment,
  type FragmentCard
} from "@/engine/webFragmentCards";
import { WebInsertPalette } from "@/components/web/WebInsertPalette";
import { WebAssetDrawer } from "@/components/web/WebAssetDrawer";
import { WebPublishDialog } from "@/components/web/WebPublishDialog";
import { WebBatchDialog } from "@/components/web/WebBatchDialog";
import { WebRichTextToolbar } from "@/components/web/WebRichTextToolbar";
import { selectionChipLabel, type WebSelection } from "@/engine/webBridge";
import {
  parseWebGroundingSummary,
  type WebGroundingSummary
} from "@/engine/webGrounding";

/**
 * The website-mode editor shell: loads the web document, drives agent turns
 * through {@link useWebAgentTurn}, and renders the generated site into a
 * sandboxed preview iframe beside a chat rail. Deliberately imports NO
 * scene/canvas code — the website surface is a separate, light bundle.
 *
 * Per docs/frontend-practices.md rule 2, the turn *lifecycle* (start → SSE →
 * done/error) lives in the hook; this component only binds fields, composes
 * the data layer's fetch wrappers for load/render, and renders the transcript.
 */

/** The Tailwind browser runtime the rendered page loads. Served from the Next
 * dev server; a srcdoc iframe resolves this relative URL against the parent
 * origin. See public/vendor/README.md. */
const TAILWIND_RUNTIME_SRC = "/vendor/tailwind-browser.js";

type ShellState =
  | { kind: "loading" }
  | { kind: "ready"; document: LoadedWebDocument }
  | { kind: "wrong-kind"; document: LoadedWebDocument }
  | { kind: "error"; message: string };

/** The preview width chips. `fluid` fills the pane; the rest pin an exact
 * device width the pane scrolls to. */
type WidthMode = "fluid" | "1440" | "768" | "375";
const WIDTH_CHIPS: { mode: WidthMode; label: string }[] = [
  { mode: "fluid", label: "Fluid" },
  { mode: "1440", label: "1440" },
  { mode: "768", label: "768" },
  { mode: "375", label: "375" }
];

/** The selection context a turn was sent with (the active chip), surfaced as a
 * small prefix on the user message bubble. */
interface TurnContext {
  nodeId: string;
}

/** One completed turn in the chat transcript. */
interface TurnRecord {
  id: string;
  prompt: string;
  context: TurnContext | null;
  activity: string[];
  summary: string | null;
  grounding: WebGroundingSummary | null;
  status: "applied" | "failed";
}

/** The in-flight turn's prompt (its live activity is derived from the hook). */
interface PendingTurn {
  id: string;
  prompt: string;
  context: TurnContext | null;
}

type RenderStatus = "idle" | "loading" | "ready" | "error";

/** The rail's two modes: the agent chat (default) and the manual inspector. */
type RailMode = "chat" | "inspect";
type CustomArtifactState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; artifact: CustomComponentArtifact }
  | { kind: "error"; message: string };

/** The selected cloned section's registry card (F3.2), on the same four-state
 * shape the custom-component artifact uses. */
type FragmentCardState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; card: FragmentCard }
  | { kind: "error"; message: string };

/** The transient "Save as template" toast: a link to the new template doc on
 * success, or the server message on failure. Auto-dismisses. */
type TemplateToast =
  | { kind: "success"; documentId: string; title: string }
  | { kind: "error"; message: string };

/** The page a manual op targets when the document itself names none — an empty
 * (freshly created) web document has no pages to resolve against, and "home" is
 * the conventional first page every generator mints. */
const FALLBACK_PAGE_ID = "home";

/** Locate a page summary by id, falling back to the first page. */
function findWebPage(webDoc: WebDoc | null, pageId: string): WebPageSummary | null {
  const pages = webDoc?.pages ?? [];
  return pages.find((page) => page.id === pageId) ?? pages[0] ?? null;
}

/** Chat-mode suggestion chips: with a selection (element-scoped edits) and
 * without (page-level moves). Clicking one fills the composer — it does not
 * send. */
const SUGGESTION_CHIPS_SELECTED = [
  "Rewrite this section",
  "Swap this image for a better one",
  "Make this band dark"
];
const SUGGESTION_CHIPS_GLOBAL = [
  "Add a testimonials section",
  "Tighten the hero copy",
  "Add an FAQ"
];

/** The asset drawer's open state: inserting a fresh image, or replacing the
 * asset of a selected image node. */
type AssetDrawerState =
  | { mode: "insert" }
  | { mode: "replace"; pageId: string; nodeId: string }
  | { mode: "background"; pageId: string; nodeId: string };

/** True when keyboard focus sits in an editable field (composer/inspector
 * inputs) or an iframe — where undo/redo shortcuts must defer to the field. */
function focusIsEditable(): boolean {
  const active = document.activeElement as HTMLElement | null;
  if (!active) {
    return false;
  }
  const tag = active.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    tag === "IFRAME" ||
    active.isContentEditable
  );
}

let messageSeq = 0;
function nextMessageId(): string {
  messageSeq += 1;
  return `web-msg-${messageSeq}`;
}

/** The selected node's text, collapsed to one line and clipped for the chip's
 * muted excerpt. */
const CHIP_EXCERPT_MAX = 40;
function chipExcerpt(text: string): string {
  const collapsed = text.trim().replace(/\s+/g, " ");
  return collapsed.length > CHIP_EXCERPT_MAX
    ? `${collapsed.slice(0, CHIP_EXCERPT_MAX - 1)}…`
    : collapsed;
}

/** Known web progress event types → human copy. Unknown types are prettified
 * from the raw type text. */
const KNOWN_EVENT_LABELS: Record<string, string> = {
  web_page_authored: "Page authored",
  web_page_fetched: "Grounded page fetched",
  web_assets_searched: "Asset library searched",
  web_provenance_cited: "Evidence cited",
  web_preview_rendered: "Previews rendered (3 widths)",
  web_theme_resolved: "Theme resolved",
  web_turn_started: "Started",
  web_turn_planned: "Planned the build"
};

function humanizeWebEvent(type: string): string {
  const known = KNOWN_EVENT_LABELS[type];
  if (known) {
    return known;
  }
  const cleaned = type.replace(/^web_/, "").replace(/[_-]+/g, " ").trim();
  return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : type;
}

/** Condense a run's progress events into human labels, collapsing consecutive
 * duplicates. */
function condenseEvents(events: WebRunEvent[]): string[] {
  const labels: string[] = [];
  for (const event of events) {
    const label = humanizeWebEvent(event.type);
    if (labels.length === 0 || labels[labels.length - 1] !== label) {
      labels.push(label);
    }
  }
  return labels;
}

function readStoredBrief(documentId: string): string | null {
  try {
    const stored = window.sessionStorage.getItem(webPromptStorageKey(documentId));
    return stored && stored.trim() ? stored : null;
  } catch {
    return null;
  }
}

function clearStoredBrief(documentId: string): void {
  try {
    window.sessionStorage.removeItem(webPromptStorageKey(documentId));
  } catch {
    /* storage unavailable — nothing to clear */
  }
}

export function WebEditorApp({ documentId }: { documentId: string }): React.ReactElement {
  const [state, setState] = useState<ShellState>({ kind: "loading" });
  const [widthMode, setWidthMode] = useState<WidthMode>("fluid");
  const [composer, setComposer] = useState("");
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const [history, setHistory] = useState<TurnRecord[]>([]);
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const pendingRef = useRef<PendingTurn | null>(null);
  pendingRef.current = pending;

  // Bumped on each applied turn OR manual edit to quietly refetch the render +
  // document meta (and theme).
  const [reloadNonce, setReloadNonce] = useState(0);
  const [renderHtml, setRenderHtml] = useState<string | null>(null);
  const [renderStatus, setRenderStatus] = useState<RenderStatus>("idle");
  const [renderError, setRenderError] = useState<string | null>(null);

  const [railMode, setRailMode] = useState<RailMode>("chat");
  // The publish modal's open state.
  const [publishOpen, setPublishOpen] = useState(false);
  // The "Generate for accounts…" batch modal (template docs only) + the
  // "Save as template" toast/lifecycle.
  const [batchOpen, setBatchOpen] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [templateToast, setTemplateToast] = useState<TemplateToast | null>(null);
  const [theme, setTheme] = useState<WebTheme | null>(null);
  const [accounts, setAccounts] = useState<WebAccount[]>([]);
  const [customComponents, setCustomComponents] = useState<
    CustomComponentCatalogItem[]
  >([]);
  const [customComponentsStatus, setCustomComponentsStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [customArtifactState, setCustomArtifactState] =
    useState<CustomArtifactState>({ kind: "idle" });
  // The cloned-section inspector (F3.2): the selected clone's registry card, the
  // workspace's hidden-on-source sections, and the state of the three durable
  // actions. `fragmentNonce` is what a completed action refetches through — the
  // card and the dormant list are both server truth, not document state.
  const [fragmentCardState, setFragmentCardState] = useState<FragmentCardState>({
    kind: "idle"
  });
  const [dormantSections, setDormantSections] = useState<FragmentCard[]>([]);
  const [fragmentActionBusy, setFragmentActionBusy] = useState(false);
  const [fragmentActionError, setFragmentActionError] = useState<string | null>(null);
  const [fragmentNonce, setFragmentNonce] = useState(0);
  const [publishedVersion, setPublishedVersion] = useState<number | null>(null);
  // The inspector's selected node id — persisted across the manual-edit reload
  // (node ids are stable) and re-validated against the fresh doc below.
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  // Which page of a multi-page site the shell is looking at. This is only what
  // the USER asked for — `resolveActivePageId` below turns it into a page the
  // loaded document actually still has, so a page retired by an agent turn or
  // an undo silently falls back to the first one instead of stranding the
  // preview on a 404.
  const [requestedPageId, setRequestedPageId] = useState<string | null>(null);
  // The replace/insert-image drawer's open state (null = closed).
  const [assetDrawer, setAssetDrawer] = useState<AssetDrawerState | null>(null);

  // The live preview iframe and the per-render bridge nonce. A fresh nonce is
  // minted for every render fetch and validated on every inbound bridge message
  // (useWebBridgeSelection); a message tagged with a prior render's nonce is
  // dropped. The ref lets the selection listener read the current nonce without
  // re-arming on each fetch.
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const nonceRef = useRef<string>("");

  const document = state.kind === "ready" ? state.document : null;
  const webDoc = document?.webDoc ?? null;
  const hasContent = webDocumentHasContent(webDoc);
  const baseVersion = document?.currentVersion ?? null;
  const pages = webDoc?.pages ?? [];
  const activePageId = resolveActivePageId(pages, requestedPageId);
  // Op targeting needs a page id even for a document that names none.
  const opPageId = activePageId || FALLBACK_PAGE_ID;

  const reload = useCallback(() => setReloadNonce((nonce) => nonce + 1), []);
  const manualEdits = useWebManualEdits({ documentId, baseVersion, onReload: reload });

  // Persist one settled Lexical session as one versioned SetRichText op. All
  // range commands remain iframe-local until this boundary.
  const handleRichTextCommit = useCallback(
    (nodeId: string, content: RichTextDocument) => {
      const located = findWebNode(webDoc, nodeId, activePageId);
      manualEdits.applyOps(
        [setRichTextOp(located ? located.pageId : opPageId, nodeId, content)],
        "rich_text_commit"
      );
    },
    [webDoc, activePageId, opPageId, manualEdits]
  );

  // Mirror an inbound bridge selection into the persisted inspector id: a node
  // selection sets it; an explicit clear (click-off / Escape inside the iframe)
  // empties it. This runs ONLY on real `select` messages — a render rebuild
  // calls resetSelection (not onSelect), so the inspector stays on its stable
  // node id across a manual-edit reload.
  const handleBridgeSelect = useCallback((next: WebSelection | null) => {
    setActiveNodeId(next ? next.nodeId : null);
  }, []);

  // A generic bridge drop already speaks the canonical post-removal
  // destination contract: parent id + child index. Resolve the source's real
  // page, reject malformed/stale/structurally invalid drops in the pure
  // planner, then persist the resulting MoveNode through the normal envelope.
  const handleMoveNode = useCallback(
    (nodeId: string, newParentNodeId: string, index: number) => {
      const located = findWebNode(webDoc, nodeId, activePageId);
      const page = located ? findWebPage(webDoc, located.pageId) : null;
      if (!page) {
        return;
      }
      const plan = planCanvasNodeMove(page, nodeId, newParentNodeId, index);
      if (plan) {
        manualEdits.applyOps([plan.operation], plan.intent);
      }
    },
    [webDoc, activePageId, manualEdits]
  );

  // Resize handles report final CSS dimensions, never an inline-style
  // mutation. Resolve the canonical node/page and persist a surgical
  // set_node_classes operation so history, version checks, export, and the
  // agent all observe the same authored Tailwind classes.
  const handleResizeNode = useCallback(
    (nodeId: string, widthPx: number | null, heightPx: number | null) => {
      const located = findWebNode(webDoc, nodeId, activePageId);
      const page = located ? findWebPage(webDoc, located.pageId) : null;
      if (!page) {
        return;
      }
      const plan = planCanvasNodeResize(page, nodeId, widthPx, heightPx);
      if (plan) {
        manualEdits.applyOps([plan.operation], plan.intent);
      }
    },
    [webDoc, activePageId, manualEdits]
  );

  const {
    selection,
    nodeInfo,
    ready: bridgeReady,
    editingNodeId,
    richTextFormats,
    richTextSelection,
    richTextError,
    customComponentRuntime,
    clearSelection,
    resetSelection,
    previewComponent,
    selectNode,
    formatRichText,
    commandRichText,
    setRichTextToolbarActive,
    settleRichText
  } = useWebBridgeSelection({
    iframeRef,
    nonceRef,
    onRichTextCommit: handleRichTextCommit,
    onSelect: handleBridgeSelect,
    onMoveNode: handleMoveNode,
    onResizeNode: handleResizeNode
  });

  // Clicking the gray canvas region AROUND the iframe (never the rail/topbar,
  // and iframe-internal clicks stay in the frame) clears the selection and tells
  // the frame to drop its highlight.
  const clearFromBackdrop = useCallback(() => {
    setActiveNodeId(null);
    clearSelection();
  }, [clearSelection]);

  // Switching pages rebuilds the preview from a different page's nodes, so the
  // selection cannot survive it: the selected node is not on the incoming page
  // (or, worse, an id that happens to exist on both would silently re-point at
  // a different element). Drop it in both the shell and the frame.
  const handleSwitchPage = useCallback(
    (pageId: string) => {
      setRequestedPageId(pageId);
      setActiveNodeId(null);
      clearSelection();
    },
    [clearSelection]
  );

  // After a reload, drop the inspector selection if the node no longer exists.
  useEffect(() => {
    if (activeNodeId && !findWebNode(webDoc, activeNodeId, activePageId)) {
      setActiveNodeId(null);
    }
  }, [webDoc, activeNodeId, activePageId]);

  // A render rebuild clears the iframe DOM, but canonical node ids are stable.
  // Restore the real selection in the fresh frame so the outline, move/resize
  // handles, context chip, and inspector all remain continuous after a manual
  // edit or undo/redo.
  useEffect(() => {
    if (activeNodeId && renderStatus === "ready" && bridgeReady) {
      selectNode(activeNodeId);
    }
  }, [activeNodeId, renderStatus, bridgeReady, selectNode]);

  const located = findWebNode(webDoc, activeNodeId, activePageId);
  const inspectorNode = located?.node ?? null;
  const inspectorPageId = located?.pageId ?? opPageId;
  const inspectorPage = findWebPage(webDoc, inspectorPageId);
  const dialogs = React.useMemo(() => listDialogComponents(webDoc), [webDoc]);
  const richTextVariables = React.useMemo(
    () =>
      buildWebRichTextVariableCatalog(
        accounts,
        document?.accountId ?? null
      ),
    [accounts, document?.accountId]
  );

  // True when an asset id already lives on the document (a plain replace/insert
  // then needs no upsert_asset first).
  const docHasAsset = useCallback(
    (assetId: string): boolean => {
      const assets = (webDoc?.assets as Record<string, unknown> | undefined) ?? {};
      return Object.prototype.hasOwnProperty.call(assets, assetId);
    },
    [webDoc]
  );

  // Insert a plain (non-image) node from the palette. Placement + wrap + id
  // minting live in the engine; this only picks the page + selection context.
  const handleInsert = useCallback(
    (kind: InsertableKind) => {
      if (!inspectorPage) {
        return;
      }
      const op = buildInsertNodeOp({
        page: inspectorPage,
        selectedNodeId: activeNodeId,
        kind
      });
      manualEdits.applyOps([op], `insert_${kind}`);
    },
    [inspectorPage, activeNodeId, manualEdits]
  );

  const handleInsertCustomComponent = useCallback(
    (component: CustomComponentCatalogItem) => {
      if (!inspectorPage || component.accountId !== document?.accountId) {
        return;
      }
      const artifact = component.latestArtifact;
      const op = buildInsertCustomComponentOp({
        page: inspectorPage,
        selectedNodeId: activeNodeId,
        component: {
          slug: component.slug,
          artifactId: artifact.artifact_id,
          props: initialCustomComponentProps(artifact)
        }
      });
      manualEdits.applyOps([op], "insert_custom_component");
    },
    [
      inspectorPage,
      activeNodeId,
      document?.accountId,
      manualEdits
    ]
  );

  const handleEditCustomComponentWithAI = useCallback((node: WebNode) => {
    const label =
      customArtifactState.kind === "ready"
        ? customArtifactState.artifact.manifest.meta.name
        : node.slug ?? "this custom component";
    setComposer(`Update the custom component “${label}”: `);
    setRailMode("chat");
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [customArtifactState]);

  const handleInsertImage = useCallback(() => setAssetDrawer({ mode: "insert" }), []);

  const handleReplaceImage = useCallback(
    (nodeId: string) => setAssetDrawer({ mode: "replace", pageId: inspectorPageId, nodeId }),
    [inspectorPageId]
  );
  const handleChooseBackground = useCallback(
    (nodeId: string) =>
      setAssetDrawer({ mode: "background", pageId: inspectorPageId, nodeId }),
    [inspectorPageId]
  );

  // The asset drawer settled on a record: insert a new Image node, or replace
  // the selected image's asset — prepending upsert_asset when the record isn't
  // on the document yet (one batch = one undo step).
  const handleAssetPick = useCallback(
    (record: AssetRecord) => {
      const drawer = assetDrawer;
      setAssetDrawer(null);
      if (!drawer) {
        return;
      }
      const inDoc = docHasAsset(record.id);
      if (drawer.mode === "insert") {
        if (!inspectorPage) {
          return;
        }
        const insert = buildInsertNodeOp({
          page: inspectorPage,
          selectedNodeId: activeNodeId,
          kind: "image",
          image: { assetId: record.id, alt: record.label ?? "" }
        });
        manualEdits.applyOps(inDoc ? [insert] : [upsertAssetOp(record), insert], "insert_image");
        return;
      }
      if (drawer.mode === "replace") {
        const replace = replaceAssetOp(drawer.pageId, drawer.nodeId, record.id);
        manualEdits.applyOps(
          inDoc ? [replace] : [upsertAssetOp(record), replace],
          "replace_image"
        );
        return;
      }
      const targetPage = webDoc?.pages?.find((page) => page.id === drawer.pageId);
      const target = targetPage?.nodes?.[drawer.nodeId];
      if (!target || (target.kind !== "container" && target.kind !== "section")) {
        return;
      }
      const background = {
        asset_id: record.id,
        fit: target.background?.fit ?? "cover",
        position: target.background?.position ?? "center",
        scrim: target.background?.scrim ?? null
      } as const;
      const props: WebNodeProps =
        target.kind === "section"
          ? {
              kind: "section",
              tag: target.tag ?? "section",
              anchor_id: target.anchor_id ?? null,
              background
            }
          : {
              kind: "container",
              href: target.href?.trim() || null,
              new_tab: target.href ? (target.new_tab ?? false) : false,
              background
            };
      const setBackground = setNodePropsOp(drawer.pageId, drawer.nodeId, props);
      manualEdits.applyOps(
        inDoc ? [setBackground] : [upsertAssetOp(record), setBackground],
        "set_background_image"
      );
    },
    [assetDrawer, docHasAsset, inspectorPage, activeNodeId, manualEdits, webDoc]
  );

  // Keep the latest run events readable inside the hook's onDone callback (which
  // fires before the next render), so a settled turn's activity is captured.
  const eventsRef = useRef<WebRunEvent[]>([]);

  const handleTurnDone = useCallback((envelope: WebTurnDoneEnvelope) => {
    const settled = pendingRef.current;
    const status: TurnRecord["status"] = envelope.status === "applied" ? "applied" : "failed";
    const summary = typeof envelope.summary === "string" ? envelope.summary : null;
    const grounding = parseWebGroundingSummary(envelope.grounding);
    if (settled) {
      const record: TurnRecord = {
        id: settled.id,
        prompt: settled.prompt,
        context: settled.context,
        activity: condenseEvents(eventsRef.current),
        summary,
        grounding,
        status
      };
      setHistory((current) => [...current, record]);
      setPending(null);
    }
    if (status === "applied" || envelope.status === "conflicted") {
      setReloadNonce((nonce) => nonce + 1);
    }
  }, []);

  const turn = useWebAgentTurn({ documentId, onDone: handleTurnDone });
  eventsRef.current = turn.events;
  const isRunning = turn.phase === "running";

  // A transport error never reaches onDone — commit the failed record here.
  useEffect(() => {
    if (turn.phase !== "error") {
      return;
    }
    const settled = pendingRef.current;
    if (!settled) {
      return;
    }
    const record: TurnRecord = {
      id: settled.id,
      prompt: settled.prompt,
      context: settled.context,
      activity: condenseEvents(eventsRef.current),
      summary: turn.error,
      grounding: null,
      status: "failed"
    };
    setHistory((current) => [...current, record]);
    setPending(null);
  }, [turn.phase, turn.error]);

  // Load (and quietly refetch on reloadNonce) the document. Only the first load
  // shows the full loading state; a post-turn refetch keeps the shell in place.
  useEffect(() => {
    let cancelled = false;
    setState((prev) =>
      prev.kind === "ready" || prev.kind === "wrong-kind" ? prev : { kind: "loading" }
    );
    fetchWebDocument({ apiBaseUrl: editorApiBaseUrl() }, documentId)
      .then((loaded) => {
        if (cancelled) return;
        setState(
          loaded.docKind === "web"
            ? { kind: "ready", document: loaded }
            : { kind: "wrong-kind", document: loaded }
        );
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message:
            cause instanceof Error ? cause.message : "This website could not be loaded."
        });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, reloadNonce]);

  // Show the live preview once the document has content or a turn has applied.
  const shouldRender = state.kind === "ready" && (hasContent || reloadNonce > 0);

  useEffect(() => {
    if (!shouldRender) {
      return;
    }
    let cancelled = false;
    // The DOM is about to be rebuilt: rotate the bridge nonce (invalidating any
    // in-flight message from the old render) and drop the stale selection.
    const nonce = crypto.randomUUID();
    nonceRef.current = nonce;
    resetSelection();
    setRenderStatus("loading");
    setRenderError(null);
    fetchWebRenderHtml(
      { apiBaseUrl: editorApiBaseUrl() },
      documentId,
      TAILWIND_RUNTIME_SRC,
      { nonce },
      // Empty for a document with no pages — the fetch then sends no page_id at
      // all, which is the endpoint's own first-page default.
      activePageId
    )
      .then((result) => {
        if (cancelled) return;
        setRenderHtml(result.html);
        setRenderStatus("ready");
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setRenderError(
          cause instanceof Error ? cause.message : "The preview could not be rendered."
        );
        setRenderStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, shouldRender, reloadNonce, activePageId, resetSelection]);

  // Fetch the resolved theme (inspector swatches) once there is content, and
  // refresh it alongside each reload. Theme failure is non-fatal — the
  // inspector just shows no swatches.
  useEffect(() => {
    if (!shouldRender) {
      return;
    }
    let cancelled = false;
    fetchWebTheme({ apiBaseUrl: editorApiBaseUrl() }, documentId)
      .then((resolved) => {
        if (!cancelled) setTheme(resolved);
      })
      .catch(() => {
        if (!cancelled) setTheme(null);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, shouldRender, reloadNonce]);

  // Personalization variables come from the same persisted account records the
  // derive path consumes. A missing catalog is an honest empty state in the
  // toolbar, not a hard-coded list of placeholders.
  useEffect(() => {
    if (!shouldRender) {
      setAccounts([]);
      return;
    }
    let cancelled = false;
    listWebAccounts({ apiBaseUrl: editorApiBaseUrl() })
      .then((records) => {
        if (!cancelled) setAccounts(records);
      })
      .catch(() => {
        if (!cancelled) setAccounts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [shouldRender, reloadNonce]);

  // The picker is always account-local. A template/plain page without an
  // account shows an explanatory empty state rather than a cross-tenant global
  // component list.
  useEffect(() => {
    const accountId = document?.accountId;
    if (!shouldRender || !accountId) {
      setCustomComponents([]);
      setCustomComponentsStatus("idle");
      return;
    }
    let cancelled = false;
    setCustomComponentsStatus("loading");
    listCustomComponents({ apiBaseUrl: editorApiBaseUrl() }, accountId)
      .then((components) => {
        if (cancelled) return;
        setCustomComponents(components);
        setCustomComponentsStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setCustomComponents([]);
        setCustomComponentsStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [document?.accountId, shouldRender, reloadNonce]);

  // Inspector metadata resolves the selected immutable artifact, even when it
  // is an older pin rather than the family currently offered by the picker.
  useEffect(() => {
    const accountId = document?.accountId;
    const artifactId =
      inspectorNode?.kind === "custom_component"
        ? inspectorNode.artifact_id
        : null;
    if (!accountId || !artifactId) {
      setCustomArtifactState({ kind: "idle" });
      return;
    }
    const cached = customComponents
      .map((item) => item.latestArtifact)
      .find((artifact) => artifact.artifact_id === artifactId);
    if (cached) {
      setCustomArtifactState({ kind: "ready", artifact: cached });
      return;
    }
    let cancelled = false;
    setCustomArtifactState({ kind: "loading" });
    fetchCustomComponentArtifact(
      { apiBaseUrl: editorApiBaseUrl() },
      accountId,
      artifactId
    )
      .then((artifact) => {
        if (!cancelled) setCustomArtifactState({ kind: "ready", artifact });
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setCustomArtifactState({
          kind: "error",
          message:
            cause instanceof Error ? cause.message : "Artifact could not be loaded."
        });
      });
    return () => {
      cancelled = true;
    };
  }, [
    document?.accountId,
    inspectorNode?.kind,
    inspectorNode?.artifact_id,
    customComponents
  ]);

  // ── the cloned-section (fragment) inspector, F3.2 ──────────────────────────
  // The selected clone's registry card — its status, condition, repair lineage,
  // hidden-on-source provenance and slot manifest. None of that is in the
  // document: the node carries an artifact id and flat slot values, and every
  // other fact about the section lives in the registry.
  useEffect(() => {
    const fragmentId =
      inspectorNode?.kind === "fragment" ? inspectorNode.fragment_id : null;
    if (!fragmentId) {
      setFragmentCardState({ kind: "idle" });
      return;
    }
    let cancelled = false;
    setFragmentCardState({ kind: "loading" });
    fetchFragmentCard({ apiBaseUrl: editorApiBaseUrl() }, fragmentId)
      .then((card) => {
        if (!cancelled) setFragmentCardState({ kind: "ready", card });
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setFragmentCardState({
          kind: "error",
          message:
            cause instanceof Error
              ? cause.message
              : "The cloned section could not be loaded."
        });
      });
    return () => {
      cancelled = true;
    };
  }, [inspectorNode?.kind, inspectorNode?.fragment_id, fragmentNonce]);

  // Every section the source site HIDES (D-F8). They are on no page, so nothing
  // can select one — the inspector is the only place a human is shown them, and
  // the list is what it reaches them through.
  useEffect(() => {
    if (!shouldRender) {
      setDormantSections([]);
      return;
    }
    let cancelled = false;
    fetchDormantFragments({ apiBaseUrl: editorApiBaseUrl() })
      .then((sections) => {
        if (!cancelled) setDormantSections(sections);
      })
      .catch(() => {
        // Non-fatal: a workspace with no hidden sections and a workspace whose
        // listing failed both leave the human with nothing to activate, and a
        // banner over the whole inspector would be louder than the fact.
        if (!cancelled) setDormantSections([]);
      });
    return () => {
      cancelled = true;
    };
  }, [shouldRender, reloadNonce, fragmentNonce]);

  /** One durable fragment action (P-7's isolation render, D-F8's activation,
   * R17-2's retire), with the server's own refusal surfaced rather than a
   * status code — every one of them is a sentence a human has to act on. */
  const runFragmentAction = useCallback(
    (action: (fragmentId: string) => Promise<FragmentCard>, fragmentId: string) => {
      setFragmentActionBusy(true);
      setFragmentActionError(null);
      action(fragmentId)
        .then(() => setFragmentNonce((nonce) => nonce + 1))
        .catch((cause: unknown) =>
          setFragmentActionError(
            cause instanceof Error ? cause.message : "The section could not be updated."
          )
        )
        .finally(() => setFragmentActionBusy(false));
    },
    []
  );

  const handleGenerateFragmentPreview = useCallback(
    (fragmentId: string) =>
      runFragmentAction(
        (id) => generateFragmentPreview({ apiBaseUrl: editorApiBaseUrl() }, id),
        fragmentId
      ),
    [runFragmentAction]
  );
  const handleActivateFragment = useCallback(
    (fragmentId: string) =>
      runFragmentAction(
        (id) => activateFragment({ apiBaseUrl: editorApiBaseUrl() }, id),
        fragmentId
      ),
    [runFragmentAction]
  );
  const handleRetireFragment = useCallback(
    (fragmentId: string) =>
      runFragmentAction(
        (id) => retireFragment({ apiBaseUrl: editorApiBaseUrl() }, id),
        fragmentId
      ),
    [runFragmentAction]
  );

  /** The document's own asset records — what an asset slot may resolve to
   * (F1 ruling #9 / LUMW0035), so the picker offers exactly these. */
  const documentAssets = useMemo<FragmentAssetOption[]>(() => {
    const assets = webDoc?.assets;
    if (!assets || typeof assets !== "object") {
      return [];
    }
    return Object.entries(assets as Record<string, unknown>)
      .map(([id, record]) => {
        const label = (record as { label?: unknown } | null)?.label;
        return { id, label: typeof label === "string" && label ? label : id };
      })
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [webDoc?.assets]);

  useEffect(() => {
    if (!shouldRender) {
      setPublishedVersion(null);
      return;
    }
    let cancelled = false;
    fetchWebPublishInfo({ apiBaseUrl: editorApiBaseUrl() }, documentId)
      .then((state) => {
        if (!cancelled) {
          setPublishedVersion(state.published ? state.docVersion : null);
        }
      })
      .catch(() => {
        if (!cancelled) setPublishedVersion(null);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, shouldRender, reloadNonce, publishOpen]);

  // Undo/redo keyboard: ⌘Z / ⇧⌘Z (Ctrl on non-mac). Ignored while a turn runs,
  // a mutation is in flight, or focus is in an editable field / the iframe.
  const undoDepth = document?.undoDepth ?? 0;
  const redoDepth = document?.redoDepth ?? 0;
  const historyBusy = isRunning || manualEdits.busy;
  const canUndo = undoDepth > 0 && !historyBusy;
  const canRedo = redoDepth > 0 && !historyBusy;
  const { undo, redo } = manualEdits;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") {
        return;
      }
      if (historyBusy || focusIsEditable()) {
        return;
      }
      event.preventDefault();
      if (event.shiftKey) {
        if (redoDepth > 0) redo();
      } else if (undoDepth > 0) {
        undo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [historyBusy, undoDepth, redoDepth, undo, redo]);

  const startTurn = useCallback(
    (prompt: string) => {
      const trimmed = prompt.trim();
      if (!trimmed || isRunning || baseVersion == null) {
        return;
      }
      // Snapshot the active chip so the turn targets it and the bubble records
      // the context, even though the chip itself persists after send.
      const context: TurnContext | null = selection ? { nodeId: selection.nodeId } : null;
      const targetNodeIds = selection ? [selection.nodeId] : undefined;
      setPending({ id: nextMessageId(), prompt: trimmed, context });
      setComposer("");
      turn.start(trimmed, baseVersion, null, targetNodeIds);
    },
    [isRunning, turn, selection, baseVersion]
  );

  // Queued-brief handoff (runs once, after the first successful load): auto-send
  // on an empty document, prefill the composer on one that already has content.
  const briefHandledRef = useRef(false);
  useEffect(() => {
    if (state.kind !== "ready" || briefHandledRef.current) {
      return;
    }
    briefHandledRef.current = true;
    const brief = readStoredBrief(documentId);
    if (!brief) {
      return;
    }
    clearStoredBrief(documentId);
    if (webDocumentHasContent(state.document.webDoc)) {
      setComposer(brief);
    } else {
      startTurn(brief);
    }
  }, [state, documentId, startTurn]);

  const onComposerSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    startTurn(composer);
  };

  const onComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      startTurn(composer);
    }
  };

  const title = document?.title ?? "Website";

  // Export the built site as a zip: the endpoint sets Content-Disposition, so an
  // anchor click to the absolute API URL is enough (no fetch/blob). `document`
  // is shadowed by the loaded doc in this scope — reach the DOM via `window`.
  const handleExport = useCallback(() => {
    const href = new URL(
      `/documents/${encodeURIComponent(documentId)}/web/export`,
      editorApiBaseUrl()
    ).toString();
    const anchor = window.document.createElement("a");
    anchor.href = href;
    anchor.rel = "noopener";
    window.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }, [documentId]);

  // Clone the current doc into a fresh template document. On success a toast
  // links to the new template; failure surfaces the server message in the same
  // toast slot. The topbar reflects `document.isTemplate` for THIS doc, so a
  // save-as-template opens the new one rather than mutating this one.
  const isTemplate = document?.isTemplate ?? false;
  const handleSaveTemplate = useCallback(async () => {
    setSavingTemplate(true);
    setTemplateToast(null);
    try {
      const created = await saveWebTemplate({ apiBaseUrl: editorApiBaseUrl() }, documentId, title);
      setTemplateToast({
        kind: "success",
        documentId: created.documentId,
        title: created.title || title
      });
    } catch (cause) {
      setTemplateToast({
        kind: "error",
        message: cause instanceof Error ? cause.message : "Could not save as template."
      });
    } finally {
      setSavingTemplate(false);
    }
  }, [documentId, title]);

  // Auto-dismiss the template toast (long enough to click the link).
  useEffect(() => {
    if (!templateToast) {
      return;
    }
    const timer = window.setTimeout(() => setTemplateToast(null), 12000);
    return () => window.clearTimeout(timer);
  }, [templateToast]);

  const liveActivity = pending ? condenseEvents(turn.events) : [];
  const holderStyle: React.CSSProperties | undefined =
    widthMode === "fluid" ? undefined : { width: `${widthMode}px` };

  const renderCanvas = (): React.ReactElement => {
    if (renderHtml) {
      return (
        <>
          <div className="web-canvas-pane">
            <div
              className={`web-preview-holder${widthMode === "fluid" ? " is-fluid" : ""}`}
              style={holderStyle}
            >
              <iframe
                ref={iframeRef}
                className="web-preview-frame"
                sandbox="allow-scripts"
                srcDoc={renderHtml}
                title="Website preview"
              />
            </div>
          </div>
          {isRunning ? (
            <span className="status-pill web-generating-pill" role="status">
              <span className="dot" />
              Generating…
            </span>
          ) : null}
        </>
      );
    }

    if (renderStatus === "error") {
      return (
        <div className="web-canvas-frame" role="alert">
          <span className="status-pill is-error">Preview failed</span>
          <p className="web-empty-hint">{renderError}</p>
        </div>
      );
    }

    if (isRunning || renderStatus === "loading") {
      return (
        <div className="web-canvas-frame" role="status">
          <span className="status-pill">
            <span className="dot web-loading-dot" />
            Generating your website…
          </span>
          <p className="web-empty-hint">The agent is authoring your pages.</p>
        </div>
      );
    }

    return (
      <div className="web-canvas-frame">
        <p className="title web-empty-title">Your website will render here</p>
        <p className="web-empty-hint">
          Describe what you want in the chat and the agent will build it.
        </p>
      </div>
    );
  };

  return (
    <>
      <header className="web-topbar">
        <span className="web-topbar-title">{title}</span>
        <span className="web-beta-pill">Website · beta</span>
        {isTemplate ? <span className="web-beta-pill">Template</span> : null}
        <span className="web-topbar-spacer" />
        {state.kind === "ready" ? (
          <div className="web-history-group" role="group" aria-label="History">
            <button
              type="button"
              className="web-history-btn"
              onClick={undo}
              disabled={!canUndo}
              aria-label="Undo"
              title="Undo (⌘Z)"
            >
              ↺
            </button>
            <button
              type="button"
              className="web-history-btn"
              onClick={redo}
              disabled={!canRedo}
              aria-label="Redo"
              title="Redo (⇧⌘Z)"
            >
              ↻
            </button>
          </div>
        ) : null}
        {state.kind === "ready" && pages.length > 1 ? (
          <select
            className="web-page-select"
            aria-label="Page"
            title="Page"
            value={activePageId}
            onChange={(event) => handleSwitchPage(event.target.value)}
          >
            {pages.map((page) => (
              <option key={page.id} value={page.id}>
                {page.name} · {page.route}
              </option>
            ))}
          </select>
        ) : null}
        {state.kind === "ready" ? (
          <div className="web-width-group" role="group" aria-label="Preview width">
            {WIDTH_CHIPS.map((chip) => (
              <button
                key={chip.mode}
                type="button"
                className={`web-width-chip${widthMode === chip.mode ? " is-selected" : ""}`}
                aria-pressed={widthMode === chip.mode}
                onClick={() => setWidthMode(chip.mode)}
              >
                {chip.label}
              </button>
            ))}
          </div>
        ) : null}
        {state.kind === "ready" ? (
          <div className="web-topbar-actions" role="group" aria-label="Publish">
            {isTemplate ? (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setBatchOpen(true)}
              >
                Generate for accounts…
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleSaveTemplate}
              disabled={savingTemplate}
            >
              {savingTemplate ? "Saving…" : "Save as template"}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleExport}
            >
              Export
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setPublishOpen(true)}
            >
              Publish
            </button>
          </div>
        ) : null}
        <Link href="/new" className="web-back-link">
          New project
        </Link>
      </header>

      {publishOpen && state.kind === "ready" ? (
        <WebPublishDialog
          documentId={documentId}
          title={title}
          onClose={() => setPublishOpen(false)}
        />
      ) : null}

      {batchOpen && state.kind === "ready" ? (
        <WebBatchDialog
          documentId={documentId}
          title={title}
          onClose={() => setBatchOpen(false)}
        />
      ) : null}

      {templateToast ? (
        <div className="web-toast" role="status">
          {templateToast.kind === "success" ? (
            <>
              <span className="web-toast-msg">Saved as a template.</span>
              <Link
                className="web-toast-link"
                href={`/web/${encodeURIComponent(templateToast.documentId)}`}
              >
                Open template
              </Link>
            </>
          ) : (
            <span className="web-toast-msg">{templateToast.message}</span>
          )}
          <button
            type="button"
            className="web-toast-close"
            onClick={() => setTemplateToast(null)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ) : null}

      {editingNodeId && richTextSelection ? (
        <WebRichTextToolbar
          iframeRef={iframeRef}
          nodeId={editingNodeId}
          selection={richTextSelection}
          theme={theme}
          variables={richTextVariables}
          disabled={manualEdits.busy}
          command={commandRichText}
          setInteractionActive={setRichTextToolbarActive}
          settle={settleRichText}
        />
      ) : null}

      {state.kind === "loading" ? (
        <div className="web-notice" role="status">
          <p>Loading website…</p>
        </div>
      ) : state.kind === "error" ? (
        <div className="web-notice" role="alert">
          <span className="status-pill is-error">Couldn’t open this website</span>
          <p>{state.message}</p>
        </div>
      ) : state.kind === "wrong-kind" ? (
        <div className="web-notice" role="alert">
          <span className="status-pill is-error">Not a website document</span>
          <p>This document is a design, not a website. Open it in the canvas editor instead.</p>
          <Link
            className="btn btn-ghost btn-sm"
            href={`/?document=${encodeURIComponent(documentId)}`}
          >
            Open in editor
          </Link>
        </div>
      ) : (
        <main className="web-workspace">
          {/* Clicks that land on the canvas region backdrop (padding around the
              iframe — never the frame's own content, which is isolated) clear the
              selection. */}
          <section className="web-canvas-region" onClick={clearFromBackdrop}>
            {renderCanvas()}
          </section>

          <aside className="web-chat" aria-label="Website chat">
            <div className="web-rail-head" role="tablist" aria-label="Rail mode">
              <button
                type="button"
                role="tab"
                aria-selected={railMode === "chat"}
                className={`web-rail-tab${railMode === "chat" ? " is-selected" : ""}`}
                onClick={() => setRailMode("chat")}
              >
                Chat
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={railMode === "inspect"}
                className={`web-rail-tab${railMode === "inspect" ? " is-selected" : ""}`}
                onClick={() => setRailMode("inspect")}
              >
                Inspect
              </button>
            </div>

            {railMode === "inspect" ? (
              <div className="web-insp-scroll">
                <div className="web-insp-toolbar">
                  <WebInsertPalette
                    onInsert={handleInsert}
                    onInsertImage={handleInsertImage}
                    onInsertCustomComponent={handleInsertCustomComponent}
                    customComponents={customComponents}
                    customComponentsStatus={customComponentsStatus}
                    customComponentsUnavailableReason={
                      document?.accountId
                        ? null
                        : "Assign this website to an account to use custom components."
                    }
                    disabled={manualEdits.busy || inspectorPage == null}
                  />
                </div>
                {assetDrawer ? (
                  <WebAssetDrawer
                    mode={assetDrawer.mode}
                    onPick={handleAssetPick}
                    onClose={() => setAssetDrawer(null)}
                  />
                ) : null}
                <WebInspectorPanel
                  node={inspectorNode}
                  nodeInfo={
                    nodeInfo && nodeInfo.nodeId === inspectorNode?.id ? nodeInfo : null
                  }
                  pageId={inspectorPageId}
                  pages={pages}
                  page={inspectorPage}
                  theme={theme}
                  dialogs={dialogs}
                  previewComponent={previewComponent}
                  selectNode={selectNode}
                  onReplaceImage={handleReplaceImage}
                  onChooseBackground={handleChooseBackground}
                  editingNodeId={editingNodeId}
                  richTextFormats={richTextFormats}
                  formatRichText={formatRichText}
                  customComponentArtifact={
                    customArtifactState.kind === "ready"
                      ? customArtifactState.artifact
                      : null
                  }
                  customComponentArtifactStatus={customArtifactState.kind}
                  customComponentArtifactError={
                    customArtifactState.kind === "error"
                      ? customArtifactState.message
                      : null
                  }
                  customComponentRuntime={
                    inspectorNode
                      ? customComponentRuntime[inspectorNode.id] ?? null
                      : null
                  }
                  customComponentRepublishRequired={
                    publishedVersion != null &&
                    baseVersion != null &&
                    baseVersion > publishedVersion
                  }
                  onEditCustomComponentWithAI={handleEditCustomComponentWithAI}
                  onRepublish={() => setPublishOpen(true)}
                  fragmentCard={
                    fragmentCardState.kind === "ready" ? fragmentCardState.card : null
                  }
                  fragmentCardStatus={fragmentCardState.kind}
                  fragmentCardError={
                    fragmentCardState.kind === "error" ? fragmentCardState.message : null
                  }
                  dormantSections={dormantSections}
                  documentAssets={documentAssets}
                  onGenerateFragmentPreview={handleGenerateFragmentPreview}
                  onActivateFragment={handleActivateFragment}
                  onRetireFragment={handleRetireFragment}
                  fragmentActionBusy={fragmentActionBusy}
                  fragmentActionError={fragmentActionError}
                  applyOps={manualEdits.applyOps}
                  busy={manualEdits.busy}
                  note={manualEdits.note}
                  error={richTextError ?? manualEdits.error}
                />
              </div>
            ) : (
              <>
            <div className="web-chat-scroll">
              {history.length === 0 && !pending ? (
                <p className="web-chat-empty">
                  Describe your website and the agent will build it — layout, copy, and styling.
                </p>
              ) : null}

              {history.map((record) => (
                <React.Fragment key={record.id}>
                  <div className="web-msg is-user">
                    {record.context ? (
                      <span className="web-msg-context">
                        <span className="web-context-glyph" aria-hidden="true">
                          &lt;/&gt;
                        </span>
                        {record.context.nodeId}
                      </span>
                    ) : null}
                    {record.prompt}
                  </div>
                  {record.activity.length > 0 ? (
                    <ul className="web-activity">
                      {record.activity.map((label, index) => (
                        <li key={`${record.id}-act-${index}`}>{label}</li>
                      ))}
                    </ul>
                  ) : null}
                  {record.summary != null ? (
                    <div
                      className={`web-msg is-agent${
                        record.status === "failed" ? " is-error" : ""
                      }`}
                    >
                      {record.summary}
                    </div>
                  ) : null}
                  {record.grounding ? (
                    <details className="web-grounding">
                      <summary>
                        Grounded in {record.grounding.sources.length} source
                        {record.grounding.sources.length === 1 ? "" : "s"}
                        {record.grounding.citationCount > 0
                          ? ` · ${record.grounding.citationCount} citation${
                              record.grounding.citationCount === 1 ? "" : "s"
                            }`
                          : ""}
                      </summary>
                      <ul>
                        {record.grounding.sources.map((source) => (
                          <li key={`${record.id}-${source.sourceId}`}>
                            <span className="web-grounding-kind">
                              {source.kind === "page" ? "Page" : "Asset"}
                            </span>
                            {source.url ? (
                              <a href={source.url} target="_blank" rel="noreferrer">
                                {source.label}
                              </a>
                            ) : (
                              <span>{source.label}</span>
                            )}
                            {source.assetId ? (
                              <code className="web-grounding-id">{source.assetId}</code>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </React.Fragment>
              ))}

              {pending ? (
                <>
                  <div className="web-msg is-user">
                    {pending.context ? (
                      <span className="web-msg-context">
                        <span className="web-context-glyph" aria-hidden="true">
                          &lt;/&gt;
                        </span>
                        {pending.context.nodeId}
                      </span>
                    ) : null}
                    {pending.prompt}
                  </div>
                  {liveActivity.length > 0 ? (
                    <ul className="web-activity is-live">
                      {liveActivity.map((label, index) => (
                        <li key={`live-act-${index}`}>{label}</li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null}
            </div>

            <div className="web-suggestions" role="group" aria-label="Suggestions">
              {(selection ? SUGGESTION_CHIPS_SELECTED : SUGGESTION_CHIPS_GLOBAL).map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className="web-suggestion-chip"
                  disabled={isRunning}
                  onClick={() => setComposer(chip)}
                >
                  {chip}
                </button>
              ))}
            </div>
            <form className="web-composer" onSubmit={onComposerSubmit}>
              {selection ? (
                <div className="web-context-chip">
                  <span className="web-context-glyph" aria-hidden="true">
                    &lt;/&gt;
                  </span>
                  <span className="web-context-chip-label">{selectionChipLabel(selection)}</span>
                  {selection.text ? (
                    <span className="web-context-chip-excerpt">{chipExcerpt(selection.text)}</span>
                  ) : null}
                  <button
                    type="button"
                    className="web-context-chip-clear"
                    onClick={clearSelection}
                    aria-label="Clear selected element"
                  >
                    ×
                  </button>
                </div>
              ) : null}
              <div className="web-composer-row">
                <textarea
                  ref={composerRef}
                  value={composer}
                  onChange={(event) => setComposer(event.target.value)}
                  onKeyDown={onComposerKeyDown}
                  placeholder={isRunning ? "The agent is working…" : "Describe a change…"}
                  rows={1}
                  disabled={isRunning}
                  aria-label="Message the website agent"
                />
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isRunning || composer.trim().length === 0}
                >
                  Send
                </button>
              </div>
            </form>
              </>
            )}
          </aside>
        </main>
      )}
    </>
  );
}
