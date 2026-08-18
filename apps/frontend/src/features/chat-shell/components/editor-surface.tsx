"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  useEditorShellController,
  type EditorShellInitialState,
} from "../hooks/use-editor-shell-controller";
import { buildWebLayerRows } from "@/features/design-editor/adapter/layers";
import {
  customComponentPropsToOperation,
  type CustomComponentFormBinding,
  type CustomComponentPropCommit,
} from "@/features/design-editor/adapter/custom-component-form";
import { richTextCommitToOperation } from "@/features/design-editor/adapter/rich-text-commit";
import {
  richTextLinkCommit,
  richTextLinkSectionVisible,
  type RichTextLinkBinding,
  type RichTextLinkTrigger,
} from "@/features/design-editor/adapter/rich-text-link-section";
import { buildThemeColorOptions } from "@/features/design-editor/adapter/theme-options";
import type {
  WebArtifactCanvasControls,
  WebRichTextSessionState,
} from "@/features/design-editor/components/web-artifact-canvas";
import type { RichTextDocument } from "@/features/design-editor/engine/webDocuments";
import { useCustomComponentArtifact } from "@/features/design-editor/hooks/use-custom-component-artifact";
import { useInspectorWrites } from "@/features/design-editor/hooks/use-inspector-writes";
import { useReplaceImage } from "@/features/design-editor/hooks/use-replace-image";
import { useWebArtifactSelection } from "@/features/design-editor/hooks/use-web-artifact-selection";
import { useWebTheme } from "@/features/design-editor/hooks/use-web-theme";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import { ArtifactStage } from "./artifact-stage";
import { WebInspector } from "./web-inspector";
import styles from "./chat-shell.module.css";

// Full-width editor surface at the canonical artifact route
// (/projects/{projectId}/artifacts/{artifactId}); the composition the branch's
// chat-shell-view.tsx provided, re-authored without the chat pane.
//
// The gallery rides along as presentation-only chrome (W0.5 founder amendment,
// 2026-08-17): the Gallery tab and gallery surface render real cards only —
// never fixture data. The leg-derived feed (ratified 2026-08-18) supplies them
// through the `artifacts` prop; with no feed the gallery keeps its honest
// empty state. Closing the last tab falls back to the gallery (founder
// Decision 1). This lifted gallery is the intended replacement for the
// existing /projects/{id}/gallery screen (founder Decision 2 — the route swap
// is a separate follow-up now that real data lands).
//
// Split view is deferred to the chat-flow integration: the ratified route
// shape also mounts this surface beside a chat on
// /projects/{id}/chats/{chatId} via `?surface=web|ad` (+ `?edit=`,
// `?selection=`) — ruling R2, 2026-08-17, superseding the earlier
// `?artifact=` param, which was never built and must not be introduced —
// where the inspector dock replaces the conversation column (composer stays
// docked). Until that lands, this surface
// renders the artifact rail (tabs + header + stage) full-width only, matching
// the dummy's maximized presentation (no inspector at full width). The
// "Close artifact panel" tab action is a no-op here for the same reason —
// there is no chat pane to return to at the canonical artifact URL; its
// wiring is a split-view decision.
//
// The wrapper carries styles.shellPanelOpen: the lifted stylesheet's
// `.shellPanelOpen .artifactWorkspace` rule is what makes the stage visible
// (the stage is born opacity-0 for the dummy's slide-in entry transition).
// Since C-1 restored the chat-chrome CSS, `.shellPanelOpen` also carries the
// split-view grid-template-columns (chat column + artifact column), and the
// CSS module is emitted unlayered so it beats Tailwind's layered
// `grid-cols-1`. The inline gridTemplateColumns pins this full-width surface
// back to a single column — the class stays purely an opacity lever here.

export function EditorSurface({
  artifacts,
  documentIds,
  initial,
}: {
  /** Slice 3 (gallery leg-derived feed): the project's real gallery cards,
   * mapped server-side from the design-artifact list read. Absent → the
   * gallery keeps its honest empty state. */
  artifacts?: ProjectArtifact[];
  /** W2.1: artifact id → design-document id, from the page's W1.3 read-seam
   * fetch. The active artifact's entry mounts the real web render; artifacts
   * without one keep the dummy's empty canvas. */
  documentIds?: Record<string, string>;
  initial?: EditorShellInitialState;
}) {
  const controller = useEditorShellController(initial);
  const activeDocumentId = controller.activeArtifactId
    ? (documentIds?.[controller.activeArtifactId] ?? null)
    : null;
  // W2.2: the canvas bridge's nonce-validated selections joined with the
  // loaded document → {node, nodeInfo} + schema + hydrated inspector state,
  // also surfaced on data attributes below for verification.
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
    selection: webSelection.selection,
  });

  // W4.8a: the in-iframe rich-text session, mirrored up by the canvas. Held
  // here because two surfaces outside the canvas need it — the inline error
  // slot below, and (next task) the inspector's conditional Link-to.
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
  // `disabled` (richTextBusy below) narrows the window; the frame's own
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

  // W2.3 (completing the W2 exit gate): while EDITING a real web document,
  // the inspector docks beside the canvas — the dummy's own editing
  // arrangement (ruling R6: the inspector replaces the conversation column;
  // at this chat-less route that column is simply the dock) using the
  // dummy's split grid template verbatim. Not editing → full-width stage,
  // exactly as W0.4 shipped. Remounted per selected node so W2.2's hydrated
  // values re-apply (the dummy's own schema-swap behavior).
  const inspectorVisible =
    controller.editing &&
    controller.artifactKind === "web" &&
    activeDocumentId !== null;
  const page = webSelection.document?.webDoc?.pages?.[0];
  const layerRows =
    page?.root && page.nodes
      ? buildWebLayerRows(
          { nodes: page.nodes, page_root: page.root },
          webSelection.selection?.node.id ?? null,
        )
      : undefined;
  const inspectorSelection =
    webSelection.selection?.schema.selection ?? controller.inspectorSelection;

  // W4.0: the document's own theme feeds the inspector's color pickers. A
  // document without one (or a failed fetch) yields no options and every
  // picker keeps the dummy's fixture palette.
  const theme = useWebTheme(activeDocumentId);
  const themeColors = useMemo(() => buildThemeColorOptions(theme), [theme]);

  return (
    <main
      className={`${styles.shellPanelOpen} grid h-full min-h-0 w-full grid-cols-1`}
      style={{
        gridTemplateColumns: inspectorVisible
          ? "minmax(400px, 480px) minmax(0, 1fr)" // the dummy's .shellPanelOpen split template
          : "minmax(0, 1fr)",
      }}
      data-artifact-id={controller.activeArtifactId ?? undefined}
      data-artifact-kind={controller.artifactKind ?? "none"}
      data-editing={controller.editing}
      data-project-id={controller.projectId}
      data-selected-node={webSelection.selection?.node.id}
      data-selected-schema={
        webSelection.selection
          ? `${webSelection.selection.schema.selection}${webSelection.selection.schema.layoutOnly ? ":layout-only" : ""}`
          : undefined
      }
      data-surface={controller.surface}
    >
      {inspectorVisible ? (
        <div className={styles.chatBody}>
          <div className={styles.inspectorDock}>
            <WebInspector
              // Keyed on the SELECTED NODE only — never the document version.
              // A per-write version key remounted the whole inspector on
              // every edit (the founder-observed defect); the controller's
              // own state already reflects the user's edit, so re-hydration
              // belongs to selection changes alone. (Known, accepted drift:
              // an engine-snapped value — padding 7→6 — displays as typed
              // until the node is reselected.)
              key={webSelection.selection?.node.id ?? "canvas"}
              customComponentForm={customComponentForm}
              // W4.8a: one inline error slot, rich-text first — a failed
              // runtime load or session error is what the user just did, so it
              // outranks a stale write error (source: WebEditorApp.tsx:1297).
              // W4.8b extends the same precedence by one rung: a rejected
              // link href is the most recent thing of all, and it shows only
              // while ITS section is on screen for ITS node — no new UI, per
              // the ledgered failure ruling.
              error={
                (richTextLinkVisible &&
                richTextLinkError?.nodeId === richTextEditingNodeId
                  ? richTextLinkError.message
                  : null) ??
                richTextSession.richTextError ??
                writes.error
              }
              note={writes.note}
              addressing={{
                // W3.1: what this surface holds — the write adapter (W3.2)
                // resolves events against exactly these three values.
                artifactId: controller.activeArtifactId,
                documentVersion: webSelection.document?.currentVersion ?? null,
                selectionId: webSelection.selection?.node.id ?? null,
              }}
              hydrated={webSelection.selection?.hydrated}
              layers={layerRows}
              onReplaceImage={onReplaceImage}
              onSelectLayer={(nodeId) =>
                canvasControls.current?.selectNode(nodeId)
              }
              onSelectionChange={controller.selectInspectorElement}
              richTextRange={richTextRange}
              selection={inspectorSelection}
              themeColors={themeColors}
            />
          </div>
        </div>
      ) : null}
      <ArtifactStage
        activeArtifactId={controller.activeArtifactId}
        activeDocumentId={activeDocumentId}
        artifacts={artifacts ?? []}
        canvasControlsRef={canvasControls}
        canvasReloadToken={reloadNonce}
        artifactKind={controller.artifactKind}
        artifactMaximized={controller.artifactMaximized}
        artifactTitle={controller.artifactTitle}
        editing={controller.editing}
        onActivateArtifact={controller.activateArtifact}
        onCanvasSelect={webSelection.onSelect}
        onCloseArtifact={controller.closeArtifact}
        onOpenGallery={controller.openGallery}
        onRichTextCommit={onRichTextCommit}
        onRichTextSessionChange={setRichTextSession}
        richTextBusy={writes.busy}
        // W4.8a editing gate: the SAME condition that mounts the editing dock.
        // Outside editing the canvas cancels any session the bridge starts, so
        // a double-click on the read-only render changes nothing.
        richTextEnabled={inspectorVisible}
        richTextTheme={theme}
        onOpenGalleryArtifact={(artifact) =>
          controller.openArtifact({
            id: artifact.id,
            kind: artifact.source.type === "website" ? "web" : "ad",
            title: artifact.title,
          })
        }
        onRenameArtifact={(title) => {
          if (controller.activeArtifactId) {
            controller.setArtifactTitleFor(controller.activeArtifactId, title);
          }
        }}
        onRenameArtifactFor={controller.setArtifactTitleFor}
        onToggleMaximized={controller.toggleArtifactMaximized}
        onTogglePanel={() => undefined}
        onToggleEditing={() => controller.setEditing(!controller.editing)}
        openArtifacts={controller.openArtifacts}
        redoDisabled={(webSelection.document?.redoDepth ?? 0) === 0}
        selectedCanvasNodeId={webSelection.selection?.node.id ?? null}
        surface={controller.surface}
        undoDisabled={(webSelection.document?.undoDepth ?? 0) === 0}
      />
    </main>
  );
}
