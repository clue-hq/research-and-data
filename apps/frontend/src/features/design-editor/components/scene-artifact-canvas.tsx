"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import type { CanvasKit, Surface, TypefaceFontProvider } from "canvaskit-wasm";
import { AlertTriangleIcon } from "lucide-react";
import { sceneEngineBanners } from "../adapter/scene-engine-banners";
import {
  ARTBOARD_BORDER_COLOR,
  ARTBOARD_SHADOW_COLOR,
  SELECTION_HANDLE_CORNER_RADIUS,
  SELECTION_HANDLE_FILL,
  SELECTION_HANDLE_STROKE,
  SELECTION_HANDLE_STROKE_WIDTH,
  SELECTION_OUTLINE_COLOR,
  SELECTION_OUTLINE_WIDTH,
  WORKSPACE_CANVAS_FALLBACK,
  artboardChromeGeometry,
  formatZoomPercent,
  sceneArtboardModel,
  sceneAssetPassthroughUrl,
  sceneDragPanViewport,
  sceneSelectionOutline,
  sceneViewportModel,
  sceneWheelViewport,
  selectionHandleRects,
  type SceneArtboardModel,
  type SceneSelectionOutline,
} from "../adapter/scene-canvas-view";
import {
  representableHit,
  sceneHitPoint,
} from "../adapter/scene-selection";
import {
  drawDescriptorTree,
  parseColor,
} from "../engine/scene/canvaskit/drawDescriptors";
import { CanvasKitImageCache } from "../engine/scene/canvaskit/imageCache";
import {
  loadCanvasKit,
  subscribeTextMeasurementStatus,
  textMeasurementStatusSnapshot,
} from "../engine/scene/canvaskit/loadCanvasKit";
import type { NodeId, Operation, PageId, Scene } from "../engine/scene/contracts";
import type { EngineApplyOutcome, HitResult } from "../engine/scene/wasmEngine";
import {
  defaultWorkspaceViewport,
  screenToWorkspace,
  type WorkspaceViewport,
} from "../engine/scene/workspaceViewport";
import {
  useSceneDocument,
  type SceneDocumentHistory,
  type SceneEngineStatus,
} from "../hooks/use-scene-document";
import styles from "./scene-artifact-canvas.module.css";

/**
 * AD2.3: a real ad, drawn by the real engine, inside the dummy's designed
 * artboard card.
 *
 * Derived from the design subsystem's `CanvasKitStage`
 * (`subsystems/clue-design/apps/editor/src/components/canvas/CanvasKitStage.tsx`),
 * with its mechanics ported rather than reinvented: one WebGL surface per
 * canvas element (falling back to the software surface), a dirty flag drained
 * by a single rAF (no frame runs while clean), the resize coalesced INTO that
 * same frame (resetting the bitmap blanks it, so wipe and redraw must land
 * together), and a re-armed `matchMedia` resolution watcher because
 * `devicePixelRatio` can change with no size change at all.
 *
 * AD2.10 (founder ruling, 2026-08-20) makes the port faithful where AD2.3
 * departed from it: **the stage is an infinite workspace and the artboard is a
 * page floating on it, bounded by its own edges alone** — Figma's model,
 * "nothing more and nothing less". The `<canvas>` is the whole neutral output
 * area, not the dummy's `.imageCanvas` card; the workspace clears to
 * `--bg-canvas`; the artboard carries a shadow and a hairline; and the viewport
 * pans and wheel-zooms. This RETIRES ruling 17 (fit margin 0, "the card IS the
 * artboard"), which made exactly one zoom level look right and left every other
 * one either padded (below fit) or silently clipped with no way to reach the
 * rest (above fit).
 *
 * Two deliberate departures from the source stage remain:
 *
 * - **One artboard.** The platform mounts a single document, so the workspace's
 *   artboard grid, its active/inactive border and its name labels are gone.
 *   (§1.1's artifact-name label and W×H chip are ratified in the contract but
 *   the AD0.1 dummy delta carries no CSS for them — inventing that styling is
 *   barred, so they wait for Gate G-A's mockup sheet. Nothing here fakes them.)
 * - **Content only.** Selection chrome stays out of the canvas by the source's
 *   own Decision 5 — the selection overlay mounts as a sibling of the
 *   `<canvas>` inside `.stage`, so hover/selection never trigger a wasm redraw.
 *
 * And one re-valuing: the source's `drawArtboard` shell is an opaque `#151920`
 * slab, legible behind a page on its DARK workspace and a hard black frame on
 * our light one. The structure is ported (a shell behind the rect, content
 * clipped to the page box, a border stroked on top); the shell is painted as a
 * real blurred drop shadow and the border keeps the hairline colour the retired
 * card drew. Both are screen-constant (`artboardChromeGeometry`).
 *
 * AD2.5 adds the read path's last leg: pointer-down selects. Gate G-A then
 * ratified the visual (founder, 2026-08-20 — Variant B), so the overlay AD2.5
 * left as a marked empty insertion point is now a real sibling `<svg>`: a
 * 1.5px indigo outline around the selected node's box, fed by
 * `deriveSelectionChromeModel`'s `selectionBox` through `sceneSelectionOutline`.
 * It is a SIBLING of the canvas, never a canvas draw — the source stage's own
 * Decision 5 — so selection can never trigger a wasm redraw, and it is
 * `pointer-events: none`, so every click still reaches the canvas beneath it.
 *
 * The ruling's four corner handles are **approved and deliberately not drawn**:
 * a handle is a promise of drag-and-resize, and that behaviour is AD4's Lane C
 * (there are no writes at all until AD3). A grabbable handle that does nothing
 * is a fake affordance. The geometry and colors are encoded in the adapter and
 * the renderer below is defaulted off — Lane C passes `handles` and changes
 * nothing else. `data-scene-selected-node` stays on the canvas as the
 * machine-readable assertion (AD2.5 finding 4, founder-confirmed).
 *
 * AD3.2 adds the ONE seam the write path needs: `applyOperations` on the
 * controls below, which hands a batch to the live engine and repaints. The
 * canvas still owns no write POLICY — what to write, when to persist it and
 * what a rejection says all live in `hooks/use-scene-manual-edits.ts`.
 *
 * When the wasm stamp handshake fails the scene still renders — from the
 * server's own snapshot — no operation can be applied at all, and
 * `engineDisabled` rides upward. A click in that state is a **no-op**: with no
 * engine there is no hit test, and a guess from descriptors would be a
 * selection the engine never agreed to. Gate G-D (founder, 2026-08-21) closed
 * the last silence around it: `SceneEngineBanners` below now SAYS so, in the
 * MVP editor's own words, instead of leaving the console diagnostic as the only
 * signal that a click did nothing on purpose.
 */

export interface SceneCanvasControls {
  /**
   * AD3.2: apply operations to the LIVE engine and repaint — the optimistic
   * half of the write path, which must land before anything is persisted (the
   * queue reconciles the server's document against the local scene at drain,
   * so persisting first would report divergence on every accepted edit).
   *
   * Null when the engine is unavailable (D9 read-only) — the caller must never
   * persist what the engine never applied. A rejected outcome is returned
   * rather than thrown: the caller shows the engine's own message.
   */
  applyOperations(operations: Operation[]): EngineApplyOutcome | null;
  /**
   * AD4.A step 2: could a batch land right now — i.e. is the live engine
   * available? False is exactly the state in which `applyOperations` returns
   * `null` (D9 read-only).
   *
   * It exists because that refusal is DELIBERATELY SILENT (the canvas's own
   * G-D banner explains the read-only state and a second message would be new
   * failure UI), which is fine for a write that costs nothing to attempt and
   * wrong for one that SPENDS something first: the Replace-image flow uploads
   * the picked file — minting a real asset registry row — before it has any
   * operation to apply. Asking here lets that flow refuse before the spend
   * instead of stranding an orphan asset behind a silent no-op.
   */
  canApply(): boolean;
  /** Point→node hit-test in absolute PAGE space (scene units), straight from
   * the engine. Null when the engine is unavailable — a disabled engine
   * refuses to answer rather than guessing from descriptors (AD2.5 consumes
   * the stack; the coordinate chain into these units is its step 2). */
  hitTest(x: number, y: number): HitResult | null;
  /** Adopt the engine's current scene and repaint. */
  refresh(): void;
  /** The scene as rendered right now (the relaid engine scene when the engine
   * is live, the server snapshot otherwise), or null before it loads. */
  sceneSnapshot(): Scene | null;
}

export interface SceneArtifactCanvasProps {
  /** The design document to render. */
  documentId: string;
  /** Receives the canvas's imperative controls while mounted. */
  controlsRef?: RefObject<SceneCanvasControls | null>;
  /** Bump to refetch the document into the same mounted canvas (the website
   * lane's quiet-swap discipline: no keyed remount, no flash). */
  reloadToken?: number;
  /**
   * A menu-chosen zoom (`"45%"`), applied EXACTLY as chosen.
   *
   * Null/absent is the fit mode (the AD2.3 read path and every freshly-opened
   * artifact): the artboard is contain-fit to the card at its exact scale, not
   * at the nearest menu step, so ruling 17's edge-to-edge fill survives the
   * menu being wired. See `sceneViewportModel` for why the displayed label and
   * the applied scale differ in that mode.
   */
  zoom?: string | null;
  /** The fit-on-open zoom as one of the header menu's own 5% steps — what the
   * menu DISPLAYS while nothing has been chosen. */
  onFitZoom?: (zoom: string) => void;
  /**
   * AD2.10: the zoom a PAN/WHEEL gesture landed on, or null when the canvas
   * falls back to the derived viewport (a fresh document, or an explicit menu
   * choice).
   *
   * A separate channel from `onFitZoom` and from the menu's own choice because
   * it outranks both for DISPLAY only: after a pinch the header must say where
   * the viewport actually is, and where it actually is may be a percentage the
   * 29-step menu does not offer (`formatZoomPercent`, not `snapZoomPercent`).
   * It never feeds back into `zoom` — the gesture already moved the viewport,
   * and re-deriving from a label would re-centre it and undo the pan.
   */
  onGestureZoom?: (zoom: string | null) => void;
  /** Mirrors the wasm stamp handshake upward, so the shell can refuse edits.
   * (The user-facing explanation is the canvas's own G-D banner, which needs no
   * shell plumbing — this stays the shell's machine-readable copy.) */
  onEngineStatusChange?: (status: SceneEngineStatus) => void;
  /**
   * AD3.3: the loaded document's undo/redo stack depths, mirrored up with the
   * generation counter that says when they were last refreshed.
   *
   * A separate channel from `onSceneChange` because it is DOCUMENT metadata,
   * not scene content — the same reason the engine status and the fit zoom have
   * their own. It is what lets the shell disable a history control it cannot
   * honour, without the session fetching a second copy of the document (this
   * lane's "one fetch, one engine, one scene" rule). Fires on every completed
   * load, including a reload-token refetch.
   */
  onHistoryChange?: (
    history: SceneDocumentHistory,
    documentId: string,
  ) => void;
  /**
   * AD2.7: the RENDERED scene, mirrored up whenever it changes (load, reload
   * token, the measure-then-inject relayout), tagged with the document it
   * belongs to.
   *
   * This is what lets the shared editing session hydrate the inspector and
   * build the layer tree without fetching a second copy of the document: the
   * scene handed up here is the very one `hitTest` answers against, so a
   * selection, its schema and its values can never come from three different
   * snapshots. Fires with `null` while the document is loading or after a
   * failed load.
   */
  onSceneChange?: (
    scene: Scene | null,
    pageId: PageId | null,
    documentId: string,
  ) => void;
  /**
   * AD2.7: the session's primary selection, once the shell owns it. Absent
   * (`undefined`) leaves the canvas on its own AD2.5 selection state, which is
   * what the standalone read path uses.
   */
  selectedNodeId?: NodeId | null;
  /** Fires on pointer-down with the node the press selected, or null when the
   * press cleared the selection (a click off the artboard, or a hit stack with
   * nothing representable in it). Never fires when the engine is unavailable —
   * a disabled engine refuses to answer rather than guessing.
   *
   * AD2.7 lifts the selection out into the editing session (which feeds it
   * back through `selectedNodeId`), so the inspector, the layer tree and the
   * canvas all read one selection. */
  onSelect?: (nodeId: NodeId | null) => void;
}

export function SceneArtifactCanvas(props: SceneArtifactCanvasProps) {
  // Keyed remount per DOCUMENT only: switching artifacts starts from
  // born-loading (never a stale ad under a new title) without a synchronous
  // setState inside an effect. Reload tokens deliberately do NOT remount — the
  // refetch swaps into the same live surface.
  return <SceneDocumentCanvas key={props.documentId} {...props} />;
}

function SceneDocumentCanvas({
  controlsRef,
  documentId,
  onEngineStatusChange,
  onFitZoom,
  onGestureZoom,
  onHistoryChange,
  onSceneChange,
  onSelect,
  reloadToken = 0,
  selectedNodeId,
  zoom = null,
}: SceneArtifactCanvasProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [ownSelectedNodeId, setOwnSelectedNodeId] = useState<NodeId | null>(
    null,
  );
  const {
    engine,
    engineStatus,
    loadGeneration,
    pageId,
    redoDepth,
    refresh,
    scene,
    tokenGeneration,
    undoDepth,
  } = useSceneDocument(documentId, reloadToken);

  // The engine's own text-measurement status store — `heuristic` means the
  // Skia pass never ran, which is a real rendering difference the G-D banner
  // names (it was silent until then: the ad renders either way).
  const measurementStatus = useSyncExternalStore(
    subscribeTextMeasurementStatus,
    textMeasurementStatusSnapshot,
    textMeasurementStatusSnapshot,
  );

  // The descriptor tree the draw loop walks. `tokenGeneration` is a real dep:
  // descriptors read the renderAdapter's module-level kit maps, which arrive
  // after the first paint.
  const artboard = useMemo(
    () => (scene ? sceneArtboardModel(scene, pageId) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tokenGeneration
    [scene, pageId, tokenGeneration],
  );

  // Fit-on-open (§1.10) is a pure function of the card's size and the page
  // box, so it is derived, never stored: no viewport state can go stale
  // against a resize. AD2.8's menu value rides in the SAME derivation — the
  // fit-vs-chosen rule lives in `sceneViewportModel`, where it is unit-tested
  // (this component's internals cannot be: no DOM, no wasm in the runner).
  const viewportModel = useMemo(
    () =>
      artboard
        ? sceneViewportModel({ rect: artboard.rect, stage: stageSize, zoom })
        : null,
    [artboard, stageSize, zoom],
  );

  // AD2.10: the one piece of viewport STATE — where the user's own pan/zoom
  // gestures have taken the workspace. Null means "nowhere yet", and the
  // derivation above governs; a gesture supersedes it until the next explicit
  // choice.
  //
  // The reset is keyed on the page and the chosen zoom, deliberately NOT on the
  // artboard or the stage size: a relayout (a text measurement landing, a write
  // in AD3) or a panel toggle must not yank the workspace back to centre under
  // someone who has panned. A menu choice must — that is what "re-centre on an
  // explicit choice" means.
  // The reset is React's own adjust-state-on-prop-change pattern (a render-time
  // comparison against the last key), not an effect: an effect would paint one
  // frame of the stale gesture viewport before snapping back.
  const [gestureViewport, setGestureViewport] =
    useState<WorkspaceViewport | null>(null);
  const viewportKey = `${pageId ?? ""}|${zoom ?? ""}`;
  const [lastViewportKey, setLastViewportKey] = useState(viewportKey);
  if (lastViewportKey !== viewportKey) {
    setLastViewportKey(viewportKey);
    setGestureViewport(null);
  }
  const activeGestureViewport =
    lastViewportKey === viewportKey ? gestureViewport : null;

  const viewport: WorkspaceViewport =
    activeGestureViewport ??
    viewportModel?.applied ??
    defaultWorkspaceViewport();

  // The header's zoom control, told where the viewport actually is after a
  // gesture. Keyed on the LABEL, so a pure pan (same zoom) never re-renders the
  // shell — a drag would otherwise push one state update per pointer move
  // through the whole editing session.
  const gestureZoomLabel = activeGestureViewport
    ? formatZoomPercent(activeGestureViewport.zoom)
    : null;
  const onGestureZoomRef = useRef(onGestureZoom);
  useEffect(() => {
    onGestureZoomRef.current = onGestureZoom;
  });
  useEffect(() => {
    onGestureZoomRef.current?.(gestureZoomLabel);
  }, [gestureZoomLabel]);

  // Report the fit as a step the header menu actually offers — the FIT, always,
  // never the chosen zoom: this is the value the menu falls back to, so a
  // choice must not overwrite it. Passive effect (callback only, no state) so
  // it can never fight the derivation above.
  const onFitZoomRef = useRef(onFitZoom);
  useEffect(() => {
    onFitZoomRef.current = onFitZoom;
  });
  const fitZoom = viewportModel?.fitLabel ?? null;
  useEffect(() => {
    if (fitZoom) {
      onFitZoomRef.current?.(fitZoom);
    }
  }, [fitZoom]);

  const onEngineStatusRef = useRef(onEngineStatusChange);
  useEffect(() => {
    onEngineStatusRef.current = onEngineStatusChange;
  });
  useEffect(() => {
    onEngineStatusRef.current?.(engineStatus);
  }, [engineStatus]);

  // AD3.3: the loaded history, mirrored up the same way — a passive-ref effect
  // (callback only, no state) keyed on the three SCALARS, never on a freshly
  // built object, which would re-fire on every render.
  const onHistoryChangeRef = useRef(onHistoryChange);
  useEffect(() => {
    onHistoryChangeRef.current = onHistoryChange;
  });
  useEffect(() => {
    onHistoryChangeRef.current?.(
      { loadGeneration, redoDepth, undoDepth },
      documentId,
    );
  }, [documentId, loadGeneration, redoDepth, undoDepth]);

  useEffect(() => {
    const element = stageRef.current;
    if (!element || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      setStageSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // AD2.7: hand the rendered scene up. A passive-ref effect (callback only, no
  // state) so it can never fight the render, and keyed on the scene identity
  // the draw loop is actually using — including the relaid one the C4
  // measurement pass adopts.
  const onSceneChangeRef = useRef(onSceneChange);
  useEffect(() => {
    onSceneChangeRef.current = onSceneChange;
  });

  // One controls object, used BOTH by the pointer handler below and by the
  // shell through `controlsRef` — so the press path calls the same declared
  // seam an outside caller would, and a change to hit-testing cannot leave the
  // two disagreeing.
  const controls = useMemo<SceneCanvasControls>(
    () => ({
      applyOperations: (operations) => {
        if (!engine) {
          return null;
        }
        const outcome = engine.applyOperations(operations);
        // `refresh()` is BOTH halves of "the canvas owns it": it adopts the
        // engine's post-apply scene as the rendered one (repaint) and, through
        // the effect below, mirrors that same scene up to the session — which
        // rehydrates the inspector and rebuilds the layer tree. A rejected
        // batch changed nothing, so it repaints nothing.
        if (outcome.accepted) {
          refresh();
          // AD4.R: the accepted scene ALSO mirrors up synchronously, so a
          // commit handler's own setState and the session's scene adoption land
          // in one React batch — the inspector's live-derived fields re-read
          // the post-write document on the very next render, with no frame in
          // between showing the pre-write value. The passive effect below still
          // fires afterwards with the final rendered (possibly relaid) scene;
          // that second setLoaded is idempotent. This is the MVP editor's own
          // shape: EditorApp installs result.scene in the accept path.
          onSceneChangeRef.current?.(outcome.scene, pageId, documentId);
        }
        return outcome;
      },
      // The same condition `applyOperations` refuses on, asked without
      // applying anything.
      canApply: () => Boolean(engine),
      hitTest: (x, y) =>
        engine && pageId ? engine.hitTest(pageId, x, y) : null,
      refresh,
      sceneSnapshot: () => scene,
    }),
    [documentId, engine, pageId, refresh, scene],
  );
  useEffect(() => {
    if (!controlsRef) {
      return;
    }
    controlsRef.current = controls;
    return () => {
      controlsRef.current = null;
    };
  }, [controls, controlsRef]);

  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  });

  // AD2.7: the shell's selection wins when it owns one; the local state is the
  // standalone read path's fallback (and keeps the diagnostic attribute honest
  // for a canvas mounted with no session).
  const activeSelectedNodeId =
    selectedNodeId === undefined ? ownSelectedNodeId : selectedNodeId;

  // Gate G-A: the selection outline, DERIVED per render from the same artboard
  // and the same viewport the draw loop transforms by — never stored, so a zoom
  // change or a stage resize can never leave a stale box behind. The conversion
  // itself lives in the adapter, where it is unit-tested (this component's
  // internals cannot be: no DOM, no wasm in the runner).
  const selectionOutline = useMemo(
    () =>
      artboard
        ? sceneSelectionOutline({
            artboard,
            pageId,
            scene,
            selectedNodeId: activeSelectedNodeId,
            viewport,
          })
        : null,
    [activeSelectedNodeId, artboard, pageId, scene, viewport],
  );

  const commitSelection = (nodeId: NodeId | null) => {
    setOwnSelectedNodeId(nodeId);
    onSelectRef.current?.(nodeId);
  };

  /* ---------------------------------------------------------------------
   * AD2.10 — the workspace gestures.
   *
   * Ported from the source canvas's own handlers (`CanvasKitCanvas.tsx`
   * :968-1010): ⌘/Ctrl + wheel zooms at the pointer, a plain wheel pans (what a
   * trackpad's two-finger scroll emits), and a held modifier turns a drag into a
   * pan. The decisions themselves live in the adapter, where they are
   * unit-tested; what is here is only the DOM plumbing.
   * ------------------------------------------------------------------ */

  // The gesture handlers are bound once and read their inputs through a ref, so
  // no listener is re-attached mid-drag. What the ref carries is the DERIVED
  // viewport (the fit or the chosen step) — the base a gesture starts from; the
  // gesture's own position is read from the state updater instead, because two
  // wheel events inside one frame would both see the same not-yet-committed ref
  // and the second would discard the first.
  const gestureInputsRef = useRef({
    artboard,
    stageSize,
    baseViewport: viewportModel?.applied ?? viewport,
  });
  useEffect(() => {
    gestureInputsRef.current = {
      artboard,
      stageSize,
      baseViewport: viewportModel?.applied ?? viewport,
    };
  });

  useEffect(() => {
    const element = stageRef.current;
    if (!element) {
      return;
    }
    const handleWheel = (event: WheelEvent) => {
      const current = gestureInputsRef.current;
      if (!current.artboard) {
        return;
      }
      // A NATIVE, non-passive listener rather than React's `onWheel`: React
      // registers wheel at the root as PASSIVE, so `preventDefault` there is a
      // no-op — ⌘+wheel would zoom the browser page over the top of the canvas
      // and a two-finger scroll would scroll the shell instead of panning. The
      // stage is a viewport, so it owns the gesture.
      event.preventDefault();
      const bounds = element.getBoundingClientRect();
      // deltaMode 1 is LINES (Firefox with a mouse wheel): ~16px per line, or a
      // notch would move the workspace by three pixels.
      const lines = event.deltaMode === 1 ? 16 : 1;
      const artboardRect = current.artboard.rect;
      const delta = { x: event.deltaX * lines, y: event.deltaY * lines };
      const point = {
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      };
      const zoomGesture = event.ctrlKey || event.metaKey;
      setGestureViewport((live) =>
        sceneWheelViewport({
          bounds: artboardRect,
          delta,
          point,
          stage: current.stageSize,
          viewport: live ?? current.baseViewport,
          zoomGesture,
        }),
      );
    };
    element.addEventListener("wheel", handleWheel, { passive: false });
    return () => element.removeEventListener("wheel", handleWheel);
  }, []);

  // Space-to-pan, the editor convention. Held space turns the whole stage into
  // a hand tool; a plain press still selects (AD2.5), which is why this is a
  // modifier and not a mode.
  const [spaceHeld, setSpaceHeld] = useState(false);
  useEffect(() => {
    const typingTarget = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) {
        return false;
      }
      return (
        target.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      );
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || typingTarget(event.target)) {
        return;
      }
      // Space would otherwise page-scroll the shell behind the stage.
      event.preventDefault();
      setSpaceHeld(true);
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === "Space") {
        setSpaceHeld(false);
      }
    };
    // A window that loses focus mid-hold never delivers the keyup.
    const onBlur = () => setSpaceHeld(false);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  const panDragRef = useRef<{
    pointerId: number;
    origin: { point: { x: number; y: number }; pan: { x: number; y: number } };
  } | null>(null);
  const [panning, setPanning] = useState(false);

  const stagePoint = (event: ReactPointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = panDragRef.current;
    const current = gestureInputsRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !current.artboard) {
      return;
    }
    const artboardRect = current.artboard.rect;
    const point = stagePoint(event);
    setGestureViewport((live) =>
      sceneDragPanViewport({
        bounds: artboardRect,
        origin: drag.origin,
        point,
        stage: current.stageSize,
        viewport: live ?? current.baseViewport,
      }),
    );
  };

  const endPanDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (panDragRef.current?.pointerId !== event.pointerId) {
      return;
    }
    panDragRef.current = null;
    setPanning(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  useEffect(() => {
    onSceneChangeRef.current?.(scene, pageId, documentId);
  }, [documentId, pageId, scene]);

  /**
   * Press-selects, the gesture machine's own semantics (the source editor
   * resolves its press target on pointer-down, not on click).
   *
   * The coordinate chain is `CanvasKitCanvas.tsx:589-617` collapsed to one
   * artboard, and every step matters:
   *
   *   pointer screen offset within the stage
   *     → `screenToWorkspace(point, viewport)`      undo pan + zoom
   *     → minus the artboard's workspace origin     artboard-local descriptor px
   *     → `descriptorToScene(local, unitScale)`     the engine's own units
   *     → `controls.hitTest(x, y)`                  bottom-to-top hit stack
   *     → `representableHit(stack, scene, pageId)`  §5's nearest schema-bearing node
   *
   * The last two conversions are the trap: `hitTest` takes SCENE units, not
   * descriptor px, and the two are identical on a `pt`/`px` page (this ad), so
   * a missing division is invisible here and wrong everywhere else. Both live
   * in `sceneHitPoint`, where they are unit-tested against a non-identity unit.
   */
  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    // AD2.10: a held space or the middle button starts a PAN; a plain primary
    // press still selects. Panning and selecting share the surface, so the
    // discriminator is checked before anything else — and the pan needs no
    // engine, so it works on a disabled-engine canvas too.
    if (
      gestureInputsRef.current.artboard &&
      (spaceHeld || event.button === 1)
    ) {
      panDragRef.current = {
        pointerId: event.pointerId,
        origin: { point: stagePoint(event), pan: viewport.pan },
      };
      setPanning(true);
      event.currentTarget.setPointerCapture?.(event.pointerId);
      event.preventDefault();
      return;
    }
    // Secondary/middle buttons are not a selection gesture.
    if (event.button !== 0) {
      return;
    }
    const element = stageRef.current;
    // No engine → no hit test → NO selection change. A descriptor-space guess
    // would be a selection the engine never agreed to, and the write path that
    // follows in AD2.7 would act on it.
    if (!element || !artboard || !scene || engineStatus.engineDisabled) {
      return;
    }
    const bounds = element.getBoundingClientRect();
    const workspacePoint = screenToWorkspace(
      { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
      viewport,
    );
    const scenePoint = sceneHitPoint(workspacePoint, artboard);
    if (!scenePoint) {
      // Off the artboard entirely: clear, deliberately (not a no-op — the user
      // pressed somewhere with nothing in it).
      commitSelection(null);
      return;
    }
    const result = controls.hitTest(scenePoint.x, scenePoint.y);
    if (!result) {
      return;
    }
    // `HitResult.stack` is bottom-to-top and its last member IS `hit` (the
    // engine's `hit_test` is literally `hit_stack(..).pop()`), so the stack
    // alone is the complete answer.
    commitSelection(representableHit(result.stack, scene, pageId));
  };

  return (
    <div
      className={[
        styles.stage,
        panning ? styles.panning : "",
        !panning && spaceHeld ? styles.pannable : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onPointerCancel={endPanDrag}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endPanDrag}
      ref={stageRef}
    >
      <ArtboardSurface
        artboard={artboard}
        assets={scene?.assets}
        // Test/diagnostic hooks, not chrome: the honest engine + text
        // measurement state and the current selection, readable independently
        // of the approved visuals that now render them (Gates G-A / G-D).
        dataEngine={engineStatus.engineDisabled ? "disabled" : "wasm"}
        dataMeasurement={measurementStatus}
        dataSelectedNode={activeSelectedNodeId ?? "none"}
        viewport={viewport}
      />
      {/* The selection overlay: an absolutely-positioned sibling of the canvas
          (never a canvas draw), so selection never triggers a wasm redraw. */}
      <SelectionChrome outline={selectionOutline} />
      {/* Gate G-D: the two engine-forced states, said out loud. */}
      <SceneEngineBanners
        engineStatus={engineStatus}
        measurementStatus={measurementStatus}
      />
    </div>
  );
}

/**
 * Gate G-D (founder, 2026-08-21): the engine-forced failure banners.
 *
 * Both states were live and SILENT before this — a stamp mismatch made the
 * canvas read-only with nothing but a console line and a `data-scene-engine`
 * attribute to say so (the founder hit exactly that when the design API died),
 * and degraded text measurement is worse still, because the ad keeps rendering
 * while its geometry is approximate.
 *
 * The ruling was "as is from the MVP editor, no separate banner", so this is
 * the design subsystem's own `EngineDisabledBanner` / `HeuristicMeasurementBanner`
 * (`EditorChrome.tsx:200-288`) ported whole: same lucide alert glyph, same
 * copy (asserted against that file by `scene-engine-banners.test.ts`), same
 * geometry, and the read-only state gets the SAME treatment as the degraded one
 * rather than a canvas-specific variant.
 *
 * It lives here, inside the canvas stage, rather than in the shell: the stage
 * is the one surface both mounts share, so the artifact route and the chat
 * route get it with no plumbing, it survives the inspector being closed, and
 * the state it reads (`engineStatus`, `measurementStatus`) is already local.
 *
 * The third G-D state — the CAS conflict — is deliberately NOT here: it stays
 * the inspector's existing note line ("Document moved on — reloaded.", D10).
 */
function SceneEngineBanners({
  engineStatus,
  measurementStatus,
}: {
  engineStatus: SceneEngineStatus;
  measurementStatus: string;
}) {
  const banners = sceneEngineBanners(engineStatus, measurementStatus);
  // Nothing wrong → no element at all, so a healthy canvas holds no space and
  // no assistive technology announces an empty alert region.
  if (banners.length === 0) {
    return null;
  }
  return (
    <div className={styles.bannerLayer}>
      {banners.map((banner) => (
        <div
          className={styles.banner}
          data-scene-banner={banner.kind}
          key={banner.kind}
          role="alert"
        >
          <AlertTriangleIcon
            aria-hidden="true"
            className={styles.bannerIcon}
            size={18}
          />
          <div className={styles.bannerBody}>
            <strong className={styles.bannerTitle}>{banner.title}</strong>
            <span className={styles.bannerText}>{banner.body}</span>
            {/* The chip ellipses (upstream's own `white-space: nowrap`), and
                our command string is longer than upstream's, so the DETAIL —
                the two engine hashes, the diagnosis — is what gets cut. The
                title restores it in full on hover without touching the approved
                visual; the console diagnostic still carries it too. */}
            <code
              className={styles.bannerCommand}
              title={
                banner.detail
                  ? `${banner.command} · ${banner.detail}`
                  : banner.command
              }
            >
              <span className={styles.bannerCommandName}>{banner.command}</span>
              {banner.detail ? ` · ${banner.detail}` : null}
            </code>
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Gate G-A's approved selection chrome (Variant B).
 *
 * An SVG with no `viewBox`, so its user units ARE the stage's CSS px and the
 * outline the adapter computed can be stroked verbatim. The stroke width is a
 * screen constant, not a scaled one: the outline is chrome, and the viewport
 * scales content only.
 *
 * Rotation is applied to a `<g>` about the box origin — the same pivot the draw
 * loop rotates a node about — so the outline and (later) its handles turn
 * together with one transform.
 *
 * `handles` is **G-A-approved geometry, enabled with Lane C** and therefore
 * defaulted off: nothing passes it today, because drag-to-resize does not exist
 * until AD4's Lane C and a grabbable handle that does nothing would be a fake
 * affordance.
 */
function SelectionChrome({
  handles = false,
  outline,
}: {
  handles?: boolean;
  outline: SceneSelectionOutline | null;
}) {
  // No selection → no element at all, not an empty overlay.
  if (!outline) {
    return null;
  }
  return (
    <svg
      aria-hidden="true"
      className={styles.selectionChrome}
      data-scene-selection-outline={outline.nodeId}
    >
      <g
        transform={
          outline.rotation
            ? `rotate(${outline.rotation} ${outline.x} ${outline.y})`
            : undefined
        }
      >
        <rect
          fill="none"
          height={outline.height}
          stroke={SELECTION_OUTLINE_COLOR}
          strokeWidth={SELECTION_OUTLINE_WIDTH}
          width={outline.width}
          x={outline.x}
          y={outline.y}
        />
        {handles
          ? selectionHandleRects(outline).map((handle) => (
              <rect
                fill={SELECTION_HANDLE_FILL}
                height={handle.size}
                key={`${handle.x},${handle.y}`}
                rx={SELECTION_HANDLE_CORNER_RADIUS}
                stroke={SELECTION_HANDLE_STROKE}
                strokeWidth={SELECTION_HANDLE_STROKE_WIDTH}
                width={handle.size}
                x={handle.x}
                y={handle.y}
              />
            ))
          : null}
      </g>
    </svg>
  );
}

/**
 * The imperative surface: everything below this line is the ported
 * `CanvasKitStage`, collapsed to one artboard.
 */
function ArtboardSurface({
  artboard,
  assets,
  dataEngine,
  dataMeasurement,
  dataSelectedNode,
  viewport,
}: {
  artboard: SceneArtboardModel | null;
  assets: Scene["assets"] | undefined;
  dataEngine: string;
  dataMeasurement: string;
  dataSelectedNode: string;
  viewport: WorkspaceViewport;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ckRef = useRef<CanvasKit | null>(null);
  const fontRef = useRef<TypefaceFontProvider | null>(null);
  const imagesRef = useRef<CanvasKitImageCache | null>(null);
  const surfaceRef = useRef<Surface | null>(null);
  const dirtyRef = useRef(false);
  const rafRef = useRef(0);
  // Resize is coalesced into the SAME rAF as the repaint: resetting the canvas
  // bitmap (element.width = …) blanks it, so wipe-and-redraw must happen
  // inside one frame callback or every resize step presents a blank stage.
  const resizePendingRef = useRef(false);
  const remakeSurfaceRef = useRef<(() => void) | null>(null);
  // The draw loop reads the LATEST props through a ref (the source stage
  // assigns it during render; this repo's lint requires the passive-effect
  // form). Declared BEFORE the invalidate effect below so the props it
  // publishes are already current when that effect marks the frame dirty —
  // and the rAF itself only runs after paint, well after both.
  const propsRef = useRef({ artboard, assets, viewport });
  useEffect(() => {
    propsRef.current = { artboard, assets, viewport };
  });

  // One draw pass; scheduled at most once per frame, only while dirty.
  const flush = () => {
    rafRef.current = 0;
    const ck = ckRef.current;
    if (resizePendingRef.current && ck) {
      remakeSurfaceRef.current?.();
    }
    const surface = surfaceRef.current;
    if (!ck || !surface || !dirtyRef.current) {
      return;
    }
    dirtyRef.current = false;
    const current = propsRef.current;
    const canvas = surface.getCanvas();
    canvas.save();
    const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
    canvas.scale(dpr, dpr);
    // AD2.10: the workspace — the source stage's own clear, reading the same
    // `--bg-canvas` custom property. This is what makes the surface an infinite
    // canvas rather than a hole in a card.
    canvas.clear(workspaceCanvasColor(ck, canvasRef.current));
    if (current.artboard) {
      canvas.translate(current.viewport.pan.x, current.viewport.pan.y);
      canvas.scale(current.viewport.zoom, current.viewport.zoom);
      drawArtboard(
        ck,
        canvas,
        current.artboard,
        current.viewport,
        fontRef.current,
        imagesRef.current,
      );
    }
    canvas.restore();
    surface.flush();
  };

  const invalidate = () => {
    dirtyRef.current = true;
    if (!rafRef.current && typeof requestAnimationFrame === "function") {
      rafRef.current = requestAnimationFrame(flush);
    }
  };

  // Mount: load CanvasKit once, then bind a surface to this canvas element.
  useEffect(() => {
    let disposed = false;
    const element = canvasRef.current;
    if (!element) {
      return;
    }

    const makeSurface = (ck: CanvasKit) => {
      resizePendingRef.current = false;
      try {
        surfaceRef.current?.delete();
        const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
        element.width = Math.max(1, Math.floor(element.clientWidth * dpr));
        element.height = Math.max(1, Math.floor(element.clientHeight * dpr));
        surfaceRef.current =
          ck.MakeWebGLCanvasSurface(element) ?? ck.MakeSWCanvasSurface(element);
      } catch {
        // Surface creation can fail (no GPU/context): leave the canvas blank
        // rather than throwing through the shell.
        surfaceRef.current = null;
      }
    };
    remakeSurfaceRef.current = () => {
      if (ckRef.current) {
        makeSurface(ckRef.current);
      }
    };

    void loadCanvasKit().then((bundle) => {
      if (disposed || !bundle) {
        return;
      }
      ckRef.current = bundle.ck;
      fontRef.current = bundle.fontProvider;
      // Bridges async asset bytes into the synchronous draw loop: a decode
      // landing re-renders the frame with real pixels. Resolution reads
      // through propsRef so it always sees the LATEST scene, and goes to the
      // headerless public passthrough (the cache fetches bare — a
      // workspace-gated URL could only ever 401).
      imagesRef.current = new CanvasKitImageCache(bundle.ck, {
        resolveUrl: (assetId) =>
          sceneAssetPassthroughUrl(propsRef.current.assets, assetId),
        onLoad: invalidate,
      });
      makeSurface(bundle.ck);
      invalidate();
    });

    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            // Skip no-op notifications (observe() fires once immediately);
            // real size changes wait for the next paint frame so the bitmap
            // wipe and the redraw land together.
            const dpr =
              typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
            const targetWidth = Math.max(
              1,
              Math.floor(element.clientWidth * dpr),
            );
            const targetHeight = Math.max(
              1,
              Math.floor(element.clientHeight * dpr),
            );
            if (
              element.width === targetWidth &&
              element.height === targetHeight
            ) {
              return;
            }
            resizePendingRef.current = true;
            invalidate();
          })
        : null;
    observer?.observe(element);

    // The ResizeObserver only sees CSS-size changes — devicePixelRatio can
    // change with NO size change (window dragged to another display, display
    // scaling, browser zoom). Without this watcher the surface keeps the old
    // density forever and every frame is CSS-stretched. matchMedia is re-armed
    // per value because a resolution query only fires when ITS OWN value stops
    // holding.
    let dprQuery: MediaQueryList | null = null;
    const onDprChange = () => {
      resizePendingRef.current = true;
      invalidate();
      armDprWatch();
    };
    const armDprWatch = () => {
      if (typeof matchMedia !== "function") {
        return;
      }
      dprQuery?.removeEventListener?.("change", onDprChange);
      const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
      dprQuery = matchMedia(`(resolution: ${dpr}dppx)`);
      dprQuery.addEventListener?.("change", onDprChange);
    };
    armDprWatch();

    return () => {
      disposed = true;
      observer?.disconnect();
      dprQuery?.removeEventListener?.("change", onDprChange);
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        // Reset the guard: leaving the (now-cancelled) id here would make the
        // next invalidate() skip scheduling, so a re-mount (React StrictMode
        // double-invokes effects in dev) would never redraw.
        rafRef.current = 0;
      }
      surfaceRef.current?.delete();
      surfaceRef.current = null;
      imagesRef.current?.dispose();
      imagesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Descriptor / viewport changes mark dirty; drawing happens in rAF.
  useEffect(invalidate, [artboard, viewport]);

  return (
    <canvas
      className={styles.canvas}
      data-scene-engine={dataEngine}
      data-scene-selected-node={dataSelectedNode}
      data-scene-text-measurement={dataMeasurement}
      ref={canvasRef}
    />
  );
}

/**
 * The workspace surface colour, ported verbatim from the source stage
 * (`CanvasKitStage.workspaceCanvasColor`) with one improvement: the custom
 * property is read from the CANVAS, not from `document.documentElement`, so a
 * `--bg-canvas` defined anywhere up this subtree (the stage's own module CSS
 * defines it, since the platform shell does not) is honoured and the painted
 * pixels can never disagree with the CSS backdrop behind them.
 */
function workspaceCanvasColor(
  ck: CanvasKit,
  element: Element | null,
): Float32Array {
  const css =
    element && typeof getComputedStyle === "function"
      ? getComputedStyle(element).getPropertyValue("--bg-canvas").trim()
      : "";
  return (
    parseColor(ck, css || WORKSPACE_CANVAS_FALLBACK) ??
    ck.Color4f(0.961, 0.961, 0.961, 1)
  );
}

/**
 * One artboard on the workspace: shadow, content, edge.
 *
 * The order is the source's `drawArtboard` — shell behind, content clipped to
 * the page box, border stroked on top — and the clip is the load-bearing part:
 * it is what makes the artboard's own edges the ONLY boundary the page has, now
 * that nothing else surrounds it. Overflowing content stops at the page edge;
 * everything outside is workspace.
 *
 * Every Paint (and the MaskFilter) is deleted before returning: these are wasm
 * heap objects, and the draw loop runs on every frame of a pan.
 */
function drawArtboard(
  ck: CanvasKit,
  canvas: ReturnType<Surface["getCanvas"]>,
  artboard: SceneArtboardModel,
  viewport: WorkspaceViewport,
  fontProvider: TypefaceFontProvider | null,
  images: CanvasKitImageCache | null,
) {
  const rect = artboard.rect;
  const chrome = artboardChromeGeometry(rect, viewport.zoom);

  const shadowPaint = new ck.Paint();
  shadowPaint.setAntiAlias(true);
  shadowPaint.setStyle(ck.PaintStyle.Fill);
  shadowPaint.setColor(parseColor(ck, ARTBOARD_SHADOW_COLOR) ?? ck.BLACK);
  const blur = ck.MaskFilter.MakeBlur(
    ck.BlurStyle.Normal,
    chrome.shadowSigma,
    true,
  );
  shadowPaint.setMaskFilter(blur);
  canvas.drawRect(
    ck.LTRBRect(
      chrome.shadow.x,
      chrome.shadow.y,
      chrome.shadow.x + chrome.shadow.width,
      chrome.shadow.y + chrome.shadow.height,
    ),
    shadowPaint,
  );
  blur.delete();
  shadowPaint.delete();

  canvas.save();
  canvas.translate(rect.x, rect.y);
  canvas.clipRect(
    ck.LTRBRect(0, 0, artboard.page.width, artboard.page.height),
    ck.ClipOp.Intersect,
    true,
  );
  drawDescriptorTree(
    ck,
    canvas,
    artboard.page,
    artboard.nodes,
    fontProvider,
    images,
  );
  canvas.restore();

  const borderPaint = new ck.Paint();
  borderPaint.setAntiAlias(true);
  borderPaint.setStyle(ck.PaintStyle.Stroke);
  borderPaint.setStrokeWidth(chrome.borderWidth);
  borderPaint.setColor(parseColor(ck, ARTBOARD_BORDER_COLOR) ?? ck.BLACK);
  canvas.drawRect(
    ck.LTRBRect(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height),
    borderPaint,
  );
  borderPaint.delete();
}

