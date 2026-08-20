"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { InspectorEventAddressing } from "@/features/chat-shell/hooks/use-inspector-controller";
import {
  hydrateSceneCanvasState,
  hydrateSceneInspectorState,
  rootFrameId,
  sceneSelectionFor,
  type SceneInspectorState,
  type SceneSchemaSelection,
} from "../adapter/scene-hydrate";
import { sceneLayerRows, type SceneLayerRow } from "../adapter/scene-layers";
import {
  nextSceneSelection,
  sceneExpansion,
  sceneFontOptions,
} from "../adapter/scene-session";
import type { SceneCanvasControls } from "../components/scene-artifact-canvas";
import { designBffConfig } from "../data/design-bff";
import type { NodeId, PageId, Scene } from "../engine/scene/contracts";
import { fetchBrandKitDetail } from "../engine/scene/documentStore";
import { collectKitFontFaceRefs } from "../engine/scene/kitFonts";
import { fetchFontLibrary } from "../engine/scene/libraryFonts";
import type { StructuredEdit } from "../engine/scene/structuredEdits";

/**
 * AD2.7: the ad (scene) editing session — the twin of
 * `use-web-editing-session.ts`, and deliberately the SAME shape, so a reader
 * meets one pattern twice rather than two designs.
 *
 * The discipline it copies verbatim from the website lane:
 *
 *  • **ids-only input.** It takes the caller's active artifact tab and the
 *    page's `artifact id → document id` map. It owns NO shell controller — the
 *    artifact route and the chats route each keep their own, and both mount
 *    this one machine beside them.
 *  • **the addressing triple** (`artifactId` / `documentVersion` /
 *    `selectionId`) stamped onto every inspector event.
 *  • **a reload nonce**, bumped by `onWriteReload`, that quietly refetches the
 *    canvas after a committed write (or an agent turn) with no keyed remount.
 *  • **a canvas-controls ref** so the shell can reach the mounted surface.
 *  • **one error precedence**, resolved here rather than in the view.
 *
 * The one structural difference is where the document comes from. The website
 * lane fetches its own JSON copy beside the iframe render; here the CANVAS
 * already owns the document, the wasm engine and the relaid scene, and the hit
 * test answers against that exact scene — so the session receives it through
 * `onSceneChange` instead of fetching a second copy that could disagree with
 * the one the engine is hit-testing. One fetch, one engine, one scene.
 *
 * Writes are NOT wired: `writes` is inert with `busy: false` (AD3 fills it),
 * and `addressing.documentVersion` is deliberately `null` — the W3.1 null
 * contract means "not addressable", which is exactly what a half-wired write
 * path must be. Nothing here can mutate a document.
 */

/** The write surface AD3 fills in. Shaped after the website lane's
 * `WebManualEdits` so the eventual controller drops straight in; every member
 * here is inert. */
export interface SceneManualEdits {
  /** Persist a structured-edit batch. AD3: today a no-op. */
  applyEdits: (edits: readonly StructuredEdit[], intent?: string) => void;
  busy: boolean;
  clearMessages: () => void;
  /** An inline error (a refused edit, or a transport failure). */
  error: string | null;
  /** A transient informational message (the 409 quiet-reload note). */
  note: string | null;
  redo: () => void;
  /** Set the inline error from an adjacent path that fails before any edit
   * exists. State only — the inspector already renders this slot. */
  reportError: (message: string) => void;
  undo: () => void;
}

export type SceneEditingSession = ReturnType<typeof useSceneEditingSession>;

const NO_EDITS: SceneManualEdits = {
  applyEdits: () => undefined,
  busy: false,
  clearMessages: () => undefined,
  error: null,
  note: null,
  redo: () => undefined,
  reportError: () => undefined,
  undo: () => undefined,
};

const NO_ROWS: SceneLayerRow[] = [];

interface LoadedScene {
  forDocumentId: string;
  pageId: PageId | null;
  scene: Scene;
}

export function useSceneEditingSession({
  activeArtifactId,
  documentIds,
  enabled = true,
}: {
  /** The caller's OWN shell controller's active artifact tab. */
  activeArtifactId: string | null;
  /** Artifact id → design-document id, from the page's read-seam fetch. */
  documentIds: Record<string, string> | undefined;
  /**
   * The caller's kind guard. React forbids a conditional hook, so the kind
   * rides in as a parameter: a mount that is showing a WEB artifact passes
   * `false` and this session touches no transport at all. Defaults to `true`
   * so a caller that only ever mounts ads needs nothing extra.
   */
  enabled?: boolean;
}) {
  const activeDocumentId =
    enabled && activeArtifactId
      ? (documentIds?.[activeArtifactId] ?? null)
      : null;

  // The website lane's W3.2 nonce, unchanged in meaning: a committed write (or
  // a design-agent turn) bumps it and the canvas refetches into the same
  // mounted surface — no keyed remount, no flash.
  const [reloadNonce, setReloadNonce] = useState(0);
  const onWriteReload = useCallback(() => {
    setReloadNonce((nonce) => nonce + 1);
  }, []);

  const canvasControls = useRef<SceneCanvasControls | null>(null);

  // The rendered scene, mirrored up by the canvas. Stamped with the document
  // it was captured for and DERIVED against the current id (never reset
  // synchronously in an effect — react-hooks/set-state-in-effect), so a
  // switched artifact never hydrates from the previous one's nodes.
  const [loaded, setLoaded] = useState<LoadedScene | null>(null);
  const onSceneChange = useCallback(
    (scene: Scene | null, pageId: PageId | null, documentId: string) => {
      setLoaded(scene ? { forDocumentId: documentId, pageId, scene } : null);
    },
    [],
  );
  const live =
    activeDocumentId && loaded?.forDocumentId === activeDocumentId
      ? loaded
      : null;
  const scene = live?.scene ?? null;
  const pageId = live?.pageId ?? null;

  // §1.7/§1.8: the additive selection. `[0]` is the primary — the node whose
  // schema the inspector renders and the row the panel scrolls to. Stamped
  // with its document for the same reason the scene is.
  const [selected, setSelected] = useState<{
    forDocumentId: string;
    ids: string[];
  } | null>(null);
  const selectedIds = useMemo(
    () =>
      activeDocumentId && selected?.forDocumentId === activeDocumentId
        ? selected.ids
        : [],
    [activeDocumentId, selected],
  );
  const select = useCallback(
    (nodeId: string | null, additive: boolean) => {
      if (!activeDocumentId) return;
      setSelected((current) => ({
        forDocumentId: activeDocumentId,
        ids: nextSceneSelection(
          current?.forDocumentId === activeDocumentId ? current.ids : [],
          nodeId,
          additive,
        ),
      }));
    },
    [activeDocumentId],
  );
  // The canvas resolves its own modifier-free press (AD2.5) — one node, or
  // null for a press on nothing.
  const onSelectCanvas = useCallback(
    (nodeId: NodeId | null) => select(nodeId, false),
    [select],
  );
  // A layer row carries the §1.7 shift/⌘ modifier the panel saw.
  const onSelectLayer = useCallback(
    (nodeId: string, additive = false) => select(nodeId, additive),
    [select],
  );

  // The primary must still exist in the scene: the canvas can refetch under a
  // live selection (a reload nonce, an agent turn) and a node the document no
  // longer carries has no schema to show. Deriving it — rather than pruning
  // the selection in an effect — means a transient loading gap cannot silently
  // discard what the user picked.
  const primaryNodeId =
    scene && selectedIds[0] && scene.nodes[selectedIds[0]]
      ? selectedIds[0]
      : null;
  const primaryNode = primaryNodeId ? scene?.nodes[primaryNodeId] : null;

  // Ruling 18: the two hydration sources are separate on purpose. A selected
  // node hydrates through AD2.4's node mapper; the EMPTY selection is the
  // canvas schema, which has no Node at all and hydrates from the page.
  const selection = useMemo<SceneSchemaSelection | null>(() => {
    if (!scene) return null;
    if (!primaryNode) {
      return { selection: "canvas", suppressAutoLayoutSection: false };
    }
    return (
      sceneSelectionFor(primaryNode, pageId ? rootFrameId(scene, pageId) : null) ??
      // §5: a kind with no v1 schema is never selectable (AD2.5 and AD2.6 both
      // refuse it), so this is unreachable through either path — the canvas
      // schema is the honest fallback if it ever is reached.
      { selection: "canvas", suppressAutoLayoutSection: false }
    );
  }, [pageId, primaryNode, scene]);

  const hydrated = useMemo<SceneInspectorState | null>(() => {
    if (!scene) return null;
    if (primaryNode) return hydrateSceneInspectorState(primaryNode, scene);
    return pageId ? hydrateSceneCanvasState(scene, pageId) : null;
  }, [pageId, primaryNode, scene]);

  // AD2.6: `expanded` is an INPUT to the row builder — nobody below owns it.
  // The user's toggles live here and the seed (artboard + the primary's
  // ancestors) is applied over them by the pure rule.
  const [manualExpansion, setManualExpansion] = useState<
    ReadonlyMap<string, boolean>
  >(() => new Map());
  const expanded = useMemo(
    () =>
      scene
        ? sceneExpansion(scene, pageId, primaryNodeId, manualExpansion)
        : new Set<string>(),
    [manualExpansion, pageId, primaryNodeId, scene],
  );
  const onToggleLayer = useCallback(
    (nodeId: string) => {
      const open = expanded.has(nodeId);
      setManualExpansion((current) => new Map(current).set(nodeId, !open));
    },
    [expanded],
  );
  const layerRows = useMemo(
    () => (scene && pageId ? sceneLayerRows(scene, pageId, expanded) : NO_ROWS),
    [expanded, pageId, scene],
  );

  // §1.10 / AD2.8: two zooms, deliberately.
  //
  //  • `fit` is what the CANVAS reported — the exact contain-fit, snapped to
  //    the nearest step the menu actually offers, so the menu can display a
  //    value it can also check. It is a label, not a transform.
  //  • `override` is what the USER chose. Only this reaches the canvas, and it
  //    is applied exactly; while it is null the canvas keeps fitting exactly,
  //    which is why wiring the menu cannot cost the read path ruling 17's
  //    edge-to-edge fill.
  //
  // Both are stamped with the document they belong to and DERIVED against the
  // current one (the same discipline as the selection above), so opening
  // another artifact — or coming back to this one — starts at fit again rather
  // than inheriting the previous artboard's zoom.
  const [override, setOverride] = useState<{
    forDocumentId: string;
    zoom: string;
  } | null>(null);
  const [fit, setFit] = useState<{
    forDocumentId: string;
    zoom: string;
  } | null>(null);
  const onZoomChange = useCallback(
    (zoom: string) => {
      if (!activeDocumentId) return;
      setOverride({ forDocumentId: activeDocumentId, zoom });
    },
    [activeDocumentId],
  );
  const onFitZoom = useCallback(
    (zoom: string) => {
      if (!activeDocumentId) return;
      setFit({ forDocumentId: activeDocumentId, zoom });
    },
    [activeDocumentId],
  );
  const zoomOverride =
    activeDocumentId && override?.forDocumentId === activeDocumentId
      ? override.zoom
      : null;
  const fitZoom =
    activeDocumentId && fit?.forDocumentId === activeDocumentId
      ? fit.zoom
      : null;

  // §2 row 3: the Font-family vocabulary. Both legs are best-effort and both
  // failure paths are already silent by construction — `fetchFontLibrary`
  // resolves to an empty library (and negatively caches it), and a kit fetch
  // that throws leaves the kit half empty — so the merge can only ever narrow
  // to `["Inter"]`, never crash the inspector.
  const brandKitId = scene?.meta.brand_kit?.id ?? null;
  const [libraryFamilies, setLibraryFamilies] = useState<string[]>([]);
  const [kitFamilies, setKitFamilies] = useState<string[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const config = designBffConfig();
    void fetchFontLibrary({
      apiBaseUrl: config.apiBaseUrl,
      fetchImpl: config.fetchImpl,
    })
      .then((library) => {
        if (cancelled) return;
        setLibraryFamilies(library.families.map((family) => family.family));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  useEffect(() => {
    if (!brandKitId) return;
    let cancelled = false;
    void fetchBrandKitDetail(designBffConfig(), brandKitId)
      .then((detail) => {
        if (cancelled) return;
        setKitFamilies(
          collectKitFontFaceRefs(detail).map((face) => face.family),
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [brandKitId]);
  const fontOptions = useMemo(
    () => sceneFontOptions(libraryFamilies, kitFamilies),
    [kitFamilies, libraryFamilies],
  );

  // W3.1's triple, ad-side. `documentVersion` is null until AD3: the scene
  // lane's write path takes its own `base_version` from the edit queue, and a
  // null here is the W3.1 "not addressable" contract — which is precisely what
  // guarantees that no inspector interaction can become a write before AD3
  // deliberately wires one.
  const addressing = useMemo<InspectorEventAddressing>(
    () => ({
      artifactId: activeArtifactId,
      documentVersion: null,
      selectionId: primaryNodeId,
    }),
    [activeArtifactId, primaryNodeId],
  );

  return {
    activeDocumentId,
    addressing,
    canvasControls,
    fontOptions,
    hydrated,
    /** One inline slot, write errors only for now — the rich-text and
     * link-href rungs the website lane resolves above them have no ad
     * equivalent (an ad has no in-canvas text session and no hrefs). */
    inspectorError: NO_EDITS.error,
    layerRows,
    note: NO_EDITS.note,
    onSceneChange,
    onSelectCanvas,
    onSelectLayer,
    onToggleLayer,
    onWriteReload,
    onZoomChange,
    /** `[0]`, resolved against the live scene — what the inspector keys on. */
    primaryNodeId,
    /** Undo/redo depth is not served by the document read, so the menu's
     * entries stay disabled rather than offering a stack we cannot count. */
    redoDisabled: true,
    reloadNonce,
    selectedIds,
    selection,
    undoDisabled: true,
    writes: NO_EDITS,
    /** The zoom to DISPLAY in the header menu (§1.10) — the user's choice when
     * there is one, else the snapped fit the canvas reported. The `"100%"`
     * fallback covers the frames before the canvas has measured its card;
     * nothing is drawn in them. */
    zoom: zoomOverride ?? fitZoom ?? "100%",
    /** The zoom to FEED the canvas: null means "fit the artboard EXACTLY" —
     * never the snapped label. */
    zoomOverride,
    /** The canvas's fit-on-open report. */
    onFitZoom,
  };
}
