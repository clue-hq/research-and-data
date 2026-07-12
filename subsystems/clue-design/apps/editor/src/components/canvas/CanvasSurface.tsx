"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Hand,
  LocateFixed,
  Maximize2,
  Minus,
  MousePointer2,
  Plus,
  Download,
  Scan
} from "lucide-react";
import { Group, Layer, Line, Rect, Stage, Text, Transformer } from "react-konva";
import type Konva from "konva";
import type { NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import { canvasDirectEditNotice, isCanvasDirectGeometryEditable } from "@/engine/canvasSelection";
import { SNAP_GUIDE_COLOR, SNAP_GUIDE_DASH, type SnapGuide } from "@/engine/canvasOperations";
import { getPage } from "@/engine/sceneQueries";
import { pageDescriptor } from "@/engine/renderAdapter";
import type { WorkspaceArtboard, WorkspaceModel } from "@/engine/workspaceLayout";
import {
  clampWorkspacePanToKeepVisible,
  clampWorkspaceZoom,
  fitWorkspaceRectToViewport,
  panWorkspaceViewport,
  zoomWorkspaceViewportAtPoint,
  type WorkspaceFitTarget,
  type WorkspaceTool,
  type WorkspaceViewport
} from "@/engine/workspaceViewport";
import type { WorkspaceViewportUpdater } from "./EditorCanvas";
import { SceneNode } from "./SceneNode";
import { ContainerSelectionOverlay } from "./ContainerSelectionOverlay";

interface CanvasSurfaceProps {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId | null) => void;
  onSelectPage?: (pageId: PageId) => void;
  onOperation: (operation: Operation) => void;
  workspaceModel: WorkspaceModel;
  workspaceViewport: WorkspaceViewport;
  onWorkspaceViewportChange: WorkspaceViewportUpdater;
  workspaceTool: WorkspaceTool;
  onWorkspaceToolChange: (tool: WorkspaceTool) => void;
  workspaceFitTarget: WorkspaceFitTarget;
  onWorkspaceFitTargetChange: (target: WorkspaceFitTarget) => void;
  onOpenDiagnostics?: () => void;
  onOpenExport?: () => void;
}

const EMPTY_VIEWPORT = { width: 900, height: 720 };

export function CanvasSurface({
  scene,
  activePageId,
  selectedNodeId,
  onSelectNode,
  onSelectPage,
  onOperation,
  workspaceModel,
  workspaceViewport,
  onWorkspaceViewportChange,
  workspaceTool,
  onWorkspaceToolChange,
  workspaceFitTarget,
  onWorkspaceFitTargetChange,
  onOpenDiagnostics,
  onOpenExport
}: CanvasSurfaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const transformerRef = useRef<Konva.Transformer | null>(null);
  const nodeRefs = useRef(new Map<NodeId, Konva.Node>());
  const dragStartRef = useRef<{ x: number; y: number; pan: { x: number; y: number } } | null>(null);
  const [viewportSize, setViewportSize] = useState(EMPTY_VIEWPORT);
  const [activeGuides, setActiveGuides] = useState<SnapGuide[]>([]);
  const selectedNodeDirectGeometryEditable = isCanvasDirectGeometryEditable(scene, selectedNodeId);
  const selectedEditNotice = canvasDirectEditNotice(scene, selectedNodeId);
  const activeArtboard = workspaceModel.activeArtboard;
  const activePage = getPage(scene, activePageId);
  const activeDescriptor = activePage ? pageDescriptor(activePage) : null;

  const fitRect = useMemo(() => {
    if (workspaceFitTarget === "current" && activeArtboard) {
      return activeArtboard.workspaceRect;
    }
    return workspaceModel.bounds;
  }, [activeArtboard, workspaceFitTarget, workspaceModel.bounds]);

  const fitWorkspace = useCallback(
    (target: Exclude<WorkspaceFitTarget, "manual">) => {
      const rect = target === "current" && activeArtboard ? activeArtboard.workspaceRect : workspaceModel.bounds;
      onWorkspaceFitTargetChange(target);
      onWorkspaceViewportChange(fitWorkspaceRectToViewport({ viewport: viewportSize, rect }));
    },
    [activeArtboard, onWorkspaceFitTargetChange, onWorkspaceViewportChange, viewportSize, workspaceModel.bounds]
  );

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      setViewportSize({
        width: Math.max(560, entry.contentRect.width),
        height: Math.max(520, entry.contentRect.height)
      });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (workspaceFitTarget === "manual") {
      return;
    }
    onWorkspaceViewportChange(fitWorkspaceRectToViewport({ viewport: viewportSize, rect: fitRect }));
  }, [fitRect, onWorkspaceViewportChange, viewportSize, workspaceFitTarget]);

  useEffect(() => {
    onWorkspaceViewportChange((current) =>
      clampWorkspacePanToKeepVisible(current, workspaceModel.bounds, viewportSize)
    );
  }, [onWorkspaceViewportChange, viewportSize, workspaceModel.bounds]);

  useEffect(() => {
    const transformer = transformerRef.current;
    if (!transformer) {
      return;
    }
    const selected =
      selectedNodeDirectGeometryEditable && selectedNodeId ? nodeRefs.current.get(selectedNodeId) : null;
    transformer.nodes(selected ? [selected] : []);
    transformer.getLayer()?.batchDraw();
  }, [selectedNodeDirectGeometryEditable, selectedNodeId, scene, workspaceModel]);

  const registerNode = (nodeId: NodeId, node: Konva.Node | null) => {
    if (node) {
      nodeRefs.current.set(nodeId, node);
    } else {
      nodeRefs.current.delete(nodeId);
    }
  };

  const activateArtboard = (pageId: PageId, nextSelectedNodeId: NodeId | null = null) => {
    onSelectPage?.(pageId);
    onSelectNode(nextSelectedNodeId);
  };

  const zoomBy = (delta: number) => {
    onWorkspaceFitTargetChange("manual");
    const center = { x: viewportSize.width / 2, y: viewportSize.height / 2 };
    onWorkspaceViewportChange((current) =>
      zoomWorkspaceViewportAtPoint(current, center, clampWorkspaceZoom(current.zoom + delta))
    );
  };

  const panBy = (screenDeltaX: number, screenDeltaY: number) => {
    onWorkspaceFitTargetChange("manual");
    onWorkspaceViewportChange((current) =>
      clampWorkspacePanToKeepVisible(
        panWorkspaceViewport(current, { x: screenDeltaX, y: screenDeltaY }),
        workspaceModel.bounds,
        viewportSize
      )
    );
  };

  if (workspaceModel.artboards.length === 0) {
    return (
      <section className="canvas-shell workspace-canvas-shell" ref={containerRef}>
        <div className="empty-state">No artboard selected.</div>
      </section>
    );
  }

  return (
    <section className="canvas-shell workspace-canvas-shell" ref={containerRef}>
      <WorkspaceChrome
        activeArtboard={activeArtboard}
        activeDescriptor={activeDescriptor}
        fitTarget={workspaceFitTarget}
        tool={workspaceTool}
        zoom={workspaceViewport.zoom}
        onToolChange={onWorkspaceToolChange}
        onZoomOut={() => zoomBy(-0.1)}
        onZoomIn={() => zoomBy(0.1)}
        onFitCurrent={() => fitWorkspace("current")}
        onFitAll={() => fitWorkspace("all")}
        onOpenDiagnostics={onOpenDiagnostics}
        onOpenExport={onOpenExport}
      />
      {selectedEditNotice ? <p className="canvas-selection-notice">{selectedEditNotice}</p> : null}
      <Stage
        width={viewportSize.width}
        height={viewportSize.height}
        x={workspaceViewport.pan.x}
        y={workspaceViewport.pan.y}
        scaleX={workspaceViewport.zoom}
        scaleY={workspaceViewport.zoom}
        draggable={workspaceTool === "hand"}
        onDragStart={(event) => {
          if (workspaceTool !== "hand") {
            return;
          }
          dragStartRef.current = {
            x: event.target.x(),
            y: event.target.y(),
            pan: workspaceViewport.pan
          };
        }}
        onDragEnd={(event) => {
          if (workspaceTool !== "hand") {
            return;
          }
          const start = dragStartRef.current;
          dragStartRef.current = null;
          onWorkspaceFitTargetChange("manual");
          const nextPan = start
            ? {
                x: start.pan.x + event.target.x() - start.x,
                y: start.pan.y + event.target.y() - start.y
              }
            : { x: event.target.x(), y: event.target.y() };
          event.target.position(workspaceViewport.pan);
          onWorkspaceViewportChange((current) =>
            clampWorkspacePanToKeepVisible({ ...current, pan: nextPan }, workspaceModel.bounds, viewportSize)
          );
        }}
        onWheel={(event) => {
          event.evt.preventDefault();
          onWorkspaceFitTargetChange("manual");
          if (event.evt.ctrlKey || event.evt.metaKey) {
            const delta = event.evt.deltaY > 0 ? -0.08 : 0.08;
            const pointer = {
              x: event.evt.offsetX,
              y: event.evt.offsetY
            };
            onWorkspaceViewportChange((current) =>
              zoomWorkspaceViewportAtPoint(current, pointer, current.zoom + delta)
            );
            return;
          }
          onWorkspaceViewportChange((current) =>
            clampWorkspacePanToKeepVisible(
              panWorkspaceViewport(current, { x: -event.evt.deltaX, y: -event.evt.deltaY }),
              workspaceModel.bounds,
              viewportSize
            )
          );
        }}
        onMouseDown={(event) => {
          if (workspaceTool !== "select") {
            return;
          }
          if (event.target === event.target.getStage()) {
            onSelectNode(null);
          }
        }}
      >
        <Layer>
          <WorkspaceBackdrop model={workspaceModel} viewport={workspaceViewport} viewportSize={viewportSize} />
          {workspaceModel.artboards.map((artboard) => (
            <ArtboardFrame
              key={artboard.pageId}
              artboard={artboard}
              scene={scene}
              selectedNodeId={selectedNodeId}
              onSelectNode={(nodeId) => activateArtboard(artboard.pageId, nodeId)}
              onSelectArtboard={() => activateArtboard(artboard.pageId, null)}
              onOperation={onOperation}
              registerNode={registerNode}
              activeGuides={artboard.isActive ? activeGuides : []}
              onGuidesChange={setActiveGuides}
            />
          ))}
          <Transformer
            ref={transformerRef}
            visible={selectedNodeDirectGeometryEditable}
            rotateEnabled={selectedNodeDirectGeometryEditable}
            resizeEnabled={selectedNodeDirectGeometryEditable}
            flipEnabled={false}
            enabledAnchors={["top-left", "top-right", "bottom-left", "bottom-right", "middle-left", "middle-right"]}
            anchorFill="#f8f4ec"
            anchorStroke="#58c4c8"
            borderStroke="#58c4c8"
            ignoreStroke
          />
        </Layer>
      </Stage>
    </section>
  );
}

function ArtboardFrame({
  artboard,
  scene,
  selectedNodeId,
  onSelectNode,
  onSelectArtboard,
  onOperation,
  registerNode,
  activeGuides,
  onGuidesChange
}: {
  artboard: WorkspaceArtboard;
  scene: Scene;
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId) => void;
  onSelectArtboard: () => void;
  onOperation: (operation: Operation) => void;
  registerNode: (nodeId: NodeId, node: Konva.Node | null) => void;
  activeGuides: SnapGuide[];
  onGuidesChange: (guides: SnapGuide[]) => void;
}) {
  const page = scene.pages[artboard.pageId];
  if (!page) {
    return null;
  }
  const descriptor = pageDescriptor(page);
  const diagnostics = artboard.diagnosticsSummary;
  const statusFill = diagnostics.errorCount > 0 ? "#ef5f5f" : diagnostics.warningCount > 0 ? "#f5b84b" : "#63c174";
  const statusText =
    diagnostics.errorCount > 0
      ? `${diagnostics.errorCount} error${diagnostics.errorCount === 1 ? "" : "s"}`
      : diagnostics.warningCount > 0
        ? `${diagnostics.warningCount} warning${diagnostics.warningCount === 1 ? "" : "s"}`
        : "Ready";

  return (
    <Group x={artboard.workspaceRect.x} y={artboard.workspaceRect.y}>
      <Text
        x={0}
        y={-30}
        text={artboard.label}
        fill={artboard.isActive ? "#ffffff" : "#c8d0d8"}
        fontSize={13}
        fontStyle="700"
        listening={false}
      />
      <Group x={Math.max(0, descriptor.width - 104)} y={-33} listening={false}>
        <Rect width={104} height={21} fill="#20252c" opacity={0.92} cornerRadius={5} />
        <Rect x={8} y={7} width={7} height={7} fill={statusFill} cornerRadius={3.5} />
        <Text x={20} y={4} width={76} height={14} text={statusText} fill="#dce4ea" fontSize={10} />
      </Group>
      <Rect
        x={-18}
        y={-18}
        width={descriptor.width + 36}
        height={descriptor.height + 36}
        fill="#151920"
        cornerRadius={10}
        shadowColor="#000000"
        shadowBlur={26}
        shadowOpacity={0.28}
        shadowOffsetY={12}
        listening={false}
      />
      <Rect
        width={descriptor.width}
        height={descriptor.height}
        fill={descriptor.background}
        stroke={artboard.isActive ? "#58c4c8" : "#858f99"}
        strokeWidth={artboard.isActive ? 2 : 1}
        onMouseDown={(event) => {
          event.cancelBubble = true;
          onSelectArtboard();
        }}
        onTap={(event) => {
          event.cancelBubble = true;
          onSelectArtboard();
        }}
      />
      {page.bleed ? (
        <Rect
          x={page.bleed.x * descriptor.unitScale}
          y={page.bleed.y * descriptor.unitScale}
          width={page.bleed.width * descriptor.unitScale}
          height={page.bleed.height * descriptor.unitScale}
          dash={[9, 5]}
          stroke="#d56b61"
          strokeWidth={1}
          opacity={0.55}
          listening={false}
        />
      ) : null}
      {page.safe_area ? (
        <Rect
          x={page.safe_area.x * descriptor.unitScale}
          y={page.safe_area.y * descriptor.unitScale}
          width={page.safe_area.width * descriptor.unitScale}
          height={page.safe_area.height * descriptor.unitScale}
          dash={[7, 5]}
          stroke="#58c4c8"
          strokeWidth={1}
          opacity={0.5}
          listening={false}
        />
      ) : null}
      <Line
        points={[descriptor.width / 2, 0, descriptor.width / 2, descriptor.height]}
        dash={[5, 8]}
        stroke="#58c4c8"
        strokeWidth={1}
        opacity={0.16}
        listening={false}
      />
      <Line
        points={[0, descriptor.height / 2, descriptor.width, descriptor.height / 2]}
        dash={[5, 8]}
        stroke="#58c4c8"
        strokeWidth={1}
        opacity={0.16}
        listening={false}
      />
      <Group clipX={0} clipY={0} clipWidth={descriptor.width} clipHeight={descriptor.height}>
        {page.children.map((nodeId) => (
          <SceneNode
            key={nodeId}
            scene={scene}
            page={page}
            nodeId={nodeId}
            pageOrigin={{ x: 0, y: 0 }}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
            onOperation={onOperation}
            registerNode={registerNode}
            onGuidesChange={onGuidesChange}
          />
        ))}
        <ContainerSelectionOverlay
          scene={scene}
          selectedNodeId={selectedNodeId}
          pageOrigin={{ x: 0, y: 0 }}
          unitScale={descriptor.unitScale}
        />
        <SnapGuideLayer guides={activeGuides} unitScale={descriptor.unitScale} />
      </Group>
    </Group>
  );
}

/**
 * Renders the currently-engaged snap guides as 1px lines in the artboard's
 * local (page-space × unitScale) coordinates — same placement convention as
 * `ContainerSelectionOverlay`. Purely presentational; empty while no drag/
 * resize is snapped. Exported for direct component-level testing (Konva
 * can't mount for real in this project's jsdom suite, so tests render this
 * through the mocked `react-konva` boundary, same as the rest of the file).
 */
export function SnapGuideLayer({ guides, unitScale }: { guides: SnapGuide[]; unitScale: number }) {
  if (guides.length === 0) {
    return null;
  }
  return (
    <Group listening={false} name="snap-guide-layer">
      {guides.map((guide, index) => {
        const points =
          guide.axis === "x"
            ? [guide.position * unitScale, guide.from * unitScale, guide.position * unitScale, guide.to * unitScale]
            : [guide.from * unitScale, guide.position * unitScale, guide.to * unitScale, guide.position * unitScale];
        return (
          <Line
            key={`guide-${guide.axis}-${index}`}
            name="snap-guide"
            points={points}
            stroke={SNAP_GUIDE_COLOR}
            strokeWidth={1}
            dash={SNAP_GUIDE_DASH}
            listening={false}
          />
        );
      })}
    </Group>
  );
}

function WorkspaceBackdrop({
  model,
  viewport,
  viewportSize
}: {
  model: WorkspaceModel;
  viewport: WorkspaceViewport;
  viewportSize: { width: number; height: number };
}) {
  return (
    <Group listening={false}>
      <Rect
        x={(0 - viewport.pan.x) / viewport.zoom}
        y={(0 - viewport.pan.y) / viewport.zoom}
        width={viewportSize.width / viewport.zoom}
        height={viewportSize.height / viewport.zoom}
        fill="#f5f5f5"
      />
      <Rect
        x={model.bounds.x}
        y={model.bounds.y}
        width={model.bounds.width}
        height={model.bounds.height}
        fill="#343942"
        opacity={0.45}
        cornerRadius={18}
      />
      <Text
        x={model.bounds.x}
        y={model.bounds.y - 28}
        text={`${model.artboards.length} frame${model.artboards.length === 1 ? "" : "s"} on workspace`}
        fill="#9faab5"
        fontSize={12}
      />
    </Group>
  );
}

function WorkspaceChrome({
  activeArtboard,
  activeDescriptor,
  fitTarget,
  tool,
  zoom,
  onToolChange,
  onZoomOut,
  onZoomIn,
  onFitCurrent,
  onFitAll,
  onOpenDiagnostics,
  onOpenExport
}: {
  activeArtboard: WorkspaceArtboard | null;
  activeDescriptor: ReturnType<typeof pageDescriptor> | null;
  fitTarget: WorkspaceFitTarget;
  tool: WorkspaceTool;
  zoom: number;
  onToolChange: (tool: WorkspaceTool) => void;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onFitCurrent: () => void;
  onFitAll: () => void;
  onOpenDiagnostics?: () => void;
  onOpenExport?: () => void;
}) {
  const sizeLabel = activeDescriptor
    ? `${formatDimension(activeDescriptor.width)} x ${formatDimension(activeDescriptor.height)} pt`
    : "No frame";
  return (
    <>
      <div className="workspace-context-bar">
        <span className="workspace-context-label">{activeArtboard?.label ?? "No artboard"}</span>
        <span>{sizeLabel}</span>
      </div>
      <div className="workspace-bottom-toolbar" aria-label="Workspace tools">
        <button
          type="button"
          className={tool === "select" ? "active" : undefined}
          aria-label="Select tool"
          aria-pressed={tool === "select"}
          title="Select tool"
          onClick={() => onToolChange("select")}
        >
          <MousePointer2 aria-hidden size={16} />
        </button>
        <button
          type="button"
          className={tool === "hand" ? "active" : undefined}
          aria-label="Pan tool"
          aria-pressed={tool === "hand"}
          title="Pan tool"
          onClick={() => onToolChange("hand")}
        >
          <Hand aria-hidden size={16} />
        </button>
        <span className="workspace-toolbar-separator" />
        <button type="button" aria-label="Zoom out" title="Zoom out" onClick={onZoomOut}>
          <Minus aria-hidden size={16} />
        </button>
        <strong>{Math.round(zoom * 100)}%</strong>
        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={onZoomIn}>
          <Plus aria-hidden size={16} />
        </button>
        <span className="workspace-toolbar-separator" />
        <button
          type="button"
          className={fitTarget === "current" ? "active" : undefined}
          aria-label="Fit current artboard"
          aria-pressed={fitTarget === "current"}
          title="Fit current artboard"
          onClick={onFitCurrent}
        >
          <LocateFixed aria-hidden size={16} />
        </button>
        <button
          type="button"
          className={fitTarget === "all" ? "active" : undefined}
          aria-label="Fit all artboards"
          aria-pressed={fitTarget === "all"}
          title="Fit all artboards"
          onClick={onFitAll}
        >
          <Maximize2 aria-hidden size={16} />
        </button>
        <button type="button" aria-label="Open diagnostics panel" title="Open diagnostics panel" onClick={onOpenDiagnostics}>
          <Scan aria-hidden size={16} />
        </button>
        <button type="button" aria-label="Open export panel" title="Open export panel" onClick={onOpenExport}>
          <Download aria-hidden size={16} />
        </button>
      </div>
    </>
  );
}

function formatDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}
