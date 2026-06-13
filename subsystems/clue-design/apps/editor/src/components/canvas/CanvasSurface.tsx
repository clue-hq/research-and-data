"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Maximize2, Minus, MousePointer2, Plus } from "lucide-react";
import { Layer, Line, Rect, Stage, Transformer } from "react-konva";
import type Konva from "konva";
import type { NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import { canvasDirectEditNotice, isCanvasDirectGeometryEditable } from "@/engine/canvasSelection";
import { centeredPageOrigin, clampCanvasPan, clampCanvasZoom, fitZoomForPage, type CanvasPan } from "@/engine/canvasViewport";
import { getPage } from "@/engine/sceneQueries";
import { pageDescriptor } from "@/engine/renderAdapter";
import { SceneNode } from "./SceneNode";
import { ContainerSelectionOverlay } from "./ContainerSelectionOverlay";

interface CanvasSurfaceProps {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId | null) => void;
  onOperation: (operation: Operation) => void;
}

export function CanvasSurface({
  scene,
  activePageId,
  selectedNodeId,
  onSelectNode,
  onOperation
}: CanvasSurfaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const transformerRef = useRef<Konva.Transformer | null>(null);
  const nodeRefs = useRef(new Map<NodeId, Konva.Node>());
  const [viewport, setViewport] = useState({ width: 900, height: 720 });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<CanvasPan>({ x: 0, y: 0 });
  const [autoFit, setAutoFit] = useState(true);
  const page = getPage(scene, activePageId);
  const descriptor = page ? pageDescriptor(page) : null;
  const selectedNodeDirectGeometryEditable = isCanvasDirectGeometryEditable(scene, selectedNodeId);
  const selectedEditNotice = canvasDirectEditNotice(scene, selectedNodeId);
  const fitZoom = useMemo(() => {
    if (!descriptor) {
      return 1;
    }
    return fitZoomForPage({
      viewportWidth: viewport.width,
      viewportHeight: viewport.height,
      pageWidth: descriptor.width,
      pageHeight: descriptor.height
    });
  }, [descriptor, viewport.height, viewport.width]);
  const basePageOrigin = useMemo(() => {
    if (!descriptor) {
      return { x: 0, y: 0 };
    }
    return centeredPageOrigin({
      viewportWidth: viewport.width,
      viewportHeight: viewport.height,
      pageWidth: descriptor.width,
      pageHeight: descriptor.height,
      zoom
    });
  }, [descriptor, viewport.height, viewport.width, zoom]);
  const clampPanForViewport = useCallback(
    (nextPan: CanvasPan, nextZoom = zoom): CanvasPan => {
      if (!descriptor) {
        return { x: 0, y: 0 };
      }
      const baseOrigin = centeredPageOrigin({
        viewportWidth: viewport.width,
        viewportHeight: viewport.height,
        pageWidth: descriptor.width,
        pageHeight: descriptor.height,
        zoom: nextZoom
      });
      return clampCanvasPan({
        viewportWidth: viewport.width,
        viewportHeight: viewport.height,
        pageWidth: descriptor.width,
        pageHeight: descriptor.height,
        zoom: nextZoom,
        baseOrigin,
        pan: nextPan
      });
    },
    [descriptor, viewport.height, viewport.width, zoom]
  );
  const pageOrigin = useMemo(
    () => ({
      x: basePageOrigin.x + pan.x,
      y: basePageOrigin.y + pan.y
    }),
    [basePageOrigin.x, basePageOrigin.y, pan.x, pan.y]
  );

  useEffect(() => {
    setAutoFit(true);
  }, [activePageId, descriptor?.height, descriptor?.width]);

  useEffect(() => {
    if (autoFit) {
      setZoom(fitZoom);
      setPan({ x: 0, y: 0 });
    }
  }, [autoFit, fitZoom]);

  useEffect(() => {
    setPan((currentPan) => (autoFit ? { x: 0, y: 0 } : clampPanForViewport(currentPan)));
  }, [autoFit, clampPanForViewport]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      setViewport({
        width: Math.max(560, entry.contentRect.width),
        height: Math.max(520, entry.contentRect.height)
      });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const transformer = transformerRef.current;
    if (!transformer) {
      return;
    }
    const selected =
      selectedNodeDirectGeometryEditable && selectedNodeId ? nodeRefs.current.get(selectedNodeId) : null;
    transformer.nodes(selected ? [selected] : []);
    transformer.getLayer()?.batchDraw();
  }, [selectedNodeDirectGeometryEditable, selectedNodeId, scene]);

  const registerNode = (nodeId: NodeId, node: Konva.Node | null) => {
    if (node) {
      nodeRefs.current.set(nodeId, node);
    } else {
      nodeRefs.current.delete(nodeId);
    }
  };

  const zoomBy = (delta: number) => {
    setAutoFit(false);
    setZoom((value) => clampCanvasZoom(value + delta));
  };

  const panBy = (screenDeltaX: number, screenDeltaY: number) => {
    setAutoFit(false);
    setPan((currentPan) =>
      clampPanForViewport({
        x: currentPan.x + screenDeltaX / zoom,
        y: currentPan.y + screenDeltaY / zoom
      })
    );
  };

  if (!page || !descriptor) {
    return (
      <section className="canvas-shell" ref={containerRef}>
        <div className="empty-state">No page selected.</div>
      </section>
    );
  }

  return (
    <section className="canvas-shell" ref={containerRef}>
      <div className="canvas-toolbar" aria-label="Canvas tools">
        <span>
          <MousePointer2 aria-hidden size={15} />
          Select
        </span>
        <button
          type="button"
          onClick={() => {
            zoomBy(-0.1);
          }}
        >
          <Minus aria-hidden size={14} />
          Zoom
        </button>
        <strong>{Math.round(zoom * 100)}%</strong>
        <button
          type="button"
          onClick={() => {
            zoomBy(0.1);
          }}
        >
          <Plus aria-hidden size={14} />
          Zoom
        </button>
        <button
          type="button"
          className={autoFit ? "active" : undefined}
          onClick={() => {
            setAutoFit(true);
            setZoom(fitZoom);
          }}
        >
          <Maximize2 aria-hidden size={14} />
          Fit
        </button>
        <span className="canvas-pan-controls" aria-label="Pan controls">
          <button type="button" aria-label="Pan left" onClick={() => panBy(96, 0)}>
            <ArrowLeft aria-hidden size={13} />
          </button>
          <button type="button" aria-label="Pan up" onClick={() => panBy(0, 96)}>
            <ArrowUp aria-hidden size={13} />
          </button>
          <button type="button" aria-label="Pan down" onClick={() => panBy(0, -96)}>
            <ArrowDown aria-hidden size={13} />
          </button>
          <button type="button" aria-label="Pan right" onClick={() => panBy(-96, 0)}>
            <ArrowRight aria-hidden size={13} />
          </button>
        </span>
      </div>
      {selectedEditNotice ? <p className="canvas-selection-notice">{selectedEditNotice}</p> : null}
      <Stage
        width={viewport.width}
        height={viewport.height}
        scaleX={zoom}
        scaleY={zoom}
        onWheel={(event) => {
          event.evt.preventDefault();
          setAutoFit(false);
          if (event.evt.ctrlKey || event.evt.metaKey) {
            const delta = event.evt.deltaY > 0 ? -0.08 : 0.08;
            setZoom((value) => clampCanvasZoom(value + delta));
            return;
          }
          setPan((currentPan) =>
            clampPanForViewport({
              x: currentPan.x - event.evt.deltaX / zoom,
              y: currentPan.y - event.evt.deltaY / zoom
            })
          );
        }}
        onMouseDown={(event) => {
          if (event.target === event.target.getStage()) {
            onSelectNode(null);
          }
        }}
      >
        <Layer>
          <Rect
            x={pageOrigin.x - 18}
            y={pageOrigin.y - 18}
            width={descriptor.width + 36}
            height={descriptor.height + 36}
            fill="#e2d8c9"
            cornerRadius={10}
            shadowColor="#000000"
            shadowBlur={18}
            shadowOpacity={0.12}
            shadowOffsetY={8}
          />
          <Rect
            x={pageOrigin.x}
            y={pageOrigin.y}
            width={descriptor.width}
            height={descriptor.height}
            fill={descriptor.background}
            stroke="#c8bda9"
            strokeWidth={1}
            onMouseDown={(event) => {
              event.cancelBubble = true;
              onSelectNode(null);
            }}
            onTap={(event) => {
              event.cancelBubble = true;
              onSelectNode(null);
            }}
          />
          {page.bleed ? (
            <Rect
              x={pageOrigin.x + page.bleed.x * descriptor.unitScale}
              y={pageOrigin.y + page.bleed.y * descriptor.unitScale}
              width={page.bleed.width * descriptor.unitScale}
              height={page.bleed.height * descriptor.unitScale}
              dash={[9, 5]}
              stroke="#b45d4f"
              strokeWidth={1}
              opacity={0.5}
              listening={false}
            />
          ) : null}
          {page.safe_area ? (
            <Rect
              x={pageOrigin.x + page.safe_area.x * descriptor.unitScale}
              y={pageOrigin.y + page.safe_area.y * descriptor.unitScale}
              width={page.safe_area.width * descriptor.unitScale}
              height={page.safe_area.height * descriptor.unitScale}
              dash={[7, 5]}
              stroke="#5a8f93"
              strokeWidth={1}
              opacity={0.45}
              listening={false}
            />
          ) : null}
          <Line
            points={[
              pageOrigin.x + descriptor.width / 2,
              pageOrigin.y,
              pageOrigin.x + descriptor.width / 2,
              pageOrigin.y + descriptor.height
            ]}
            dash={[5, 8]}
            stroke="#2f5f78"
            strokeWidth={1}
            opacity={0.18}
            listening={false}
          />
          <Line
            points={[
              pageOrigin.x,
              pageOrigin.y + descriptor.height / 2,
              pageOrigin.x + descriptor.width,
              pageOrigin.y + descriptor.height / 2
            ]}
            dash={[5, 8]}
            stroke="#2f5f78"
            strokeWidth={1}
            opacity={0.18}
            listening={false}
          />
          {page.children.map((nodeId) => (
            <SceneNode
              key={nodeId}
              scene={scene}
              page={page}
              nodeId={nodeId}
              pageOrigin={pageOrigin}
              selectedNodeId={selectedNodeId}
              onSelectNode={onSelectNode}
              onOperation={onOperation}
              registerNode={registerNode}
            />
          ))}
          <ContainerSelectionOverlay
            scene={scene}
            selectedNodeId={selectedNodeId}
            pageOrigin={pageOrigin}
            unitScale={descriptor.unitScale}
          />
          <Transformer
            ref={transformerRef}
            visible={selectedNodeDirectGeometryEditable}
            rotateEnabled={selectedNodeDirectGeometryEditable}
            resizeEnabled={selectedNodeDirectGeometryEditable}
            flipEnabled={false}
            enabledAnchors={["top-left", "top-right", "bottom-left", "bottom-right", "middle-left", "middle-right"]}
            anchorFill="#f8f4ec"
            anchorStroke="#256c70"
            borderStroke="#256c70"
            ignoreStroke
          />
        </Layer>
      </Stage>
    </section>
  );
}
