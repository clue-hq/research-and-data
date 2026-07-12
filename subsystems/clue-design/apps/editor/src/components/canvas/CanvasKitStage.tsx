"use client";

import { useEffect, useRef } from "react";
import type { CanvasKit, Surface, TypefaceFontProvider } from "canvaskit-wasm";
import type { RenderPageDescriptor } from "@/engine/renderAdapter";
import type { Rect } from "@/engine/workspaceLayout";
import type { WorkspaceViewport } from "@/engine/workspaceViewport";
import { drawDescriptorTree, parseColor, type DrawNode } from "@/engine/canvaskit/drawDescriptors";
import { CanvasKitImageCache, type CanvasKitImageSource } from "@/engine/canvaskit/imageCache";
import { loadCanvasKit } from "@/engine/canvaskit/loadCanvasKit";
import { assetBytesUrl } from "@/engine/assetLibrary";
import { editorApiBaseUrl } from "@/engine/editorConfig";

const API_BASE_URL = editorApiBaseUrl();

/**
 * Wave 3 C2: the imperative CanvasKit render surface. Replaces react-konva's
 * retained `<Stage>`/`<Layer>` reconciliation with one immediate draw of the
 * descriptor tree (the C2 interpreter).
 *
 * - the wasm + font load once via the C0 singleton; a failed load leaves the
 *   canvas blank and the parent falls back to Konva
 * - one WebGL/CPU surface per <canvas>, recreated on resize at devicePixelRatio
 * - descriptor / viewport changes set a dirty flag; a single rAF drains it; no
 *   rAF runs while clean (frame budget stays with real content)
 *
 * Drawing is content-only: selection chrome and handles live in a sibling SVG
 * overlay (Decision 5), so hover/selection never trigger a wasm redraw.
 */

export interface CanvasKitStageProps {
  artboards: CanvasKitArtboard[];
  viewport: WorkspaceViewport;
}

export interface CanvasKitArtboard {
  page: RenderPageDescriptor;
  nodes: DrawNode[];
  workspaceRect: Rect;
  isActive: boolean;
  /** Print workstream W3: the page's bleed rect in descriptor space, relative
   * to the page top-left (negative origin — art extends past trim). Present
   * only when the print feature is on and the page defines a bleed; content is
   * then clipped to this box instead of the trim box so bleed art stays
   * visible up to the bleed line. */
  bleed?: Rect | null;
}

export function CanvasKitStage({ artboards, viewport }: CanvasKitStageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ckRef = useRef<CanvasKit | null>(null);
  const fontRef = useRef<TypefaceFontProvider | null>(null);
  const imagesRef = useRef<CanvasKitImageCache | null>(null);
  const surfaceRef = useRef<Surface | null>(null);
  const dirtyRef = useRef(false);
  const rafRef = useRef(0);
  // Resize is coalesced into the SAME rAF as the repaint: resetting the
  // canvas bitmap (element.width = …) blanks it, so wipe-and-redraw must
  // happen inside one frame callback or every sidebar-drag step presents a
  // blank stage (the resize-flicker bug).
  const resizePendingRef = useRef(false);
  const remakeSurfaceRef = useRef<(() => void) | null>(null);
  const propsRef = useRef({ artboards, viewport });
  propsRef.current = { artboards, viewport };

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
    canvas.clear(workspaceCanvasColor(ck));
    canvas.translate(current.viewport.pan.x, current.viewport.pan.y);
    canvas.scale(current.viewport.zoom, current.viewport.zoom);
    for (const artboard of current.artboards) {
      drawArtboard(ck, canvas, artboard, fontRef.current, imagesRef.current);
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
        surfaceRef.current = ck.MakeWebGLCanvasSurface(element) ?? ck.MakeSWCanvasSurface(element);
      } catch {
        // Surface creation can fail (no GPU/context); leave the canvas blank
        // and let the parent fall back to Konva.
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
      // landing re-renders the frame with real image pixels (Step 2 / E0.1).
      imagesRef.current = new CanvasKitImageCache(bundle.ck, {
        resolveUrl: (assetId) => assetBytesUrl(API_BASE_URL, assetId),
        onLoad: invalidate
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
            const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
            const targetWidth = Math.max(1, Math.floor(element.clientWidth * dpr));
            const targetHeight = Math.max(1, Math.floor(element.clientHeight * dpr));
            if (element.width === targetWidth && element.height === targetHeight) {
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
    // density forever and every frame is CSS-stretched: a permanently blurry
    // canvas while exports stay sharp. matchMedia is re-armed per value
    // because a resolution query only fires when ITS OWN value stops holding.
    let dprQuery: MediaQueryList | null = null;
    const armDprWatch = () => {
      if (typeof matchMedia !== "function") {
        return;
      }
      dprQuery?.removeEventListener?.("change", onDprChange);
      const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
      dprQuery = matchMedia(`(resolution: ${dpr}dppx)`);
      dprQuery.addEventListener?.("change", onDprChange);
    };
    const onDprChange = () => {
      resizePendingRef.current = true;
      invalidate();
      armDprWatch();
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
  useEffect(invalidate, [artboards, viewport]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />;
}

function workspaceCanvasColor(ck: CanvasKit): Float32Array {
  const css =
    typeof document !== "undefined"
      ? getComputedStyle(document.documentElement).getPropertyValue("--bg-canvas").trim()
      : "";
  return parseColor(ck, css || "#f5f5f5") ?? ck.Color4f(0.961, 0.961, 0.961, 1);
}

function drawArtboard(
  ck: CanvasKit,
  canvas: import("canvaskit-wasm").Canvas,
  artboard: CanvasKitArtboard,
  fontProvider: TypefaceFontProvider | null,
  images: CanvasKitImageSource | null
) {
  const rect = artboard.workspaceRect;
  const shellPaint = paint(ck, "#151920", ck.PaintStyle.Fill);
  canvas.drawRRect(ck.RRectXY(ck.LTRBRect(rect.x - 18, rect.y - 18, rect.x + rect.width + 18, rect.y + rect.height + 18), 10, 10), shellPaint);
  shellPaint.delete();

  canvas.save();
  canvas.translate(rect.x, rect.y);
  // Clip content to the bleed box when the print feature supplies one (art
  // extends past trim, visible up to the bleed line); otherwise clip at trim
  // exactly as before. The bleed origin is negative, so this widens the clip.
  const clip = artboard.bleed
    ? ck.LTRBRect(
        artboard.bleed.x,
        artboard.bleed.y,
        artboard.bleed.x + artboard.bleed.width,
        artboard.bleed.y + artboard.bleed.height
      )
    : ck.LTRBRect(0, 0, artboard.page.width, artboard.page.height);
  canvas.clipRect(clip, ck.ClipOp.Intersect, true);
  drawDescriptorTree(ck, canvas, artboard.page, artboard.nodes, fontProvider, images);
  canvas.restore();

  const borderPaint = paint(ck, artboard.isActive ? "#58c4c8" : "#858f99", ck.PaintStyle.Stroke);
  borderPaint.setStrokeWidth(artboard.isActive ? 2 : 1);
  canvas.drawRect(ck.LTRBRect(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height), borderPaint);
  borderPaint.delete();
}

function paint(ck: CanvasKit, color: string, style: import("canvaskit-wasm").PaintStyle) {
  const next = new ck.Paint();
  next.setAntiAlias(true);
  next.setStyle(style);
  next.setColor(parseColor(ck, color) ?? ck.BLACK);
  return next;
}
