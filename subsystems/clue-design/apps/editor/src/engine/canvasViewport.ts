export const MIN_CANVAS_ZOOM = 0.1;
export const MAX_CANVAS_ZOOM = 2;
const DEFAULT_VIEWPORT_MARGIN = 96;

export interface FitZoomInput {
  viewportWidth: number;
  viewportHeight: number;
  pageWidth: number;
  pageHeight: number;
  margin?: number;
}

export interface PageOriginInput extends FitZoomInput {
  zoom: number;
  minX?: number;
  minY?: number;
}

export interface CanvasPan {
  x: number;
  y: number;
}

export interface ClampPanInput extends FitZoomInput {
  zoom: number;
  baseOrigin: CanvasPan;
  pan: CanvasPan;
  minVisible?: number;
}

export function clampCanvasZoom(value: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.min(MAX_CANVAS_ZOOM, Math.max(MIN_CANVAS_ZOOM, value));
}

export function fitZoomForPage({
  viewportWidth,
  viewportHeight,
  pageWidth,
  pageHeight,
  margin = DEFAULT_VIEWPORT_MARGIN
}: FitZoomInput): number {
  if (!isPositiveFinite(viewportWidth) || !isPositiveFinite(viewportHeight) || !isPositiveFinite(pageWidth) || !isPositiveFinite(pageHeight)) {
    return 1;
  }

  const availableWidth = Math.max(1, viewportWidth - margin);
  const availableHeight = Math.max(1, viewportHeight - margin);
  return clampCanvasZoom(Math.min(availableWidth / pageWidth, availableHeight / pageHeight));
}

export function centeredPageOrigin({
  viewportWidth,
  viewportHeight,
  pageWidth,
  pageHeight,
  zoom,
  minX = 32,
  minY = 40
}: PageOriginInput): { x: number; y: number } {
  const safeZoom = clampCanvasZoom(zoom);
  if (!isPositiveFinite(viewportWidth) || !isPositiveFinite(viewportHeight) || !isPositiveFinite(pageWidth) || !isPositiveFinite(pageHeight)) {
    return { x: minX, y: minY };
  }

  return {
    x: Math.max(minX, (viewportWidth - pageWidth * safeZoom) / 2 / safeZoom),
    y: Math.max(minY, (viewportHeight - pageHeight * safeZoom) / 2 / safeZoom)
  };
}

export function clampCanvasPan({
  viewportWidth,
  viewportHeight,
  pageWidth,
  pageHeight,
  zoom,
  baseOrigin,
  pan,
  minVisible = 96
}: ClampPanInput): CanvasPan {
  const safeZoom = clampCanvasZoom(zoom);
  if (
    !isPositiveFinite(viewportWidth) ||
    !isPositiveFinite(viewportHeight) ||
    !isPositiveFinite(pageWidth) ||
    !isPositiveFinite(pageHeight) ||
    !isPositiveFinite(safeZoom)
  ) {
    return { x: 0, y: 0 };
  }

  return {
    x: clampAxisPan({
      pan: finiteOrZero(pan.x),
      baseOrigin: finiteOrZero(baseOrigin.x),
      viewportSize: viewportWidth,
      pageSize: pageWidth,
      zoom: safeZoom,
      minVisible
    }),
    y: clampAxisPan({
      pan: finiteOrZero(pan.y),
      baseOrigin: finiteOrZero(baseOrigin.y),
      viewportSize: viewportHeight,
      pageSize: pageHeight,
      zoom: safeZoom,
      minVisible
    })
  };
}

function clampAxisPan({
  pan,
  baseOrigin,
  viewportSize,
  pageSize,
  zoom,
  minVisible
}: {
  pan: number;
  baseOrigin: number;
  viewportSize: number;
  pageSize: number;
  zoom: number;
  minVisible: number;
}): number {
  const viewportWorld = viewportSize / zoom;
  const minVisibleWorld = Math.min(pageSize / 2, minVisible / zoom);
  if (pageSize <= Math.max(1, viewportWorld - minVisibleWorld)) {
    return 0;
  }

  const origin = baseOrigin + pan;
  const minOrigin = minVisibleWorld - pageSize;
  const maxOrigin = viewportWorld - minVisibleWorld;
  return Math.min(maxOrigin, Math.max(minOrigin, origin)) - baseOrigin;
}

function finiteOrZero(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}
