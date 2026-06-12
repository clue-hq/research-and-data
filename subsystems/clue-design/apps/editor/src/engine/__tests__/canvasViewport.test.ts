import { describe, expect, it } from "vitest";
import {
  centeredPageOrigin,
  clampCanvasPan,
  clampCanvasZoom,
  fitZoomForPage,
  MAX_CANVAS_ZOOM,
  MIN_CANVAS_ZOOM
} from "../canvasViewport";

describe("canvas viewport helpers", () => {
  it("fits a square custom artboard inside the available viewport", () => {
    const zoom = fitZoomForPage({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 1080,
      pageHeight: 1080
    });

    expect(zoom).toBeCloseTo(0.577, 2);
    expect(1080 * zoom).toBeLessThanOrEqual(900 - 96);
    expect(1080 * zoom).toBeLessThanOrEqual(720 - 96);
  });

  it("fits wide and tall custom artboards by the constraining axis", () => {
    const wide = fitZoomForPage({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 1600,
      pageHeight: 500
    });
    const tall = fitZoomForPage({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 500,
      pageHeight: 1600
    });

    expect(wide).toBeCloseTo((900 - 96) / 1600, 3);
    expect(tall).toBeCloseTo((720 - 96) / 1600, 3);
  });

  it("caps tiny artifacts at the maximum editor zoom", () => {
    const zoom = fitZoomForPage({
      viewportWidth: 1200,
      viewportHeight: 900,
      pageWidth: 100,
      pageHeight: 100
    });

    expect(zoom).toBe(MAX_CANVAS_ZOOM);
  });

  it("clamps invalid zoom values to a usable range", () => {
    expect(clampCanvasZoom(Number.NaN)).toBe(1);
    expect(clampCanvasZoom(0.01)).toBe(MIN_CANVAS_ZOOM);
    expect(clampCanvasZoom(9)).toBe(MAX_CANVAS_ZOOM);
  });

  it("centers the page when there is spare viewport space", () => {
    const origin = centeredPageOrigin({
      viewportWidth: 1200,
      viewportHeight: 900,
      pageWidth: 600,
      pageHeight: 400,
      zoom: 1
    });

    expect(origin).toEqual({ x: 300, y: 250 });
  });

  it("keeps fitted custom pages centered instead of drifting with stale pan", () => {
    const pan = clampCanvasPan({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 1080,
      pageHeight: 1080,
      zoom: 0.57,
      baseOrigin: { x: 245, y: 92 },
      pan: { x: -500, y: 300 }
    });

    expect(pan).toEqual({ x: 0, y: 0 });
  });

  it("allows bounded pan for wide custom artifacts that exceed the viewport", () => {
    const baseOrigin = centeredPageOrigin({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 1600,
      pageHeight: 500,
      zoom: 1
    });
    const pan = clampCanvasPan({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 1600,
      pageHeight: 500,
      zoom: 1,
      baseOrigin,
      pan: { x: -2000, y: 1000 }
    });

    expect(baseOrigin).toEqual({ x: 32, y: 110 });
    expect(baseOrigin.x + pan.x).toBe(-1504);
    expect(pan.y).toBe(0);
  });

  it("allows bounded vertical pan for tall custom artifacts", () => {
    const baseOrigin = centeredPageOrigin({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 500,
      pageHeight: 1600,
      zoom: 1
    });
    const pan = clampCanvasPan({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 500,
      pageHeight: 1600,
      zoom: 1,
      baseOrigin,
      pan: { x: 800, y: -2200 }
    });

    expect(baseOrigin).toEqual({ x: 200, y: 40 });
    expect(pan.x).toBe(0);
    expect(baseOrigin.y + pan.y).toBe(-1504);
  });

  it("drops invalid pan input back to a stable origin", () => {
    const pan = clampCanvasPan({
      viewportWidth: 900,
      viewportHeight: 720,
      pageWidth: 1600,
      pageHeight: 500,
      zoom: 1,
      baseOrigin: { x: 32, y: 110 },
      pan: { x: Number.NaN, y: Number.POSITIVE_INFINITY }
    });

    expect(pan).toEqual({ x: 0, y: 0 });
  });
});
