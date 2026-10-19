"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  customComponentPropsToOperation,
  type CustomComponentFormBinding,
  type CustomComponentPropCommit,
} from "../adapter/custom-component-form";
import {
  cloneTextEditsFor,
  type CloneTextEditRow,
} from "../adapter/clone-text-edits";
import { buildWebLayerRows } from "../adapter/layers";
import { richTextCommitToOperation } from "../adapter/rich-text-commit";
import {
  richTextLinkCommit,
  richTextLinkSectionVisible,
  type RichTextLinkBinding,
  type RichTextLinkTrigger,
} from "../adapter/rich-text-link-section";
import { buildThemeColorOptions, tokenLabel } from "../adapter/theme-options";
import type {
  WebAnnotationsCanvasBinding,
  WebArtifactCanvasControls,
  WebRichTextSessionState,
} from "../components/web-artifact-canvas";
import type {
  RichTextDocument,
  WebFragmentTextOverride,
  WebPageSummary,
} from "../engine/webDocuments";
import { useCustomComponentArtifact } from "./use-custom-component-artifact";
import { useInspectorWrites } from "./use-inspector-writes";
import { useReplaceImage } from "./use-replace-image";
import { useWebAnnotations } from "./use-web-annotations";
import { useWebArtifactSelection } from "./use-web-artifact-selection";
import { useWebTheme } from "./use-web-theme";
import type { WebElementAddress } from "../engine/webBridge";
import type { InspectorPresentationState } from "@/features/chat-shell/hooks/use-inspector-controller";

// Chat-flow slice 2: the web editing session, extracted VERBATIM from
// EditorSurface's hooks region so a second mount (the chats route's artifact
// rail + inspector dock) composes the exact same machinery. The hook TAKES
// `activeArtifactId` (and the page's `documentIds` map) as input and owns NO
// shell controller — the artifact route and the chats route each keep their
// own; this is only the document/selection/write/theme session behind them.

export type WebEditingSession = ReturnType<typeof useWebEditingSession>;

/** F5 task 18: one page of the loaded document, as the shell's page switcher
 * needs it (the document's own node maps stay inside the session). */
export interface WebSessionPage {
  id: string;
  name: string;
  route: string;
}

/**
 * F5 task 19: everything the web inspector's Page section needs, or `null` when
 * the section must not be on screen at all.
 *
 * The "no node selected" rule lives HERE, in one place, rather than being
 * re-derived at each of the two inspector mounts (the artifact route and the
 * chats route) where it could drift: a selected node means the panel is showing
 * that node, and the page controls are not part of it.
 */
export interface WebPageSectionBinding {
  /** The page the switcher and the canvas are on — the one this section edits. */
  activePage: WebSessionPage;
  pages: readonly WebSessionPage[];
  /** A write is in flight (the one-in-flight rule) — the controls go inert. */
  busy: boolean;
  /** The ENGINE's own refusal code behind the write path's current inline error
   * (`op.route_exists`, `op.route_invalid`, …), so the route field can say WHICH
   * refusal this was in its own words. Deliberately NOT the error prose: a
   * failure this section does not recognise is not its to narrate, and stays in
   * the inspector's one existing error line. */
  errorEngineCode: string | null;
  onAddPage: (page: { id: string; name: string; route: string }) => void;
  onRemovePage: (pageId: string) => void;
  onSetPageMeta: (pageId: string, meta: { name?: string; route?: string }) => void;
}

/**
 * R-A6 (slice 3): the human's own text edits inside the selected cloned band —
 * everything the inspector's "Cloned text edits" section needs, or `null` when
 * the selection owns no such list at all.
 *
 * `nodeId` is the FRAGMENT's, never the wrapper section's, because that is the
 * node the write op must be addressed to. Which node owns the list is decided by
 * one pure rule (`adapter/clone-text-edits`), so a wrapper and its clone cannot
 * disagree about whose edits these are.
 */
export interface WebCloneTextEditsBinding {
  pageId: string;
  nodeId: string;
  overrides: readonly CloneTextEditRow[];
  /** A write is in flight (the one-in-flight rule) — Clear goes inert. */
  busy: boolean;
  onClear: (path: string) => void;
}

/**
 * F5 task 18: which page of a multi-page web document is active.
 *
 * Pure and DERIVED, never reset in an effect (the same discipline
 * `useWebArtifactSelection` documents): the requested page when the currently
 * loaded document still has it, the first page otherwise — so a reload that
 * dropped the active page falls back instead of asking the render seam for a
 * page that no longer exists — and null when the document has no pages at all.
 */
export function resolveActivePageId(
  pages: readonly WebPageSummary[] | undefined,
  requested: string | null,
): string | null {
  if (!pages || pages.length === 0) return null;
  const requestedPage = pages.find((page) => page.id === requested);
  return requestedPage?.id ?? pages[0].id;
}

export function useWebEditingSession({
  activeArtifactId,
  documentIds,
  enabled = true,
  onScreen = true,
  onSendAnnotation,
}: {
  /** The caller's OWN shell controller's active artifact tab. */
  activeArtifactId: string | null;
  /** W2.1: artifact id → design-document id, from the page's read-seam fetch. */
  documentIds: Record<string, string> | undefined;
  /**
   * AD2.7 (audit finding F3): the caller's kind guard.
   *
   * Both mounts call this hook unconditionally — React forbids a conditional
   * hook — so before AD2.7 an AD document was fed to the WEB legs: every ad
   * load fetched `/documents/{id}/web/theme` and `/documents/{id}` (web shape)
   * and swallowed the resulting 409s. The kind therefore rides in as a
   * PARAMETER: a mount showing an ad passes `false` and every leg below sees a
   * null document id, which is already the "no document, no fetch" path each
   * of them has always had.
   *
   * Defaults to `true`, so a caller that only mounts web artifacts (and every
   * existing test) behaves exactly as before.
   */
  enabled?: boolean;
  /**
   * Slice 2 (R-A2): the comment box's **Send to chat** — store the note and
   * submit the turn in one gesture.
   *
   * A PARAMETER rather than something this hook can do on its own, because
   * only a mount with a composer can submit a turn: the chats route passes it,
   * the artifact route (which has no composer) passes nothing and the canvas
   * then renders no Send button at all — the binding's own contract.
   *
   * Must be identity-stable; it goes straight into the one memoised canvas
   * binding, and a fresh function per render would hand the iframe a new
   * binding on every keystroke in the composer.
   */
  /** The artifact is on screen (the artifact surface, panel open): undo/redo keys act only then
   * (review finding S2b-6). Defaults to true. */
  onScreen?: boolean;
  onSendAnnotation?: (note: string) => void;
}) {
  const activeDocumentId =
    enabled && activeArtifactId
      ? (documentIds?.[activeArtifactId] ?? null)
      : null;
  // W2.2: the canvas bridge's nonce-validated selections joined with the
  // loaded document → {node, nodeInfo} + schema + hydrated inspector state.
  // W3.2: after a committed write the reload nonce bumps — the document
  // refetches (fresh currentVersion → next base_version) and the canvas
  // remounts its render (rotating the bridge nonce with the rebuilt DOM).
  const [reloadNonce, setReloadNonce] = useState(0);
  const webSelection = useWebArtifactSelection(activeDocumentId, reloadNonce);
  const canvasControls = useRef<WebArtifactCanvasControls | null>(null);
  const onWriteReload = useCallback(() => {
    setReloadNonce((nonce) => nonce + 1);
  }, []);
  const writes = useInspectorWrites({
    document: webSelection.document,
    documentId: activeDocumentId,
    onReload: onWriteReload,
    onScreen,
    selection: webSelection.selection,
  });

  // W4.8a: the in-iframe rich-text session, mirrored up by the canvas. Held
  // here because two surfaces outside the canvas need it — the inline error
  // slot, and the inspector's conditional Link-to.
  const [richTextSession, setRichTextSession] = useState<WebRichTextSessionState>({
    editingNodeId: null,
    richTextSelection: null,
    richTextError: null,
  });

  // W4.8b: the inspector's range-bound Link-to reports an invalid href, and
  // the one inline error line under the inspector header shows it (no new UI —
  // the ledgered failure ruling). Stamped with the node whose session raised
  // it, so a stale error can never reappear over a LATER session's section.
  const [richTextLinkError, setRichTextLinkError] = useState<{
    message: string;
    nodeId: string;
  } | null>(null);

  // The commit path: ONE `set_rich_text` op through the SAME manual-edits
  // controller every inspector write uses (one in-flight mutation,
  // `base_version` per apply, 409 → quiet reload + note, 422 → first
  // diagnostic inline). Source semantics, WebEditorApp.tsx:331-340.
  //
  // Carried-over source caveat: `applyOps` no-ops while another write is in
  // flight, and by commit time the frame has already destroyed its Lexical
  // session — so a commit that lands mid-write is lost. The toolbar's
  // `disabled` (richTextBusy) narrows the window; the frame's own
  // focusout/⌘-Enter paths can still hit it. Same upstream.
  const applyOps = writes.applyOps;
  const loadedDocument = webSelection.document;
  const onRichTextCommit = useCallback(
    (nodeId: string, content: RichTextDocument) => {
      const operation = richTextCommitToOperation(loadedDocument, nodeId, content);
      if (!operation) return;
      applyOps([operation], "rich_text_commit");
    },
    [applyOps, loadedDocument],
  );

  // W4.8b (contract item 3): the TEXT schema's "Link to" section binds to the
  // LIVE rich-text range — so it exists only while there is one, and its
  // writes are range-link COMMANDS, never the node-prop write path (a text
  // node has no href to write). Absent ⇒ the inspector renders no Link-to
  // section for text at all (mapping contract §2: hidden = absent).
  const richTextEditingNodeId = richTextSession.editingNodeId;
  const richTextRangeSelection = richTextSession.richTextSelection;
  const onRichTextLinkInteraction = useCallback(
    (active: boolean) => {
      if (!richTextEditingNodeId) return;
      canvasControls.current?.setRichTextInteractionActive(
        richTextEditingNodeId,
        active,
      );
    },
    [richTextEditingNodeId],
  );
  const onRichTextSubmitLink = useCallback(
    (href: string, newTab: boolean, trigger: RichTextLinkTrigger) => {
      if (!richTextEditingNodeId || !richTextRangeSelection) return;
      const decision = richTextLinkCommit({
        href,
        linkState: richTextRangeSelection.link.state,
        newTab,
        trigger,
      });
      if (decision.kind === "invalid") {
        setRichTextLinkError({
          message: decision.error,
          nodeId: richTextEditingNodeId,
        });
        return;
      }
      setRichTextLinkError(null);
      if (decision.kind === "none") return;
      canvasControls.current?.commandRichText(
        richTextEditingNodeId,
        decision.command,
      );
    },
    [richTextEditingNodeId, richTextRangeSelection],
  );
  const richTextLinkVisible = richTextLinkSectionVisible(richTextSession);
  const richTextRange: RichTextLinkBinding | null =
    richTextLinkVisible && richTextEditingNodeId && richTextRangeSelection
      ? {
          nodeId: richTextEditingNodeId,
          onInteractionChange: onRichTextLinkInteraction,
          onSubmitLink: onRichTextSubmitLink,
          selection: richTextRangeSelection,
        }
      : null;

  // W4.7 (contract item 34): a selected CUSTOM COMPONENT gets the
  // schema-driven props form. Its schema is the pinned artifact's manifest, so
  // the form waits on a read the canvas does not perform: the account comes
  // from the loaded document (only a derived, account-bound doc has one) and
  // the artifact pin from the node itself. Either missing → no fetch, no form.
  const selectedNode = webSelection.selection?.node ?? null;
  const customComponentNode =
    selectedNode?.kind === "custom_component" ? selectedNode : null;
  const customComponentArtifact = useCustomComponentArtifact(
    customComponentNode ? (loadedDocument?.accountId ?? null) : null,
    customComponentNode?.artifact_id ?? null,
  );
  // One prop settles → the whole props object goes back as ONE
  // `set_node_props` op through the SAME manual-edits controller (one
  // in-flight, `base_version`, 409/422 handling) — no second write path. The
  // intent string is the source's own.
  const onCommitCustomComponentProp: CustomComponentPropCommit = useCallback(
    (name, value) => {
      if (!customComponentNode) return;
      const operation = customComponentPropsToOperation(
        loadedDocument,
        customComponentNode,
        name,
        value,
      );
      if (!operation) return;
      applyOps([operation], "set_custom_component_props");
    },
    [applyOps, customComponentNode, loadedDocument],
  );
  // Ledgered ruling (2026-08-18): while the artifact loads, or if its fetch
  // failed, the binding is NULL and the props section is simply absent — the
  // §5 layout fallback stands alone, no loading shell and no error chrome.
  // Item 34's scope is the form.
  const customComponentForm: CustomComponentFormBinding | null =
    customComponentNode && customComponentArtifact.status === "ready"
      ? {
          artifact: customComponentArtifact.artifact,
          busy: writes.busy,
          onCommitProp: onCommitCustomComponentProp,
          props: customComponentNode.props ?? {},
        }
      : null;

  // W4.2 (§1 row 12): the Replace-image pick — upload the file to the asset
  // store, then apply `upsert_asset` (new records only) + `replace_asset` as
  // one batch through the SAME manual-edits controller, so the edit carries
  // `base_version`, reloads on success, and reports failure in the one inline
  // slot the inspector already renders.
  const onReplaceImage = useReplaceImage({
    applyOps: writes.applyOps,
    document: webSelection.document,
    onError: writes.reportError,
    selection: webSelection.selection,
  });

  // F5 task 18: the ACTIVE page — the one the shell's switcher picked, the
  // first page until it picks one, and the first page again whenever a reload
  // drops the picked one. Everything page-scoped in this session reads it —
  // the render the canvas fetches and the layer tree below, which before task
  // 18 was pinned to `pages[0]` — so the switcher, the canvas and the
  // inspector can never disagree about which page is on screen. (Writes need
  // no change: an op takes its `page_id` from the node it targets, via
  // `pageIdForNode`.)
  const documentPages = webSelection.document?.webDoc?.pages;
  const [requestedPageId, setRequestedPageId] = useState<string | null>(null);
  const activePageId = resolveActivePageId(documentPages, requestedPageId);
  const pages: WebSessionPage[] = useMemo(
    () =>
      (documentPages ?? []).map((summary) => ({
        id: summary.id,
        name: summary.name,
        route: summary.route,
      })),
    [documentPages],
  );
  // A selected node belongs to the page it was selected on, so switching pages
  // clears the selection through the ordinary "selection gone" path (the same
  // `onSelect(null)` the canvas sends on a press over nothing) — the canvas's
  // `selectedNodeId` and the inspector empty out together.
  const clearSelection = webSelection.onSelect;
  const setActivePageId = useCallback(
    (pageId: string) => {
      setRequestedPageId(pageId);
      clearSelection(null);
    },
    [clearSelection],
  );

  // Slice 2 (R-A1..R-A3): the canvas's element annotations. Owned HERE because
  // two surfaces need the one list — the canvas (comment box + badges) and the
  // composer's chip bar (task 7) — and because R-A3's "a document switch drops
  // them" is exactly this hook's lifetime.
  const annotations = useWebAnnotations(activeDocumentId, activePageId);
  const annotationsPending = annotations.state.pending;
  const annotationsOpen = annotations.open;
  const annotationsDismiss = annotations.dismiss;
  const annotationsAdd = annotations.add;
  const annotationsEditNote = annotations.editNote;
  const annotationsItemsForPage = annotations.itemsForPage;
  const canvasAnnotations: WebAnnotationsCanvasBinding = useMemo(
    () => ({
      add: annotationsAdd,
      dismiss: annotationsDismiss,
      editNote: annotationsEditNote,
      itemsForPage: annotationsItemsForPage,
      open: annotationsOpen,
      pending: annotationsPending,
      onSend: onSendAnnotation,
    }),
    [
      annotationsAdd,
      annotationsDismiss,
      annotationsEditNote,
      annotationsItemsForPage,
      annotationsOpen,
      annotationsPending,
      onSendAnnotation,
    ],
  );

  // F5 task 19: adding a page makes it the one you are editing. Fired
  // optimistically beside the write, which is safe by construction: if the add
  // is refused the document never gains that id, and `resolveActivePageId`'s
  // own fallback lands back on the first page.
  const addPageWrite = writes.addPage;
  const onAddPage = useCallback(
    (newPage: { id: string; name: string; route: string }) => {
      addPageWrite(newPage);
      setRequestedPageId(newPage.id);
      clearSelection(null);
    },
    [addPageWrite, clearSelection],
  );

  const page =
    documentPages?.find((summary) => summary.id === activePageId) ??
    documentPages?.[0];
  const layerRows =
    page?.root && page.nodes
      ? buildWebLayerRows(
          { nodes: page.nodes, page_root: page.root },
          webSelection.selection?.node.id ?? null,
          webSelection.document?.fragmentMeta,
        )
      : undefined;

  // W4.0: the document's own theme feeds the inspector's color pickers. A
  // document without one (or a failed fetch) yields no options and every
  // picker keeps the dummy's fixture palette.
  const theme = useWebTheme(activeDocumentId);
  const themeColors = useMemo(() => buildThemeColorOptions(theme), [theme]);
  // Founder correction 2026-09-04: with NO node selected the inspector shows
  // the canvas schema, whose Background used to sit on the shared default
  // seed (a sample site's mint) because nothing hydrated it. The page's real
  // background is the theme's `surface-page` token, so that is what the
  // swatch states; a document with no theme hydrates nothing and the neutral
  // default (white — what a themeless page renders) stands.
  const canvasHydrated = useMemo<Partial<InspectorPresentationState> | undefined>(() => {
    const value = theme?.tokens?.["surface-page"];
    if (typeof value !== "string" || value.length === 0) return undefined;
    return { backgroundColor: value, tokenBackgroundColor: tokenLabel("surface-page") };
  }, [theme]);

  // W2.3: layer-row click → postMessage into the iframe → frame echoes
  // `select` → ordinary selection path.
  const onSelectLayer = useCallback((nodeId: string) => {
    canvasControls.current?.selectNode(nodeId);
  }, []);

  // W3.1: what the mount holds — the write adapter (W3.2) resolves events
  // against exactly these three values.
  const addressing = {
    artifactId: activeArtifactId,
    documentVersion: webSelection.document?.currentVersion ?? null,
    selectionId: webSelection.selection?.node.id ?? null,
  };

  // W4.8a: one inline error slot, rich-text first — a failed runtime load or
  // session error is what the user just did, so it outranks a stale write
  // error (source: WebEditorApp.tsx:1297). W4.8b extends the same precedence
  // by one rung: a rejected link href is the most recent thing of all, and it
  // shows only while ITS section is on screen for ITS node — no new UI, per
  // the ledgered failure ruling.
  const inspectorError =
    (richTextLinkVisible && richTextLinkError?.nodeId === richTextEditingNodeId
      ? richTextLinkError.message
      : null) ??
    richTextSession.richTextError ??
    writes.error;

  // F5 task 19: the Page section's binding — present only while NO node is
  // selected (a selected node means the panel is describing that node) and the
  // document actually has pages. Removing the active page needs nothing extra:
  // the reload drops it and `resolveActivePageId` falls back to the first page.
  const activePage = pages.find((candidate) => candidate.id === activePageId) ?? null;
  const pageSection: WebPageSectionBinding | null =
    activePage && webSelection.selection === null
      ? {
          activePage,
          busy: writes.busy,
          errorEngineCode: writes.errorEngineCode,
          onAddPage,
          onRemovePage: writes.removePage,
          onSetPageMeta: writes.setPageMeta,
          pages,
        }
      : null;

  // R-A6 (slice 3): the in-frame clone text editor settled. The canvas renders
  // `activePageId`, so that is the page the commit belongs to — the same one the
  // Clone-text-edits section clears against. A pathless address cannot be an
  // override (the validator already drops one), so it is ignored rather than
  // written to the whole node.
  const setFragmentTextOverride = writes.setFragmentTextOverride;
  const onCloneTextCommit = useCallback(
    (address: WebElementAddress, override: WebFragmentTextOverride) => {
      if (!address.path || !activePageId) return;
      setFragmentTextOverride(
        activePageId,
        address.nodeId,
        address.path,
        override,
      );
    },
    [activePageId, setFragmentTextOverride],
  );

  // R-A6 (slice 3): the selected clone's human text edits. Present whenever the
  // selection resolves to a fragment (itself, or the wrapper section a pin is
  // born in); the list may be empty, and the section decides what to do with
  // that. `page` is the loaded document's own active page, so the write is
  // addressed to the page the canvas is actually on.
  const cloneTextEditsSelection = cloneTextEditsFor(
    page,
    webSelection.selection?.node.id ?? null,
  );
  const cloneTextEdits: WebCloneTextEditsBinding | null =
    page && cloneTextEditsSelection
      ? {
          busy: writes.busy,
          nodeId: cloneTextEditsSelection.nodeId,
          onClear: (path: string) =>
            writes.setFragmentTextOverride(
              page.id,
              cloneTextEditsSelection.nodeId,
              path,
              null,
            ),
          overrides: cloneTextEditsSelection.overrides,
          pageId: page.id,
        }
      : null;

  return {
    activeDocumentId,
    activePageId,
    addressing,
    annotations,
    cloneTextEdits,
    canvasAnnotations,
    canvasControls,
    canvasHydrated,
    customComponentForm,
    inspectorError,
    layerRows,
    onCloneTextCommit,
    onReplaceImage,
    onRichTextCommit,
    onRichTextSessionChange: setRichTextSession,
    onSelectLayer,
    onWriteReload,
    pageSection,
    pages,
    redoDisabled: (webSelection.document?.redoDepth ?? 0) === 0,
    reloadNonce,
    richTextRange,
    richTextSession,
    setActivePageId,
    theme,
    themeColors,
    undoDisabled: (webSelection.document?.undoDepth ?? 0) === 0,
    webSelection,
    writes,
  };
}
