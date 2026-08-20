"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { InspectorEventAddressing } from "@/features/chat-shell/hooks/use-inspector-controller";
import {
  hydrateSceneSelectionState,
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
import type { SceneDocumentHistory } from "./use-scene-document";
import { useSceneInspectorWrites } from "./use-scene-inspector-writes";

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
 * AD3.2 wires the writes: `writes` is the real manual-edits controller
 * (`use-scene-manual-edits.ts`) and the inspector's events reach it through
 * `use-scene-inspector-writes.ts`. The write is OPTIMISTIC — the live engine
 * applies it, the canvas repaints and mirrors the new scene back through
 * `onSceneChange`, and only then does the edit queue persist it; the reload
 * nonce is bumped ONLY when the queue reports the server disagrees. The
 * addressing triple's `documentVersion` stays `null` on this lane — the gate
 * that replaces it is documented at its construction site below.
 *
 * AD3.3 adds the history leg: the canvas mirrors the loaded document's real
 * undo/redo stack depths up through `onHistoryChange`, the controller adds the
 * steps taken since that load, and `undoDisabled`/`redoDisabled` below are the
 * result — so the action menu's two rows are offered exactly when the server
 * has something to undo or redo.
 */

export type SceneEditingSession = ReturnType<typeof useSceneEditingSession>;

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
  // AD3.2 review: a reload is REQUESTED here but only ARRIVES one fetch later,
  // and the inspector must re-read its fields from the scene that arrives —
  // never from the optimistic one still on screen when the request went out.
  // See `inspectorGeneration` below.
  const reloadPendingRef = useRef(false);
  const [inspectorGeneration, setInspectorGeneration] = useState(0);
  const onWriteReload = useCallback(() => {
    reloadPendingRef.current = true;
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
      // The authoritative scene a requested reload was waiting for has landed:
      // bump the generation the inspector is keyed on, so its fields re-read
      // the document instead of keeping what the user typed. Only here, and
      // only once per reload — a successful write must NOT remount the panel
      // (that was the founder-observed defect on the web lane).
      if (scene && reloadPendingRef.current) {
        reloadPendingRef.current = false;
        setInspectorGeneration((generation) => generation + 1);
      }
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

  // AD4.0 step 2: the routing moved into the adapter
  // (`hydrateSceneSelectionState`) once the canvas schema gained its SECOND
  // entry state — a selected root frame renders §1.1's page rows, which a node
  // hydration cannot state. The rule, and why the node still wins every shared
  // field, is documented there.
  const hydrated = useMemo<SceneInspectorState | null>(
    () =>
      scene
        ? hydrateSceneSelectionState(scene, pageId, primaryNode ?? null)
        : null,
    [pageId, primaryNode, scene],
  );

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
  // AD2.10 adds a THIRD value, for display only: where the user's own pan/zoom
  // gestures left the viewport. It outranks both of the above in the menu —
  // after a pinch, neither the fit nor the last chosen step is where the canvas
  // actually is — and it reaches the canvas never: the gesture already moved
  // the viewport, so feeding a label back would re-derive and re-centre it.
  const [gesture, setGesture] = useState<{
    forDocumentId: string;
    zoom: string;
  } | null>(null);
  const onZoomChange = useCallback(
    (zoom: string) => {
      if (!activeDocumentId) return;
      // An explicit choice is also the way BACK from a gesture: it re-centres
      // the artboard, and the canvas clears its gesture viewport on the same
      // change, so the two cannot disagree about which one is showing.
      setGesture(null);
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
  const onGestureZoom = useCallback(
    (zoom: string | null) => {
      if (!activeDocumentId) return;
      setGesture(zoom ? { forDocumentId: activeDocumentId, zoom } : null);
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
  const gestureZoom =
    activeDocumentId && gesture?.forDocumentId === activeDocumentId
      ? gesture.zoom
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

  // AD3.3: the document's own history, mirrored up by the canvas on every
  // completed load — the depths the menu's Undo/Redo rows disable off, and the
  // base the controller adds the steps taken since to. Stamped with its
  // document and DERIVED against the current one, exactly like the scene and
  // the selection above: a switched artifact must not disable (or enable) its
  // rows off the previous ad's stacks.
  const [history, setHistory] = useState<{
    forDocumentId: string;
    history: SceneDocumentHistory;
  } | null>(null);
  const onHistoryChange = useCallback(
    (next: SceneDocumentHistory, documentId: string) => {
      setHistory({ forDocumentId: documentId, history: next });
    },
    [],
  );
  const liveHistory =
    activeDocumentId && history?.forDocumentId === activeDocumentId
      ? history.history
      : null;

  // AD3.2: the real write path. The controller applies each operation to the
  // live engine through the canvas seam, then persists it on the edit queue;
  // the listener inside it is what turns an inspector event into an operation.
  // AD3.3: it also owns the two history steps, which is why the depths go in.
  // AD4.0: `artifactId` and `pageId` are what §1.1's canvas rows are addressed
  // by — an empty selection has no node id to gate on. `pageId` is the one the
  // canvas rendered and `hydrated` above read, so the write stays the exact
  // inverse of what the panel is showing.
  const writes = useSceneInspectorWrites({
    artifactId: activeArtifactId,
    canvasControls,
    documentId: activeDocumentId,
    loadGeneration: liveHistory?.loadGeneration ?? 0,
    onReload: onWriteReload,
    pageId,
    primaryNodeId,
    redoDepth: liveHistory?.redoDepth ?? 0,
    scene,
    undoDepth: liveHistory?.undoDepth ?? 0,
  });

  // W3.1's triple, ad-side. `documentVersion` stays NULL here, permanently and
  // deliberately (AD3.2 ruling): the edit queue owns `base_version` internally
  // (`editQueue.ts:110-113,152`), so a copy stamped on an inspector event would
  // only ever be a second, staler source of the same fact, and the scene itself
  // carries no version at all. (AD3.3 correction: this comment used to add that
  // `documentStore.fetchDocument` does not parse `current_version` — it does
  // now, for the history controls. The ruling never rested on that.)
  // The write gate that replaces it asserts something
  // strictly stronger — the event's selection IS this session's primary
  // selection AND the live scene really carries that node — and lives in
  // `use-scene-inspector-writes.ts`, where it is documented in full.
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
    /**
     * AD3.2 review: what the inspector's remount key carries beside the node
     * id. It advances ONLY when a reloaded document has actually arrived (the
     * `onSceneChange` above), which is exactly when the panel's fields must
     * stop showing what the user typed and start showing what the server has.
     *
     * Not the reload NONCE: that advances when the reload is requested, and a
     * remount then re-reads the optimistic scene still on screen — proven in
     * the browser, where a refused edit kept its value beside a note saying the
     * document had reloaded. And not a write token: remounting on every write
     * is the founder-observed defect the web lane's key comment names.
     */
    inspectorGeneration,
    /** One inline slot, write errors only — the rich-text and link-href rungs
     * the website lane resolves above them have no ad equivalent (an ad has no
     * in-canvas text session and no hrefs), so the controller's error IS the
     * precedence. */
    inspectorError: writes.error,
    layerRows,
    note: writes.note,
    /** AD3.3: receives the canvas's loaded undo/redo depths. */
    onHistoryChange,
    onSceneChange,
    onSelectCanvas,
    onSelectLayer,
    onToggleLayer,
    onWriteReload,
    onZoomChange,
    /** `[0]`, resolved against the live scene — what the inspector keys on. */
    primaryNodeId,
    /** AD3.3: the menu's Redo row disables off the DOCUMENT's real redo stack
     * — the depth the load reported, plus every step taken since it. Empty
     * means the step would do nothing, so the row is not offered. */
    redoDisabled: writes.redoDisabled,
    reloadNonce,
    selectedIds,
    selection,
    /** AD3.3: likewise the Undo row. Both stay disabled until a document has
     * actually loaded (depth 0/0), never enabled speculatively. */
    undoDisabled: writes.undoDisabled,
    writes,
    /** The zoom to DISPLAY in the header menu (§1.10) — where a gesture left
     * the viewport when there was one, else the user's choice, else the snapped
     * fit the canvas reported. The `"100%"` fallback covers the frames before
     * the canvas has measured its stage; nothing is drawn in them. */
    zoom: gestureZoom ?? zoomOverride ?? fitZoom ?? "100%",
    /** The zoom to FEED the canvas: null means "fit the artboard EXACTLY" —
     * never the snapped label. */
    zoomOverride,
    /** The canvas's fit-on-open report. */
    onFitZoom,
    /** AD2.10: the canvas's pan/wheel-gesture report (display only). */
    onGestureZoom,
  };
}
