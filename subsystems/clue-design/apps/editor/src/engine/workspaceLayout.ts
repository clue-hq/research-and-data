import type { Diagnostic, PageId, Scene } from "./contracts";
import { pageDescriptor } from "./renderAdapter";
import { listPages, nodeIdForAsset, pageIdForNode } from "./sceneQueries";

export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DiagnosticsSummary {
  errorCount: number;
  warningCount: number;
}

export interface WorkspaceArtboard {
  pageId: PageId;
  name: string;
  label: string;
  layoutWidth: number;
  layoutHeight: number;
  workspaceRect: Rect;
  isActive: boolean;
  diagnosticsSummary: DiagnosticsSummary;
}

export interface WorkspaceModel {
  artboards: WorkspaceArtboard[];
  bounds: Rect;
  activeArtboard: WorkspaceArtboard | null;
}

export interface WorkspaceLayoutOptions {
  gap?: number;
  rowWidth?: number;
  labelPaddingTop?: number;
  boundsPadding?: number;
}

const DEFAULT_GAP = 180;
const DEFAULT_ROW_WIDTH = 2800;
const DEFAULT_LABEL_PADDING_TOP = 44;
const DEFAULT_BOUNDS_PADDING = 160;

export function createWorkspaceModel(
  scene: Scene,
  activePageId: PageId | null,
  diagnostics: Diagnostic[] = [],
  options: WorkspaceLayoutOptions = {}
): WorkspaceModel {
  const summaries = diagnosticsByPage(scene, diagnostics);
  const placements = layoutWorkspaceArtboards(
    listPages(scene).map((page) => {
      const descriptor = pageDescriptor(page);
      return {
        pageId: page.id,
        name: page.name,
        width: descriptor.width,
        height: descriptor.height
      };
    }),
    options
  );
  const artboards = placements.map((placement) => {
    const summary = summaries.get(placement.pageId) ?? { errorCount: 0, warningCount: 0 };
    return {
      pageId: placement.pageId,
      name: placement.name,
      label: placement.name,
      layoutWidth: placement.workspaceRect.width,
      layoutHeight: placement.workspaceRect.height,
      workspaceRect: placement.workspaceRect,
      isActive: placement.pageId === activePageId,
      diagnosticsSummary: summary
    };
  });

  return {
    artboards,
    bounds: workspaceBounds(
      artboards.map((artboard) => artboard.workspaceRect),
      {
        labelPaddingTop: options.labelPaddingTop,
        boundsPadding: options.boundsPadding
      }
    ),
    activeArtboard: artboards.find((artboard) => artboard.pageId === activePageId) ?? artboards[0] ?? null
  };
}

export function layoutWorkspaceArtboards(
  artboards: Array<{ pageId: PageId; name: string; width: number; height: number }>,
  options: WorkspaceLayoutOptions = {}
): Array<{ pageId: PageId; name: string; workspaceRect: Rect }> {
  const gap = positiveOrDefault(options.gap, DEFAULT_GAP);
  const rowWidth = positiveOrDefault(options.rowWidth, DEFAULT_ROW_WIDTH);
  const placed: Array<{ pageId: PageId; name: string; workspaceRect: Rect }> = [];
  let cursorX = 0;
  let cursorY = 0;
  let rowHeight = 0;

  for (const artboard of artboards) {
    const width = positiveOrDefault(artboard.width, 1);
    const height = positiveOrDefault(artboard.height, 1);
    const shouldWrap = placed.length > 0 && cursorX > 0 && cursorX + width > rowWidth;
    if (shouldWrap) {
      cursorX = 0;
      cursorY += rowHeight + gap;
      rowHeight = 0;
    }

    placed.push({
      pageId: artboard.pageId,
      name: artboard.name,
      workspaceRect: {
        x: cursorX,
        y: cursorY,
        width,
        height
      }
    });

    cursorX += width + gap;
    rowHeight = Math.max(rowHeight, height);
  }

  return placed;
}

export function workspaceBounds(
  rects: Rect[],
  options: Pick<WorkspaceLayoutOptions, "labelPaddingTop" | "boundsPadding"> = {}
): Rect {
  const boundsPadding = positiveOrDefault(options.boundsPadding, DEFAULT_BOUNDS_PADDING);
  const labelPaddingTop = positiveOrDefault(options.labelPaddingTop, DEFAULT_LABEL_PADDING_TOP);
  if (rects.length === 0) {
    return { x: -boundsPadding, y: -boundsPadding, width: boundsPadding * 2, height: boundsPadding * 2 };
  }

  const minX = Math.min(...rects.map((rect) => rect.x));
  const minY = Math.min(...rects.map((rect) => rect.y));
  const maxX = Math.max(...rects.map((rect) => rect.x + rect.width));
  const maxY = Math.max(...rects.map((rect) => rect.y + rect.height));
  return {
    x: minX - boundsPadding,
    y: minY - labelPaddingTop - boundsPadding,
    width: maxX - minX + boundsPadding * 2,
    height: maxY - minY + labelPaddingTop + boundsPadding * 2
  };
}

export function artboardAtWorkspacePoint(model: WorkspaceModel, point: Point): WorkspaceArtboard | null {
  return (
    model.artboards.find((artboard) => pointInRect(point, artboard.workspaceRect)) ??
    null
  );
}

export function workspacePointToArtboardLocal(artboard: WorkspaceArtboard, point: Point): Point {
  return {
    x: point.x - artboard.workspaceRect.x,
    y: point.y - artboard.workspaceRect.y
  };
}

export function artboardLocalPointToWorkspace(artboard: WorkspaceArtboard, point: Point): Point {
  return {
    x: artboard.workspaceRect.x + point.x,
    y: artboard.workspaceRect.y + point.y
  };
}

export function artboardLocalRectToWorkspace(artboard: WorkspaceArtboard, rect: Rect): Rect {
  return {
    x: artboard.workspaceRect.x + rect.x,
    y: artboard.workspaceRect.y + rect.y,
    width: rect.width,
    height: rect.height
  };
}

export function pointInRect(point: Point, rect: Rect): boolean {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  );
}

function diagnosticsByPage(scene: Scene, diagnostics: Diagnostic[]): Map<PageId, DiagnosticsSummary> {
  const byPage = new Map<PageId, DiagnosticsSummary>();
  for (const diagnostic of diagnostics) {
    const pageId = pageIdForDiagnostic(scene, diagnostic);
    if (!pageId) {
      continue;
    }
    const summary = byPage.get(pageId) ?? { errorCount: 0, warningCount: 0 };
    if (diagnostic.severity === "error") {
      summary.errorCount += 1;
    } else if (diagnostic.severity === "warning") {
      summary.warningCount += 1;
    }
    byPage.set(pageId, summary);
  }
  return byPage;
}

function pageIdForDiagnostic(scene: Scene, diagnostic: Diagnostic): PageId | null {
  const subject = diagnostic.subject;
  if (!subject) {
    return null;
  }
  switch (subject.kind) {
    case "page":
      return scene.pages[subject.id] ? subject.id : null;
    case "node":
      return pageIdForNode(scene, subject.id);
    case "slot": {
      const slot = scene.slots[subject.id];
      const nodeId = slot?.bound_nodes.find((id) => Boolean(scene.nodes[id])) ?? null;
      return nodeId ? pageIdForNode(scene, nodeId) : null;
    }
    case "asset": {
      const nodeId = nodeIdForAsset(scene, subject.id);
      return nodeId ? pageIdForNode(scene, nodeId) : null;
    }
    case "document":
      return null;
  }
}

function positiveOrDefault(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}
