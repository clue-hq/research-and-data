"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";
import type { CanvasKit, Surface, TypefaceFontProvider } from "canvaskit-wasm";
import {
  sceneArtboardModel,
  sceneAssetPassthroughUrl,
  snapZoomPercent,
  type SceneArtboardModel,
} from "../adapter/scene-canvas-view";
import { drawDescriptorTree } from "../engine/scene/canvaskit/drawDescriptors";
import { CanvasKitImageCache } from "../engine/scene/canvaskit/imageCache";
import {
  loadCanvasKit,
  subscribeTextMeasurementStatus,
  textMeasurementStatusSnapshot,
} from "../engine/scene/canvaskit/loadCanvasKit";
import type { Scene } from "../engine/scene/contracts";
import type { HitResult } from "../engine/scene/wasmEngine";
import {
  defaultWorkspaceViewport,
  fitWorkspaceRectToViewport,
  type WorkspaceViewport,
} from "../engine/scene/workspaceViewport";
import {
  useSceneDocument,
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
 * Three deliberate departures from the source stage:
 *
 * - **One artboard.** The platform mounts a single document inside a fixed
 *   card, so the workspace's artboard grid, its active/inactive border and its
 *   name labels are gone. (§1.1's artifact-name label and W×H chip are
 *   ratified in the contract but the AD0.1 dummy delta carries no CSS for
 *   them — inventing that styling is barred, so they wait for Gate G-A's
 *   mockup sheet. Nothing here fakes them.)
 * - **No canvas backdrop.** The source clears to the workspace gray and paints
 *   a dark rounded shell behind each artboard; here the dummy's `.imageCanvas`
 *   card IS the artboard chrome (its hairline border, radius and shadow), so
 *   the surface clears to transparent and the designed card shows through.
 * - **Content only.** Selection chrome stays out of the canvas by the source's
 *   own Decision 5 — AD2.5 mounts its SVG overlay as a sibling of the
 *   `<canvas>` inside `.stage`, so hover/selection never trigger a wasm redraw.
 *
 * Read-only by construction: no pointer handlers, no operations, no write
 * path. When the wasm stamp handshake fails the scene still renders — from the
 * server's own snapshot — and `engineDisabled` rides upward (Gate G-D owns the
 * banner wording; until it lands the console diagnostic in `useSceneDocument`
 * is the honest signal).
 */

export interface SceneCanvasControls {
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
  /** A menu-chosen zoom (`"45%"`). Absent — the AD2.3 read path — fits the
   * artboard to the card on open (§1.10) and reports the step it landed on. */
  zoom?: string | null;
  /** The fit-on-open zoom as one of the header menu's own 5% steps. */
  onFitZoom?: (zoom: string) => void;
  /** Mirrors the wasm stamp handshake upward, so the shell can refuse edits
   * and (post Gate G-D) explain why. */
  onEngineStatusChange?: (status: SceneEngineStatus) => void;
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
  reloadToken = 0,
  zoom = null,
}: SceneArtifactCanvasProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const { engine, engineStatus, pageId, refresh, scene, tokenGeneration } =
    useSceneDocument(documentId, reloadToken);

  // The engine's own text-measurement status store — `heuristic` means the
  // Skia pass never ran, which is a real (silent) rendering difference the
  // approved banner will name (Gate G-D).
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
  // against a resize, and AD2.8's menu value simply overrides the zoom while
  // keeping the same centering math.
  const fitted = useMemo<WorkspaceViewport | null>(
    () =>
      artboard
        ? fitWorkspaceRectToViewport({ viewport: stageSize, rect: artboard.rect })
        : null,
    [artboard, stageSize],
  );
  const viewport = useMemo<WorkspaceViewport>(() => {
    if (!artboard || !fitted) {
      return defaultWorkspaceViewport();
    }
    const chosen = parseZoomPercent(zoom);
    if (chosen === null) {
      return fitted;
    }
    return {
      zoom: chosen,
      pan: {
        x: stageSize.width / 2 - (artboard.rect.width / 2) * chosen,
        y: stageSize.height / 2 - (artboard.rect.height / 2) * chosen,
      },
    };
  }, [artboard, fitted, stageSize, zoom]);

  // Report the fit as a step the header menu actually offers. Passive effect
  // (callback only, no state) so it can never fight the derivation above.
  const onFitZoomRef = useRef(onFitZoom);
  useEffect(() => {
    onFitZoomRef.current = onFitZoom;
  });
  const fitZoom = fitted ? snapZoomPercent(fitted.zoom) : null;
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

  useEffect(() => {
    if (!controlsRef) {
      return;
    }
    controlsRef.current = {
      hitTest: (x, y) =>
        engine && pageId ? engine.hitTest(pageId, x, y) : null,
      refresh,
      sceneSnapshot: () => scene,
    };
    return () => {
      controlsRef.current = null;
    };
  }, [controlsRef, engine, pageId, refresh, scene]);

  return (
    <div className={styles.stage} ref={stageRef}>
      <ArtboardSurface
        artboard={artboard}
        assets={scene?.assets}
        // Test/diagnostic hooks, not chrome: the honest engine + text
        // measurement state, readable without a banner (Gate G-D).
        dataEngine={engineStatus.engineDisabled ? "disabled" : "wasm"}
        dataMeasurement={measurementStatus}
        viewport={viewport}
      />
      {/* AD2.5 mounts its selection overlay here, as a sibling of the canvas. */}
    </div>
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
  viewport,
}: {
  artboard: SceneArtboardModel | null;
  assets: Scene["assets"] | undefined;
  dataEngine: string;
  dataMeasurement: string;
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
    // Transparent, not the source's workspace gray: the dummy's artboard card
    // owns the backdrop (§1.1's card chrome is CSS, and stays CSS).
    canvas.clear(ck.TRANSPARENT);
    if (current.artboard) {
      canvas.translate(current.viewport.pan.x, current.viewport.pan.y);
      canvas.scale(current.viewport.zoom, current.viewport.zoom);
      canvas.save();
      canvas.clipRect(
        ck.LTRBRect(
          0,
          0,
          current.artboard.page.width,
          current.artboard.page.height,
        ),
        ck.ClipOp.Intersect,
        true,
      );
      drawDescriptorTree(
        ck,
        canvas,
        current.artboard.page,
        current.artboard.nodes,
        fontRef.current,
        imagesRef.current,
      );
      canvas.restore();
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
      data-scene-text-measurement={dataMeasurement}
      ref={canvasRef}
    />
  );
}

/** `"45%"` → `0.45`; anything unparseable (including the AD2.3 default) → null,
 * which means "fit the artboard". */
function parseZoomPercent(zoom: string | null | undefined): number | null {
  if (!zoom) {
    return null;
  }
  const parsed = Number.parseFloat(zoom.replace("%", ""));
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed / 100;
}

