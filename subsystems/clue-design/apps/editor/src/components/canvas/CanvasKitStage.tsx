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

const API_BASE_URL = process.env.NEXT_PUBLIC_LUMEN_API_BASE_URL ?? "http://localhost:8000";

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
}

export function CanvasKitStage({ artboards, viewport }: CanvasKitStageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ckRef = useRef<CanvasKit | null>(null);
  const fontRef = useRef<TypefaceFontProvider | null>(null);
  const imagesRef = useRef<CanvasKitImageCache | null>(null);
  const surfaceRef = useRef<Surface | null>(null);
  const dirtyRef = useRef(false);
  const rafRef = useRef(0);
  const propsRef = useRef({ artboards, viewport });
  propsRef.current = { artboards, viewport };

  // One draw pass; scheduled at most once per frame, only while dirty.
  const flush = () => {
    rafRef.current = 0;
    const ck = ckRef.current;
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
    canvas.clear(parseColor(ck, "#3b3f46") ?? ck.Color4f(0.231, 0.247, 0.275, 1));
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
      try {
        surfaceRef.current?.delete();
        const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
        element.width = Math.max(1, Math.floor(element.clientWidth * dpr));
        element.height = Math.max(1, Math.floor(element.clientHeight * dpr));
        surfaceRef.current = ck.MakeWebGLCanvasSurface(element) ?? ck.MakeSWCanvasSurface(element);
        invalidate();
      } catch {
        // Surface creation can fail (no GPU/context); leave the canvas blank
        // and let the parent fall back to Konva.
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
    });

    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            if (ckRef.current) {
              makeSurface(ckRef.current);
            }
          })
        : null;
    observer?.observe(element);

    return () => {
      disposed = true;
      observer?.disconnect();
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
  canvas.clipRect(ck.LTRBRect(0, 0, artboard.page.width, artboard.page.height), ck.ClipOp.Intersect, true);
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
