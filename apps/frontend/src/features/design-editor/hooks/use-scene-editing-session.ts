"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { InspectorEventAddressing } from "@/features/chat-shell/hooks/use-inspector-controller";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import {
  kitLibraryEntries,
  type KitLibraryEntry,
} from "../adapter/scene-asset-library";
import {
  hydrateSceneSelectionState,
  rootFrameId,
  sceneSelectionFor,
  type SceneInspectorState,
  type SceneSchemaSelection,
} from "../adapter/scene-hydrate";
import { sceneLayerRows, type SceneLayerRow } from "../adapter/scene-layers";
import { isPagelessScene } from "../adapter/scene-pageless";
import { buildScenePalette, type ScenePalette } from "../adapter/scene-palette";
import { snapshotSceneTurnTargets } from "../adapter/scene-turn-targets";
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
import { buildKitTokenMaps, type KitTokenMaps } from "../engine/scene/tokenColors";
import { useSceneArrange } from "./use-scene-arrange";
import { useSceneAssetLibrary } from "./use-scene-asset-library";
import { useSceneClipboard } from "./use-scene-clipboard";
import { useSceneDelete } from "./use-scene-delete";
import type { SceneDocumentHistory } from "./use-scene-document";
import { useSceneExport } from "./use-scene-export";
import { useSceneImageAi } from "./use-scene-image-ai";
import { useSceneImagePaste } from "./use-scene-image-paste";
import { useSceneInspectorWrites } from "./use-scene-inspector-writes";
import { useSceneReplaceImage } from "./use-scene-replace-image";

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
/** One identity, so a kitless document does not re-derive the asset library on
 * every render (`NO_ROWS`' reason exactly). */
const NO_KIT_ENTRIES: KitLibraryEntry[] = [];

interface LoadedScene {
  forDocumentId: string;
  pageId: PageId | null;
  scene: Scene;
  presentationScene: Scene | null;
}

export function useSceneEditingSession({
  activeArtifactId,
  agentRunLocked = false,
  documentIds,
  enabled = true,
  onScreen = true,
}: {
  /** The caller's OWN shell controller's active artifact tab. */
  activeArtifactId: string | null;
  /**
   * Task 4 (scene live-streaming rung A): a design turn is queued or running on
   * the open document, so this session is VIEW-ONLY — founder ruling, no mid-run
   * manual editing, ever.
   *
   * The decision is the caller's (`chat-shell/model/agent-run-lock`, which is
   * the only place that can see the turn stream AND the open document's thread);
   * this session only transports it into the write controller and hands the
   * canvas a way to report a refusal. Defaults to false, which is what the
   * artifact route — no live turn stream to read — leaves it at.
   */
  agentRunLocked?: boolean;
  /** Artifact id → design-document id, from the page's read-seam fetch. */
  documentIds: Record<string, string> | undefined;
  /**
   * The caller's kind guard. React forbids a conditional hook, so the kind
   * rides in as a parameter: a mount that is showing a WEB artifact passes
   * `false` and this session touches no transport at all. Defaults to `true`
   * so a caller that only ever mounts ads needs nothing extra.
   */
  enabled?: boolean;
  /** The artifact is on screen (the artifact surface, panel open): undo/redo keys act only then
   * (review finding S2b-6). Defaults to true. */
  onScreen?: boolean;
}) {
  const activeDocumentId =
    enabled && activeArtifactId
      ? (documentIds?.[activeArtifactId] ?? null)
      : null;

  // The website lane's W3.2 nonce, unchanged in meaning: a committed write (or
  // a design-agent turn) bumps it and the canvas refetches into the same
  // mounted surface — no keyed remount, no flash.
  const [reloadNonce, setReloadNonce] = useState(0);
  // AD4.R: a reloaded scene reaches the panel by derivation — the fields read
  // live hydrated state — so no remount escort is needed.
  const onWriteReload = useCallback(() => setReloadNonce((nonce) => nonce + 1), []);

  const canvasControls = useRef<SceneCanvasControls | null>(null);

  // The rendered scene, mirrored up by the canvas. Stamped with the document
  // it was captured for and DERIVED against the current id (never reset
  // synchronously in an effect — react-hooks/set-state-in-effect), so a
  // switched artifact never hydrates from the previous one's nodes.
  const [loaded, setLoaded] = useState<LoadedScene | null>(null);
  const onSceneChange = useCallback(
    (scene: Scene | null, pageId: PageId | null, documentId: string, presentationScene: Scene | null = null) => {
      setLoaded(scene ? { forDocumentId: documentId, pageId, scene, presentationScene } : null);
    },
    [],
  );
  const live =
    activeDocumentId && loaded?.forDocumentId === activeDocumentId
      ? loaded
      : null;
  const scene = live?.scene ?? null;
  const pageId = live?.pageId ?? null;
  // genad2 Task 5: the loaded document has NO page at all (`open_design_leg@4`
  // births a scene document with `pages: {}`; the design agent authors the first
  // page in a later turn). Derived from the LIVE scene only — while nothing is
  // loaded this is `false`, because "not answered yet" is a different fact from
  // "the agent has not authored a page" and the panel must not confuse them.
  const pageless = scene !== null && isPagelessScene(scene);

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
  const brandKitId = scene?.meta.brand_kit?.id ?? null;
  const brandKitVersion = scene?.meta.brand_kit?.version ?? null;
  const brandKitRef =
    brandKitId && brandKitVersion !== null
      ? `${brandKitId}@${brandKitVersion}`
      : null;
  const [kitPalette, setKitPalette] = useState<{
    forBrandKitRef: string;
    palette: ScenePalette | null;
    tokenMaps: KitTokenMaps;
  } | null>(null);
  // Scope to the document's pinned kit, and rehydrate when its async fetch
  // settles even if the selected node and authored scene have not changed.
  const tokenMaps = brandKitRef && kitPalette?.forBrandKitRef === brandKitRef
    ? kitPalette.tokenMaps : null;

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
  //
  // AD4.R, the producer side of a load-bearing guarantee: this memo must never
  // yield null for a mounted document mid-reload — `use-scene-document` keeps
  // the old load in place until the new one arrives (a reload-token bump never
  // resets to `loading`), so `scene` stays non-null across the refetch. The
  // live-hydrated inspector depends on it: a transient null would drop every
  // bound field back to the controller's mount-mode defaults for a frame.
  const hydrated = useMemo<SceneInspectorState | null>(
    () =>
      scene
        ? hydrateSceneSelectionState(scene, pageId, primaryNode ?? null, tokenMaps,
            primaryNode ? live?.presentationScene?.nodes[primaryNode.id] ?? null : null)
        : null,
    [pageId, primaryNode, scene, tokenMaps, live?.presentationScene],
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
  //
  // AD4.0 step 3 (§1.6): the SAME kit response also carries the colour
  // palette, so `kitPalette` below is set from the one `fetchBrandKitDetail`
  // the fonts already needed — never a second identical request.
  const [libraryFamilies, setLibraryFamilies] = useState<string[]>([]);
  const [kitFamilies, setKitFamilies] = useState<string[]>([]);
  // Replace-image lane: the kit's own pictures, which the asset library pins
  // first. Read off the SAME kit fetch as the fonts and the palette below — one
  // fetch, now three vocabularies. A document with NO kit attached pins
  // nothing, DERIVED rather than reset in an effect (the palette's discipline
  // below, and `react-hooks/set-state-in-effect` forbids the effect form).
  const [fetchedKitEntries, setFetchedKitEntries] = useState<KitLibraryEntry[]>([]);
  const kitEntries = brandKitId ? fetchedKitEntries : NO_KIT_ENTRIES;
  // STAMPED with the kit it was fetched for and DERIVED against the current
  // one, the discipline the scene, the selection, the zoom and the history all
  // follow here. Without it, opening a second ad would keep offering the
  // previous document's brand tokens until its own fetch landed — and the
  // write path VALIDATES against this list, so a pick in that window would
  // bind a token this document's kit may not define. (The `kitFamilies`
  // sibling is not stamped; a stale font NAME is a weaker failure and is not
  // this step's row, but it is the same shape and is recorded.)
  const palette =
    brandKitRef && kitPalette?.forBrandKitRef === brandKitRef
      ? kitPalette.palette
      : null;
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
  // ONE kit fetch, TWO vocabularies (AD4.0 step 3).
  //
  // THE ROUTE, recorded here because the plan's own reference (`brandHub`)
  // does not exist: `GET /brand-kits/{id}/versions/{version}` →
  // `brand_kit_json`, whose
  // `tokens.font_faces` the fonts read and whose `tokens.colors` §1.6's
  // pickers read. It goes through `designBffConfig()`, i.e. the authenticated
  // `/api/clue/design` BFF — never browser→FastAPI, and never the headerless
  // `design-public` passthrough, because `/brand-kits` requires the workspace
  // header.
  //
  // The scene's exact version rides into the versioned route. A v6 document
  // therefore offers v6 colors and fonts even after the same kit publishes
  // v9; the inspector and canvas cannot disagree about which kit is attached.
  // Failure remains fail-soft: a throw leaves the palette `null`
  //     and every picker on the dummy's own list, exactly as it renders today.
  useEffect(() => {
    if (!brandKitId || brandKitVersion === null || !brandKitRef) return;
    let cancelled = false;
    void fetchBrandKitDetail(
      designBffConfig(),
      brandKitId,
      brandKitVersion,
    )
      .then((detail) => {
        if (cancelled) return;
        setKitFamilies(
          collectKitFontFaceRefs(detail).map((face) => face.family),
        );
        setKitPalette({
          forBrandKitRef: brandKitRef,
          palette: buildScenePalette(detail),
          tokenMaps: buildKitTokenMaps(detail),
        });
        setFetchedKitEntries(kitLibraryEntries(detail));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [brandKitId, brandKitRef, brandKitVersion]);
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
    /**
     * The durable version this load landed on, carried beside the depths
     * because the canvas reports both in the same breath.
     *
     * Scene live-streaming task 10 (late join) is what reads it: a canvas that
     * opens onto a run already in flight has to say WHERE the document it just
     * loaded stands in the run's operation ledger, and the version is the only
     * thing that can be translated into that. Null when the load could not
     * report one.
     */
    version: number | null;
  } | null>(null);
  // The last committed version each document's canvas reported. A ref, not
  // state: it is read only inside the submission snapshot, and it must SURVIVE
  // the canvas unmounting (switching to the gallery surface nulls
  // `canvasControls`, but a selection made in the editor is still submittable
  // from there — without this memory that submit was a silent no-op).
  const lastLoadedVersionsRef = useRef(new Map<string, number>());
  const onHistoryChange = useCallback(
    (
      next: SceneDocumentHistory,
      documentId: string,
      currentVersion: number | null,
    ) => {
      if (currentVersion !== null) {
        lastLoadedVersionsRef.current.set(documentId, currentVersion);
      }
      setHistory({ forDocumentId: documentId, history: next, version: currentVersion });
    },
    [],
  );
  const liveHistory =
    activeDocumentId && history?.forDocumentId === activeDocumentId
      ? history.history
      : null;
  /**
   * Task 10: the load the active document is currently showing — its durable
   * version and the generation that loaded it. Stamped and derived exactly like
   * the history above, so a switched artifact never reports the previous ad's
   * version, and `loadGeneration` is what makes a RELOAD onto the same version a
   * distinct load (rung A reloads the canvas on a checkpoint, and each of those
   * is a fresh join for the stream).
   */
  const loadedDocument =
    activeDocumentId && history?.forDocumentId === activeDocumentId && history.version !== null
      ? { documentId: activeDocumentId, version: history.version, loadGeneration: history.history.loadGeneration }
      : null;

  // AD3.2: the real write path. The controller applies each operation to the
  // live engine through the canvas seam, then persists it on the edit queue;
  // the listener inside it is what turns an inspector event into an operation.
  // AD3.3: it also owns the two history steps, which is why the depths go in.
  // AD4.0: `artifactId` and `pageId` are what §1.1's canvas rows are addressed
  // by — an empty selection has no node id to gate on. `pageId` is the one the
  // canvas rendered and `hydrated` above read, so the write stays the exact
  // inverse of what the panel is showing.
  // AD4.0 step 3: `palette` is what §1.6's token rows validate a picked label
  // against — the panel offers it and the write gate re-checks it, so the two
  // can never disagree about which tokens this document has.
  const writes = useSceneInspectorWrites({
    artifactId: activeArtifactId,
    canvasControls,
    documentId: activeDocumentId,
    loadGeneration: liveHistory?.loadGeneration ?? 0,
    // Task 4: the lock, and the one sentence it says. The copy is imported
    // rather than passed down so there is exactly one string in the codebase.
    lockNote: AGENT_RUN_LOCK_NOTE,
    locked: agentRunLocked,
    onReload: onWriteReload,
    onScreen,
    pageId,
    palette,
    tokenMaps,
    primaryNodeId,
    redoDepth: liveHistory?.redoDepth ?? 0,
    scene,
    undoDepth: liveHistory?.undoDepth ?? 0,
  });

  /** Freeze this click-submit's target ids before waiting for optimistic writes.
   * Selection may change while the queue drains; the accepted turn must not. */
  const snapshotEditTargets = useCallback(async () => {
    if (!activeDocumentId || selectedIds.length === 0) return null;
    // Only nodes the live scene still carries ride the turn: a node an agent
    // turn or manual edit deleted has nothing to focus, and submitting its id
    // would refuse the whole message server-side until the user found and
    // removed a chip labelled with a raw engine id.
    // No scene yet means nothing to validate a target against — same answer
    // the chip bar gives (it renders no chips without a scene).
    const liveSelectedIds = scene
      ? selectedIds.filter((nodeId) => scene.nodes[nodeId])
      : [];
    if (liveSelectedIds.length === 0) return null;
    const controls = canvasControls.current;
    const loadedVersion =
      controls?.documentId === activeDocumentId
        ? controls.documentVersion()
        : (lastLoadedVersionsRef.current.get(activeDocumentId) ?? null);
    const snapshot = await snapshotSceneTurnTargets({
      awaitWritesSettled: writes.awaitWritesSettled,
      documentId: activeDocumentId,
      loadedVersion,
      persistedVersion: writes.persistedVersion,
      selectedIds: liveSelectedIds,
    });
    if (snapshot.documentVersion === null) {
      writes.reportError(
        "The selected edit targets could not be tied to the current design version. Reload the design and try again.",
      );
      return null;
    }
    return snapshot;
  }, [activeDocumentId, scene, selectedIds, writes]);

  // AD4.A step 2 (§1.3 row 1): the Replace-image flow. It takes the LIVE
  // primary node rather than the hydrated state, because §4's lock and the
  // node's own asset are facts about the document, not about the panel — and
  // because the write must still be aimed correctly when the upload lands
  // seconds later. Its failures use the SAME inline error slot every other
  // write on this lane uses (`reportError`), never new failure UI.
  const onReplaceImage = useSceneReplaceImage({
    applyOps: writes.applyOps,
    clearMessages: writes.clearMessages,
    documentId: activeDocumentId,
    node: primaryNode ?? null,
    onError: writes.reportError,
    // Task 4 (I3): the gate, not a boolean — a pick refused because the design
    // agent is working must say THAT, never "the write path is not armed".
    onNote: writes.reportNote,
    writeGate: writes.writeGate,
  });

  // Replace-image lane: the asset-library picker. Same deps as the upload above — a pick IS a
  // replace with the upload step removed (spec §4.2) — plus the kit's own asset ids for pinning.
  const assetLibraryBinding = useSceneAssetLibrary({
    applyOps: writes.applyOps,
    canApply: writes.canApply,
    documentId: activeDocumentId,
    kitEntries,
    node: primaryNode ?? null,
    onError: writes.reportError,
  });
  const assetLibrary = activeDocumentId && scene ? assetLibraryBinding : undefined;

  // AD4.A step 3 (§1.3 row 2): the AI image suite — generate / edit / remove
  // background / candidate review. Same seam as Replace image above and for the
  // same reasons: the LIVE node (§4's lock and the node's own asset are facts
  // about the document, and the write must still be aimed correctly seconds
  // later), the same pre-spend gate, and the same one inline error slot.
  //
  // It also takes the SCENE, which the upload does not: the edit gate reads the
  // source asset's `status` out of the scene's own registry, and the document
  // id is what a staged candidate is stamped with so it can never be accepted
  // into another ad.
  const imageAiBinding = useSceneImageAi({
    applyOps: writes.applyOps,
    clearMessages: writes.clearMessages,
    documentId: activeDocumentId,
    node: primaryNode ?? null,
    onError: writes.reportError,
    onNote: writes.reportNote,
    scene,
    writeGate: writes.writeGate,
  });
  // AD4.A step 3 review: the rows are OFFERED only when there is a real
  // document to write to. Both ad call sites pass this unconditionally and the
  // hook always returns a binding, so without this gate the AI controls render
  // on the pre-load path — including the fixture layer tree's "Image" row,
  // which opens the image schema before any scene exists — as a live-looking
  // Generate button whose every click is refused in silence. That is this
  // lane's signature defect, and the honest answer is not to offer the control.
  const imageAi = activeDocumentId && scene ? imageAiBinding : undefined;

  // AD4.B step 4 (§1.5 Arrange): z-order, align, distribute, group/ungroup and
  // the ⌘G/⇧⌘G pair.
  //
  // It takes the SELECTION SET, not the primary node — it is the one binding on
  // this lane whose actions are about several nodes at once (align needs 2+,
  // distribute 3+, group 2+ same-parent siblings), and the whole live scene,
  // because every eligibility rule is a question about the tree (a node's
  // siblings, its parent's layout mode, its lock).
  //
  // BOTH transports ride in: `applyOps` for the three operation actions, and
  // `applyEdit` for group/ungroup, which the engine models as structured edits
  // and which therefore travel the shipped undo/redo path's own control flow.
  const arrangeBinding = useSceneArrange({
    applyEdit: writes.applyEdit,
    applyOps: writes.applyOps,
    clearMessages: writes.clearMessages,
    documentId: activeDocumentId,
    onNote: writes.reportNote,
    scene,
    selectedIds,
    writeGate: writes.writeGate,
  });
  // OFFERED only when there is a real document to arrange — `imageAi`'s gate
  // above, for its reason exactly: the hook always returns a binding, and
  // without this the fixture layer tree would render fourteen live-looking
  // buttons over no scene at all. (The enablement inside would already be all
  // false, so nothing could be written; this keeps the panel from claiming
  // otherwise, and keeps the absent-binding path the dummy's own.)
  const arrange = activeDocumentId && scene ? arrangeBinding : undefined;

  // Clipboard Task 8: external image ingestion — the two seams Task 7 left for
  // pictures that came from OUTSIDE this document (a ⌘V of files, pasted svg
  // markup) plus the gesture the clipboard never sees at all, a drag-drop onto
  // the canvas. It sits here for the same reason every other handler hook does:
  // components never reach the engine or the transport.
  //
  // R21: where a pasted picture lands is the CANVAS's answer — the live
  // viewport's centre in page space — asked through the same controls ref the
  // write path uses, and only when that ref is serving THIS document (a canvas
  // showing another artifact, or none, must not decide where this one pastes).
  // Null falls back to the page's own centre inside the hook.
  const viewportPageCenter = useCallback(() => {
    const controls = canvasControls.current;
    return controls?.documentId === activeDocumentId
      ? controls.viewportPageCenter()
      : null;
  }, [activeDocumentId]);
  const imagePaste = useSceneImagePaste({
    applyOps: writes.applyOps,
    canApply: writes.canApply,
    pageId,
    reportError: writes.reportError,
    scene,
    selectedNodeId: primaryNodeId,
    viewportPageCenter,
  });

  // Clipboard Task 7: ⌘C / ⌘X / ⌘V / ⌘D over the scene.
  //
  // It sits HERE, beside the arrange binding, for the same reason arrange does
  // (AD4.A: components never reach the engine or the transport, so the session
  // composes the handler hook) — and it returns nothing, because a clipboard
  // has no panel: copy, cut and paste arrive as the browser's OWN semantic
  // events (never a keymap — only inside those events is `clipboardData` live,
  // and only they fire for the Edit menu and the right-click menu), and ⌘D is
  // the single chord it registers.
  //
  // The selection it takes is the PRIMARY one, unresolved: `primaryNodeId`
  // above has already been checked against the live scene, and the hook does
  // its own cross-page check (R11), so passing `selectedIds[0]` raw would only
  // duplicate that. V1 copies ONE subtree — the shipped selection model's shape.
  //
  // `workspaceId` is deliberately omitted: nothing in this session knows one
  // (it takes artifact ids and document ids, no workspace), and the payload's
  // `workspaceHint` is display/debug only — a fabricated value would be worse
  // than the honest null, since asset resolution is the real cross-workspace
  // gate. Task 9 made a plain-text paste the hook's OWN (no seam): it replaces
  // a selected text node's content or mints one at `viewportPageCenter`, the
  // same canvas answer the image paste above takes.
  useSceneClipboard({
    documentId: activeDocumentId,
    onExternalImages: imagePaste.onExternalImages,
    onSvgMarkup: imagePaste.onSvgMarkup,
    pageId,
    scene,
    selectedNodeId: primaryNodeId,
    viewportPageCenter,
    writes,
  });

  // The Delete key (Backspace on a Mac keyboard): the WHOLE selection set, not
  // the primary — several layer-panel-selected elements go in one undo frame.
  const clearSelection = useCallback(() => select(null, false), [select]);
  useSceneDelete({
    applyOps: writes.applyOps,
    clearMessages: writes.clearMessages,
    clearSelection,
    documentId: activeDocumentId,
    onNote: writes.reportNote,
    pageId,
    scene,
    selectedIds,
    writeGate: writes.writeGate,
  });

  // AD4.D step 2 (§1.11): the export menu's request, answered. It sits beside
  // the write hooks rather than inside them because an export is a READ (ruling
  // R-D3): it goes to its own endpoint with `persist_preflight: false`, takes no
  // `applyOps` and no lock, and so shares nothing with the write path but the
  // scene it reads. The fallback title is `null` — the DETAIL's title is the
  // primary source and the image menu always sends one (the tab's own title,
  // as the header renders it).
  const { exportPreview, exportStatus, requestExportPreview } = useSceneExport({
    // R-D19: an export reads the server's PERSISTED copy, so it has to wait for
    // this document's optimistic writes to land or it renders the pre-edit
    // document. Same drain a history step takes, for the same reason — the
    // write controller owns the queue, so it owns the answer.
    awaitWritesSettled: writes.awaitWritesSettled,
    documentId: activeDocumentId,
    pageId,
    scene,
    title: null,
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

  /**
   * Task 4: the canvas refused a gesture or a caret because the lock holds.
   *
   * It lands in the SAME inline note line the D10 quiet reload uses — no new
   * failure UI — which is also why this is not a piece of state of its own: the
   * next real write, reload or selection clears it exactly as it clears every
   * other note on this lane.
   */
  const reportNote = writes.reportNote;
  const onLockedEdit = useCallback(() => {
    reportNote(AGENT_RUN_LOCK_NOTE);
  }, [reportNote]);

  return {
    activeDocumentId,
    addressing,
    /** §1.5: the Arrange section's five actions and their enablement.
     * `undefined` until a document is actually loaded — the same gate `imageAi`
     * takes, which is what keeps the buttons inert on the fixture path. */
    arrange,
    /** The Replace-image lane's asset-library picker — open/close, the filtered
     * items and `pick`. `undefined` until a document is loaded, the same gate
     * `arrange` and `imageAi` take. */
    assetLibrary,
    canvasControls,
    /** AD4.D step 3 (§1.11): the render the export menu's designed preview
     * region shows and the element that hosts it, or `null` when there is
     * nothing true to show — including when the document has moved past the
     * scene the render was made from (ruling R-D13). Stamped and derived like
     * everything else here. */
    exportPreview,
    /** §1.11: what the last export attempt did — the line the export menu's
     * `aria-live` span announces, over the controller's own optimistic
     * "requested" one. `null` until an export has been asked for FOR THIS
     * document — it is stamped and derived like everything else here, so
     * switching artifacts never inherits the previous ad's outcome. Operation
     * feedback only, never a claim about the document. */
    exportStatus,
    fontOptions,
    hydrated,
    /** §1.3 row 2: the inspector's AI image suite — what the four flows are
     * showing and the six callbacks they commit through. `undefined` until a
     * document is actually loaded, which is what keeps the rows off the
     * pre-load and fixture paths. */
    imageAi,
    /** One inline slot, write errors only — the rich-text and link-href rungs
     * the website lane resolves above them have no ad equivalent (an ad has no
     * in-canvas text session and no hrefs), so the controller's error IS the
     * precedence. */
    inspectorError: writes.error,
    layerRows,
    note: writes.note,
    /** Task 10 (scene live-streaming rung B): the durable version the open
     * document is currently loaded at, with the generation that loaded it —
     * what a late join reports to the stream so its cursor starts where the
     * canvas actually stands. `null` until a load has reported a version. */
    loadedDocument,
    /** AD3.3: receives the canvas's loaded undo/redo depths. */
    onHistoryChange,
    /** Task 4: the canvas reporting a gesture or caret it refused because the
     * agent-run lock holds — routed to the lane's one inline note line. */
    onLockedEdit,
    /** §1.3 row 1: the inspector's Replace-image handler — the file the user
     * picked becomes an asset and lands in the selected image node. */
    onReplaceImage,
    onSceneChange,
    /** Clipboard Task 8: image files dragged onto the canvas, with the page
     * point the pointer named — uploaded and inserted centred on it. */
    onSceneDropImageFiles: imagePaste.onDropImageFiles,
    onSelectCanvas,
    onSelectLayer,
    onToggleLayer,
    onWriteReload,
    onZoomChange,
    /** genad2 Task 5: the open document has no page yet. The ad inspector's
     * canvas schema states no size, preset or background for that window (it
     * would otherwise show the un-hydrated fixture seeds — `1200`x`1200` — over
     * a document that measures nothing); the canvas stage says so out loud. */
    pageless,
    /** §1.6: the document's brand-kit colour palette, the way `fontOptions` is
     * exposed beside it — offered by every colour picker in the ad inspector,
     * and the vocabulary the token write rows validate against. `null` while
     * no kit is attached, before its fetch lands, or after one that failed. */
    palette,
    /** `[0]`, resolved against the live scene — what the inspector keys on. */
    primaryNodeId,
    /** AD3.3: the menu's Redo row disables off the DOCUMENT's real redo stack
     * — the depth the load reported, plus every step taken since it. Empty
     * means the step would do nothing, so the row is not offered. */
    redoDisabled: writes.redoDisabled,
    reloadNonce,
    /** AD4.D step 3: the preview region, opened or re-pointed at another
     * `(format, scale)`. Answered from a per-scene cache when it can be, and
     * with a fresh export when it cannot. */
    requestExportPreview,
    /** The live document scene used to resolve selected node ids to chip labels. */
    scene,
    selectedIds,
    selection,
    snapshotEditTargets,
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
