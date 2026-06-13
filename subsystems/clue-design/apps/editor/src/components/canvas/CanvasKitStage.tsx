"use client";

import { useEffect, useRef } from "react";
import type { CanvasKit, FontMgr, Surface } from "canvaskit-wasm";
import type { RenderPageDescriptor } from "@/engine/renderAdapter";
import { drawDescriptorTree, type DrawNode } from "@/engine/canvaskit/drawDescriptors";
import { loadCanvasKit } from "@/engine/canvaskit/loadCanvasKit";

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
  page: RenderPageDescriptor;
  /** The page's node tree as descriptors (incl. full shadow stacks). */
  nodes: DrawNode[];
  /** Page-origin offset in canvas px (the centered artboard position). */
  pageOrigin: { x: number; y: number };
  zoom: number;
}

export function CanvasKitStage({ page, nodes, pageOrigin, zoom }: CanvasKitStageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ckRef = useRef<CanvasKit | null>(null);
  const fontRef = useRef<FontMgr | null>(null);
  const surfaceRef = useRef<Surface | null>(null);
  const dirtyRef = useRef(false);
  const rafRef = useRef(0);
  const propsRef = useRef({ page, nodes, pageOrigin, zoom });
  propsRef.current = { page, nodes, pageOrigin, zoom };

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
    canvas.clear(ck.Color(245, 241, 233, 1)); // editor backdrop
    canvas.translate(current.pageOrigin.x, current.pageOrigin.y);
    canvas.scale(current.zoom, current.zoom);
    drawDescriptorTree(ck, canvas, current.page, current.nodes, fontRef.current);
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
      surfaceRef.current?.delete();
      const dpr = typeof devicePixelRatio === "number" ? devicePixelRatio : 1;
      element.width = Math.max(1, Math.floor(element.clientWidth * dpr));
      element.height = Math.max(1, Math.floor(element.clientHeight * dpr));
      surfaceRef.current = ck.MakeWebGLCanvasSurface(element) ?? ck.MakeSWCanvasSurface(element);
      invalidate();
    };

    void loadCanvasKit().then((bundle) => {
      if (disposed || !bundle) {
        return;
      }
      ckRef.current = bundle.ck;
      fontRef.current = bundle.fontMgr;
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
      }
      surfaceRef.current?.delete();
      surfaceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Descriptor / viewport changes mark dirty; drawing happens in rAF.
  useEffect(invalidate, [page, nodes, pageOrigin, zoom]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />;
}
