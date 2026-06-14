import { MAX_CANVAS_ZOOM, MIN_CANVAS_ZOOM, clampCanvasZoom } from "./canvasViewport";
import type { Point, Rect } from "./workspaceLayout";

const DEFAULT_VIEWPORT_MARGIN = 128;

export interface WorkspaceViewport {
  zoom: number;
  pan: Point;
}

export interface ViewportSize {
  width: number;
  height: number;
}

export interface FitWorkspaceInput {
  viewport: ViewportSize;
  rect: Rect;
  margin?: number;
}

export function defaultWorkspaceViewport(): WorkspaceViewport {
  return {
    zoom: 1,
    pan: { x: 0, y: 0 }
  };
}

export function fitWorkspaceRectToViewport({
  viewport,
  rect,
  margin = DEFAULT_VIEWPORT_MARGIN
}: FitWorkspaceInput): WorkspaceViewport {
  if (!isPositiveFinite(viewport.width) || !isPositiveFinite(viewport.height) || !isPositiveFinite(rect.width) || !isPositiveFinite(rect.height)) {
    return defaultWorkspaceViewport();
  }

  const availableWidth = Math.max(1, viewport.width - margin);
  const availableHeight = Math.max(1, viewport.height - margin);
  const zoom = clampWorkspaceZoom(Math.min(availableWidth / rect.width, availableHeight / rect.height));
  const pan = {
    x: viewport.width / 2 - (rect.x + rect.width / 2) * zoom,
    y: viewport.height / 2 - (rect.y + rect.height / 2) * zoom
  };

  return { zoom, pan };
}

export function clampWorkspaceZoom(value: number): number {
  return clampCanvasZoom(value);
}

export function screenToWorkspace(point: Point, viewport: WorkspaceViewport): Point {
  const zoom = clampWorkspaceZoom(viewport.zoom);
  return {
    x: (point.x - viewport.pan.x) / zoom,
    y: (point.y - viewport.pan.y) / zoom
  };
}

export function workspaceToScreen(point: Point, viewport: WorkspaceViewport): Point {
  const zoom = clampWorkspaceZoom(viewport.zoom);
  return {
    x: point.x * zoom + viewport.pan.x,
    y: point.y * zoom + viewport.pan.y
  };
}

export function workspaceRectToScreen(rect: Rect, viewport: WorkspaceViewport): Rect {
  const topLeft = workspaceToScreen(rect, viewport);
  const zoom = clampWorkspaceZoom(viewport.zoom);
  return {
    x: topLeft.x,
    y: topLeft.y,
    width: rect.width * zoom,
    height: rect.height * zoom
  };
}

export function zoomWorkspaceViewportAtPoint(
  viewport: WorkspaceViewport,
  screenPoint: Point,
  nextZoom: number
): WorkspaceViewport {
  const currentZoom = clampWorkspaceZoom(viewport.zoom);
  const safeNextZoom = clampWorkspaceZoom(nextZoom);
  if (safeNextZoom === currentZoom) {
    return {
      zoom: safeNextZoom,
      pan: viewport.pan
    };
  }

  const workspacePoint = screenToWorkspace(screenPoint, viewport);
  return {
    zoom: safeNextZoom,
    pan: {
      x: screenPoint.x - workspacePoint.x * safeNextZoom,
      y: screenPoint.y - workspacePoint.y * safeNextZoom
    }
  };
}

export function panWorkspaceViewport(viewport: WorkspaceViewport, delta: Point): WorkspaceViewport {
  return {
    zoom: clampWorkspaceZoom(viewport.zoom),
    pan: {
      x: finiteOrZero(viewport.pan.x) + finiteOrZero(delta.x),
      y: finiteOrZero(viewport.pan.y) + finiteOrZero(delta.y)
    }
  };
}

export function clampWorkspacePanToKeepVisible(
  viewport: WorkspaceViewport,
  workspaceBounds: Rect,
  viewportSize: ViewportSize,
  minVisible = 96
): WorkspaceViewport {
  const zoom = clampWorkspaceZoom(viewport.zoom);
  if (!isPositiveFinite(workspaceBounds.width) || !isPositiveFinite(workspaceBounds.height)) {
    return { zoom, pan: viewport.pan };
  }
  return {
    zoom,
    pan: {
      x: clampAxisPan({
        pan: finiteOrZero(viewport.pan.x),
        zoom,
        viewportSize: viewportSize.width,
        contentStart: workspaceBounds.x,
        contentSize: workspaceBounds.width,
        minVisible
      }),
      y: clampAxisPan({
        pan: finiteOrZero(viewport.pan.y),
        zoom,
        viewportSize: viewportSize.height,
        contentStart: workspaceBounds.y,
        contentSize: workspaceBounds.height,
        minVisible
      })
    }
  };
}

export { MAX_CANVAS_ZOOM as MAX_WORKSPACE_ZOOM, MIN_CANVAS_ZOOM as MIN_WORKSPACE_ZOOM };

function clampAxisPan({
  pan,
  zoom,
  viewportSize,
  contentStart,
  contentSize,
  minVisible
}: {
  pan: number;
  zoom: number;
  viewportSize: number;
  contentStart: number;
  contentSize: number;
  minVisible: number;
}): number {
  if (!isPositiveFinite(viewportSize)) {
    return pan;
  }

  const minVisibleScreen = Math.min(contentSize * zoom * 0.5, minVisible);
  const contentMin = contentStart * zoom + pan;
  const contentMax = (contentStart + contentSize) * zoom + pan;
  if (contentMax - contentMin <= viewportSize - minVisibleScreen) {
    return pan;
  }

  const minPan = minVisibleScreen - (contentStart + contentSize) * zoom;
  const maxPan = viewportSize - minVisibleScreen - contentStart * zoom;
  return Math.min(maxPan, Math.max(minPan, pan));
}

function finiteOrZero(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}
