"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Minus, MousePointer2, Plus } from "lucide-react";
import { Layer, Rect, Stage, Transformer } from "react-konva";
import type Konva from "konva";
import type { NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import { getPage } from "@/engine/sceneQueries";
import { pageDescriptor } from "@/engine/renderAdapter";
import { SceneNode } from "./SceneNode";

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
  const [zoom, setZoom] = useState(0.9);
  const page = getPage(scene, activePageId);
  const descriptor = page ? pageDescriptor(page) : null;
  const pageOrigin = useMemo(() => {
    if (!descriptor) {
      return { x: 0, y: 0 };
    }
    return {
      x: Math.max(32, (viewport.width - descriptor.width * zoom) / 2 / zoom),
      y: 40
    };
  }, [descriptor, viewport.width, zoom]);

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
    const selected = selectedNodeId ? nodeRefs.current.get(selectedNodeId) : null;
    transformer.nodes(selected ? [selected] : []);
    transformer.getLayer()?.batchDraw();
  }, [selectedNodeId, scene]);

  const registerNode = (nodeId: NodeId, node: Konva.Node | null) => {
    if (node) {
      nodeRefs.current.set(nodeId, node);
    } else {
      nodeRefs.current.delete(nodeId);
    }
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
        <button type="button" onClick={() => setZoom((value) => Math.max(0.4, value - 0.1))}>
          <Minus aria-hidden size={14} />
          Zoom
        </button>
        <strong>{Math.round(zoom * 100)}%</strong>
        <button type="button" onClick={() => setZoom((value) => Math.min(2, value + 0.1))}>
          <Plus aria-hidden size={14} />
          Zoom
        </button>
      </div>
      <Stage
        width={viewport.width}
        height={viewport.height}
        scaleX={zoom}
        scaleY={zoom}
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
          />
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
          <Transformer
            ref={transformerRef}
            rotateEnabled
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
