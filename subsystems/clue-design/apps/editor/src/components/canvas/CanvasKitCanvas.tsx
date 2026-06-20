"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, Hand, LocateFixed, Maximize2, Minus, MousePointer2, Plus, Scan } from "lucide-react";
import type { Diagnostic, NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";
import { artboardAtWorkspacePoint, type WorkspaceModel } from "@/engine/workspaceLayout";
import { containerSelectionGeometry } from "@/engine/canvasSelection";
import { deriveSelectionChromeModel } from "@/engine/selectionChrome";
import {
  gestureReducer,
  initialGestureState,
  marqueeSelection,
  type GestureAction,
  type GestureState,
  type PressTarget
} from "@/engine/gestureMachine";
import {
  descriptorToScene,
  dragActionToOperation,
  handleAtPoint,
  resizeActionToOperation,
  screenToDescriptor
} from "@/engine/canvaskitGestures";
import { getNode, getPage, nodeDisplayName, topLevelAncestorId } from "@/engine/sceneQueries";
import { nodeDescriptor, pageDescriptor, type ParentComputedOrigin } from "@/engine/renderAdapter";
import { loadCanvasKit } from "@/engine/canvaskit/loadCanvasKit";
import { skiaMeasurements } from "@/engine/canvaskit/skiaMeasurements";
import type { Box } from "@/engine/transformerMath";
import { nodePatch, set, updateTextNode } from "@/engine/operations";
import {
  clampWorkspacePanToKeepVisible,
  clampWorkspaceZoom,
  fitWorkspaceRectToViewport,
  panWorkspaceViewport,
  screenToWorkspace,
  zoomWorkspaceViewportAtPoint,
  type WorkspaceFitTarget,
  type WorkspaceTool,
  type WorkspaceViewport
} from "@/engine/workspaceViewport";
import type { WorkspaceViewportUpdater } from "./EditorCanvas";
import { CanvasKitStage } from "./CanvasKitStage";
import { SelectionOverlay } from "./SelectionOverlay";
import { TextEditOverlay } from "./TextEditOverlay";
import type { DrawNode } from "@/engine/canvaskit/drawDescriptors";

/**
 * Wave 3 C3 host: the CanvasKit editor canvas, flag-gated behind Konva.
 *
 * Ties the C2 stage + C3a hit-testing + C3b gesture machine + C3c transformer
 * + the C3d SVG overlay into a working surface. Pointer events run through the
 * pure `gestureReducer`; actions apply through the EXISTING operation builders
 * (no new mutation path). A live `preview` override shows the in-progress
 * drag/resize/rotate before the engine commits.
 *
 * V0 scope: shared workspace pan/zoom and artboard placement parity with the
 * Konva canvas while preserving the CanvasKit gesture interaction layer.
 */

export interface CanvasKitCanvasProps {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId | null) => void;
  onSelectPage?: (pageId: PageId) => void;
  onOperation: (operation: Operation) => void;
  /** The engine provides authoritative point→node hit-testing (C3a). */
  engine: OptimisticEnginePort | null;
  diagnostics?: Diagnostic[];
  workspaceModel: WorkspaceModel;
  workspaceViewport: WorkspaceViewport;
  onWorkspaceViewportChange: WorkspaceViewportUpdater;
  workspaceTool: WorkspaceTool;
  onWorkspaceToolChange: (tool: WorkspaceTool) => void;
  workspaceFitTarget: WorkspaceFitTarget;
  onWorkspaceFitTargetChange: (target: WorkspaceFitTarget) => void;
  onOpenDiagnostics?: () => void;
  onOpenExport?: () => void;
  /** Called after the C4 measurement pass updates the engine's `computed`
   * (which does not emit a delta), so the host can re-sync its React scene. */
  onSceneRefresh?: () => void;
}

interface Preview {
  nodeId: NodeId;
  box: Box;
  rotation: number;
}

export function CanvasKitCanvas({
  scene,
  activePageId,
  selectedNodeId,
  onSelectNode,
  onSelectPage,
  onOperation,
  engine,
  diagnostics = [],
  workspaceModel,
  workspaceViewport,
  onWorkspaceViewportChange,
  workspaceTool,
  onWorkspaceToolChange,
  workspaceFitTarget,
  onWorkspaceFitTargetChange,
  onOpenDiagnostics,
  onOpenExport,
  onSceneRefresh
}: CanvasKitCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef<GestureState>(initialGestureState);
  const panDragRef = useRef<{ pointerId: number; x: number; y: number; pan: { x: number; y: number } } | null>(null);
  const [viewport, setViewport] = useState({ width: 900, height: 720 });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [marquee, setMarquee] = useState<Box | null>(null);
  const [editingNodeId, setEditingNodeId] = useState<NodeId | null>(null);
  const [hoverNodeId, setHoverNodeId] = useState<NodeId | null>(null);

  const page = getPage(scene, activePageId);
  const pageView = page ? pageDescriptor(page) : null;
  const activeArtboard = workspaceModel.activeArtboard;
  const unitScale = pageView?.unitScale ?? 1;
  const zoom = workspaceViewport.zoom;

  const pageOrigin = useMemo(() => {
    if (!activeArtboard) return { x: 0, y: 0 };
    return {
      x: workspaceViewport.pan.x + activeArtboard.workspaceRect.x * workspaceViewport.zoom,
      y: workspaceViewport.pan.y + activeArtboard.workspaceRect.y * workspaceViewport.zoom
    };
  }, [activeArtboard, workspaceViewport.pan.x, workspaceViewport.pan.y, workspaceViewport.zoom]);

  const fitRect = useMemo(() => {
    if (workspaceFitTarget === "current" && activeArtboard) {
      return activeArtboard.workspaceRect;
    }
    return workspaceModel.bounds;
  }, [activeArtboard, workspaceFitTarget, workspaceModel.bounds]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === "undefined") {
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
    if (workspaceFitTarget === "manual") {
      return;
    }
    onWorkspaceViewportChange(fitWorkspaceRectToViewport({ viewport, rect: fitRect }));
  }, [fitRect, onWorkspaceViewportChange, viewport, workspaceFitTarget]);

  useEffect(() => {
    onWorkspaceViewportChange((current) =>
      clampWorkspacePanToKeepVisible(current, workspaceModel.bounds, viewport)
    );
  }, [onWorkspaceViewportChange, viewport, workspaceModel.bounds]);

  // A signature of every text node's measurement inputs. The C4 measurement
  // pass keys on this, not the whole scene, so dragging/resizing non-text
  // nodes (which change `computed` but not text inputs) does not re-measure —
  // and the setMeasurements → relayout → refresh cycle cannot loop.
  const textSignature = useMemo(() => {
    const parts: string[] = [];
    for (const node of Object.values(scene.nodes)) {
      if (node.kind.kind !== "text") {
        continue;
      }
      const t = node.kind;
      parts.push(
        [
          t.content,
          t.font_family,
          t.font_size,
          t.font_weight,
          t.line_height ?? 1.2,
          t.letter_spacing ?? 0,
          t.wrap ?? "no_wrap",
          t.max_lines ?? "_",
          t.direction ?? "ltr"
        ].join("|")
      );
    }
    return parts.sort().join("\n");
  }, [scene]);

  // C4 measure-then-inject: measure every text node with SkParagraph and feed
  // the metrics to the engine, then re-sync the host scene so the Skia-faithful
  // geometry renders. Runs only when the text inputs change.
  useEffect(() => {
    if (!engine?.setMeasurements) {
      return;
    }
    let cancelled = false;
    void loadCanvasKit().then((bundle) => {
      if (cancelled || !bundle?.fontProvider || !engine.setMeasurements) {
        return;
      }
      engine.setMeasurements(skiaMeasurements(bundle.ck, bundle.fontProvider, scene));
      onSceneRefresh?.();
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine, textSignature]);

  // Descriptor trees, applying the live preview override to the dragged node.
  const artboards = useMemo(() => {
    const buildForPage = (pageId: PageId, nodeId: NodeId, parentComputedOrigin: ParentComputedOrigin | null = null): DrawNode | null => {
      const currentPage = scene.pages[pageId];
      const node = scene.nodes[nodeId];
      if (!node || !currentPage) return null;
      const descriptor = nodeDescriptor(scene, node, currentPage, parentComputedOrigin);
      if (preview && preview.nodeId === nodeId) {
        const scale = pageDescriptor(currentPage).unitScale;
        const parentOffsetX = (parentComputedOrigin?.x ?? 0) * scale;
        const parentOffsetY = (parentComputedOrigin?.y ?? 0) * scale;
        descriptor.x = preview.box.x - parentOffsetX;
        descriptor.y = preview.box.y - parentOffsetY;
        descriptor.width = preview.box.width;
        descriptor.height = preview.box.height;
        descriptor.rotation = preview.rotation;
      }
      const childParentComputedOrigin = node.computed
        ? {
            x: node.computed.layout_bounds.x,
            y: node.computed.layout_bounds.y
          }
        : null;
      return {
        descriptor,
        children: node.children.map((childId) => buildForPage(pageId, childId, childParentComputedOrigin)).filter(Boolean) as DrawNode[]
      };
    };
    return workspaceModel.artboards
      .map((artboard) => {
        const currentPage = scene.pages[artboard.pageId];
        if (!currentPage) {
          return null;
        }
        return {
          page: pageDescriptor(currentPage),
          workspaceRect: artboard.workspaceRect,
          isActive: artboard.isActive,
          nodes: currentPage.children.map((nodeId) => buildForPage(artboard.pageId, nodeId)).filter(Boolean) as DrawNode[]
        };
      })
      .filter(Boolean) as Array<{
      page: ReturnType<typeof pageDescriptor>;
      workspaceRect: { x: number; y: number; width: number; height: number };
      isActive: boolean;
      nodes: DrawNode[];
    }>;
  }, [scene, preview, workspaceModel.artboards]);

  const selectionBox = useMemo<{ box: Box; rotation: number; nodeId: NodeId } | null>(() => {
    if (!selectedNodeId) return null;
    if (preview && preview.nodeId === selectedNodeId) {
      return { box: preview.box, rotation: preview.rotation, nodeId: selectedNodeId };
    }
    const node = getNode(scene, selectedNodeId);
    if (!node || !page) return null;
    const d = nodeDescriptor(scene, node, page);
    return { box: { x: d.x, y: d.y, width: d.width, height: d.height }, rotation: d.rotation, nodeId: selectedNodeId };
  }, [scene, page, selectedNodeId, preview]);

  // Step 5 (E0.2): a draggable focal-point dot for the selected image node.
  const focalPoint = useMemo(() => {
    if (!selectionBox) return null;
    const node = getNode(scene, selectionBox.nodeId);
    if (!node || node.kind.kind !== "image") return null;
    return node.asset_placement?.focal_point ?? { x: 0.5, y: 0.5 };
  }, [scene, selectionBox]);

  const commitFocalPoint = useCallback(
    (focal: { x: number; y: number }) => {
      if (!selectionBox) return;
      const node = getNode(scene, selectionBox.nodeId);
      if (!node || node.kind.kind !== "image") return;
      const placement = {
        ...(node.asset_placement ?? {}),
        fit: node.asset_placement?.fit ?? "cover",
        focal_point: focal
      };
      onOperation({ kind: "update_node", node_id: node.id, patch: nodePatch({ asset_placement: set(placement) }) });
    },
    [scene, selectionBox, onOperation]
  );

  const chromeModel = useMemo(
    () =>
      deriveSelectionChromeModel(scene, {
        activePageId,
        selectedNodeId,
        hoverNodeId,
        diagnostics
      }),
    [activePageId, diagnostics, hoverNodeId, scene, selectedNodeId]
  );

  const showHandles = chromeModel.showHandles;

  const boxForNode = useCallback(
    (nodeId: NodeId): { box: Box; rotation: number } | null => {
      const node = getNode(scene, nodeId);
      if (!node || !page) return null;
      const d = nodeDescriptor(scene, node, page);
      return { box: { x: d.x, y: d.y, width: d.width, height: d.height }, rotation: d.rotation };
    },
    [scene, page]
  );

  const pressTargetFor = useCallback(
    (descriptorPoint: { x: number; y: number }): PressTarget => {
      // Handle grab on the current selection takes priority.
      if (selectionBox && showHandles) {
        const handle = handleAtPoint(descriptorPoint, selectionBox.box, selectionBox.rotation, zoom);
        if (handle === "rotate") {
          const center = {
            x: selectionBox.box.x + selectionBox.box.width / 2,
            y: selectionBox.box.y + selectionBox.box.height / 2
          };
          return { kind: "rotate", nodeId: selectionBox.nodeId, pivot: center, box: selectionBox.box, rotation: selectionBox.rotation };
        }
        if (handle) {
          return { kind: "handle", nodeId: selectionBox.nodeId, handle, box: selectionBox.box, rotation: selectionBox.rotation };
        }
      }
      // Otherwise hit-test the scene through the engine.
      const scenePoint = descriptorToScene(descriptorPoint, unitScale);
      const hit = engine?.hitTest?.(activePageId ?? "", scenePoint.x, scenePoint.y);
      if (hit?.hit) {
        const resolved = boxForNode(hit.hit);
        if (resolved) {
          return { kind: "node", nodeId: hit.hit, box: resolved.box, rotation: resolved.rotation };
        }
      }
      return { kind: "empty" };
    },
    [selectionBox, showHandles, zoom, unitScale, engine, activePageId, boxForNode]
  );

  const updateHoverFromEvent = useCallback(
    (event: React.PointerEvent) => {
      if (workspaceTool !== "select" || editingNodeId || stateRef.current.kind !== "idle") {
        setHoverNodeId(null);
        return;
      }
      const workspacePoint = screenToWorkspace(screenPointFromEvent(event), workspaceViewport);
      const hitArtboard = artboardAtWorkspacePoint(workspaceModel, workspacePoint);
      if (!hitArtboard || hitArtboard.pageId !== activePageId) {
        setHoverNodeId(null);
        return;
      }
      const hitPage = scene.pages[hitArtboard.pageId] ?? null;
      if (!hitPage) {
        setHoverNodeId(null);
        return;
      }
      const hitPageDescriptor = pageDescriptor(hitPage);
      const localDescriptorPoint = {
        x: workspacePoint.x - hitArtboard.workspaceRect.x,
        y: workspacePoint.y - hitArtboard.workspaceRect.y
      };
      const scenePoint = descriptorToScene(localDescriptorPoint, hitPageDescriptor.unitScale);
      const hit = engine?.hitTest?.(hitArtboard.pageId, scenePoint.x, scenePoint.y)?.hit ?? null;
      setHoverNodeId((current) => (current === hit ? current : hit));
    },
    [activePageId, editingNodeId, engine, scene.pages, workspaceModel, workspaceTool, workspaceViewport]
  );

  const applyAction = useCallback(
    (action: GestureAction) => {
      if (!page) return;
      switch (action.kind) {
        case "select":
          onSelectNode(action.nodeId);
          break;
        case "drag": {
          const node = getNode(scene, action.nodeId);
          if (!node) break;
          if (action.committed) {
            setPreview(null);
            const op = dragActionToOperation(action.box, scene, node, page, pageOrigin);
            if (op) onOperation(op);
          } else {
            setPreview({ nodeId: action.nodeId, box: action.box, rotation: nodeDescriptor(scene, node, page).rotation });
          }
          break;
        }
        case "resize": {
          const node = getNode(scene, action.nodeId);
          if (!node) break;
          const rotation = nodeDescriptor(scene, node, page).rotation;
          if (action.committed) {
            setPreview(null);
            const op = resizeActionToOperation(action.box, rotation, scene, node, page, pageOrigin);
            if (op) onOperation(op);
          } else {
            setPreview({ nodeId: action.nodeId, box: action.box, rotation });
          }
          break;
        }
        case "rotate": {
          const node = getNode(scene, action.nodeId);
          if (!node || !selectionBox) break;
          if (action.committed) {
            setPreview(null);
            const op = resizeActionToOperation(selectionBox.box, action.rotation, scene, node, page, pageOrigin);
            if (op) onOperation(op);
          } else {
            setPreview({ nodeId: action.nodeId, box: selectionBox.box, rotation: action.rotation });
          }
          break;
        }
        case "marquee": {
          if (action.committed) {
            setMarquee(null);
            const boxes = page.children
              .map((id) => {
                const resolved = boxForNode(id);
                return resolved ? { nodeId: id, box: resolved.box } : null;
              })
              .filter(Boolean) as Array<{ nodeId: NodeId; box: Box }>;
            const hits = marqueeSelection(action.rect, boxes);
            onSelectNode(hits.length > 0 ? hits[hits.length - 1] : null);
          } else {
            setMarquee(action.rect);
          }
          break;
        }
        default:
          break;
      }
    },
    [scene, page, pageOrigin, selectionBox, onOperation, onSelectNode, boxForNode]
  );

  const dispatch = useCallback(
    (event: Parameters<typeof gestureReducer>[1]) => {
      const result = gestureReducer(stateRef.current, event);
      stateRef.current = result.state;
      applyAction(result.action);
    },
    [applyAction]
  );

  const pointerFromEvent = (event: React.PointerEvent): { x: number; y: number } => {
    return screenToDescriptor(screenPointFromEvent(event, containerRef.current), pageOrigin, zoom);
  };

  // The text node being edited: its descriptor box + style for the DOM overlay.
  const editing = useMemo(() => {
    if (!editingNodeId || !page) {
      return null;
    }
    const node = getNode(scene, editingNodeId);
    if (!node || node.kind.kind !== "text") {
      return null;
    }
    const d = nodeDescriptor(scene, node, page);
    if (!d.text) {
      return null;
    }
    return {
      node,
      box: { x: d.x, y: d.y, width: d.width, height: d.height } as Box,
      rotation: d.rotation,
      content: d.text.content,
      style: {
        fontFamily: d.text.fontFamily,
        fontSize: d.text.fontSize,
        fontWeight: d.text.fontWeight,
        align: d.text.align,
        lineHeight: d.text.lineHeight,
        letterSpacing: d.text.letterSpacing,
        color: d.fill
      }
    };
  }, [scene, page, editingNodeId]);

  // Double-click: edit a text node, otherwise drill to its top-level container.
  const onDoubleClick = (event: React.MouseEvent) => {
    const rect = containerRef.current?.getBoundingClientRect();
    const descriptorPoint = screenToDescriptor(
      { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) },
      pageOrigin,
      zoom
    );
    const scenePoint = descriptorToScene(descriptorPoint, unitScale);
    const hit = engine?.hitTest?.(activePageId ?? "", scenePoint.x, scenePoint.y);
    if (hit?.hit) {
      const node = getNode(scene, hit.hit);
      if (node?.kind.kind === "text") {
        onSelectNode(hit.hit);
        setEditingNodeId(hit.hit);
        return;
      }
    }
    if (selectedNodeId) {
      onSelectNode(topLevelAncestorId(scene, selectedNodeId) ?? selectedNodeId);
    }
  };

  const commitTextEdit = (content: string) => {
    const node = editing?.node;
    const original = editing?.content;
    setEditingNodeId(null);
    if (node && content !== original) {
      onOperation(updateTextNode(node, { content }));
    }
  };

  const modifiersFromEvent = (event: React.PointerEvent) => ({
    shift: event.shiftKey,
    meta: event.metaKey || event.ctrlKey
  });

  const fitWorkspace = (target: "current" | "all") => {
    const rect = target === "current" && activeArtboard ? activeArtboard.workspaceRect : workspaceModel.bounds;
    onWorkspaceFitTargetChange(target);
    onWorkspaceViewportChange(fitWorkspaceRectToViewport({ viewport, rect }));
  };

  const zoomBy = (delta: number) => {
    onWorkspaceFitTargetChange("manual");
    onWorkspaceViewportChange((current) =>
      zoomWorkspaceViewportAtPoint(
        current,
        { x: viewport.width / 2, y: viewport.height / 2 },
        clampWorkspaceZoom(current.zoom + delta)
      )
    );
  };

  return (
    <section className="canvas-shell workspace-canvas-shell" ref={containerRef} style={{ position: "relative" }}>
      <CanvasKitStage artboards={artboards} viewport={workspaceViewport} />
      <CanvasKitArtboardLabels workspaceModel={workspaceModel} viewport={workspaceViewport} />
      <div className="workspace-context-bar">
        <span className="workspace-context-label">{activeArtboard?.label ?? "No artboard"}</span>
        <span>{pageView ? `${formatDimension(pageView.width)} x ${formatDimension(pageView.height)} pt` : "No frame"}</span>
      </div>
      <div className="workspace-bottom-toolbar" aria-label="CanvasKit workspace tools">
        <button
          type="button"
          className={workspaceTool === "select" ? "active" : undefined}
          aria-label="Select tool"
          aria-pressed={workspaceTool === "select"}
          title="Select tool"
          onClick={() => onWorkspaceToolChange("select")}
        >
          <MousePointer2 aria-hidden size={16} />
        </button>
        <button
          type="button"
          className={workspaceTool === "hand" ? "active" : undefined}
          aria-label="Pan tool"
          aria-pressed={workspaceTool === "hand"}
          title="Pan tool"
          onClick={() => onWorkspaceToolChange("hand")}
        >
          <Hand aria-hidden size={16} />
        </button>
        <span className="workspace-toolbar-separator" />
        <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => zoomBy(-0.1)}>
          <Minus aria-hidden size={16} />
        </button>
        <strong>{Math.round(zoom * 100)}%</strong>
        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => zoomBy(0.1)}>
          <Plus aria-hidden size={16} />
        </button>
        <span className="workspace-toolbar-separator" />
        <button
          type="button"
          className={workspaceFitTarget === "current" ? "active" : undefined}
          aria-label="Fit current artboard"
          aria-pressed={workspaceFitTarget === "current"}
          title="Fit current artboard"
          onClick={() => fitWorkspace("current")}
        >
          <LocateFixed aria-hidden size={16} />
        </button>
        <button
          type="button"
          className={workspaceFitTarget === "all" ? "active" : undefined}
          aria-label="Fit all artboards"
          aria-pressed={workspaceFitTarget === "all"}
          title="Fit all artboards"
          onClick={() => fitWorkspace("all")}
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
      <div
        data-testid="canvaskit-interaction-layer"
        style={{ position: "absolute", inset: 0 }}
        onWheel={(event) => {
          event.preventDefault();
          const screenPoint = screenPointFromEvent(event, containerRef.current);
          onWorkspaceFitTargetChange("manual");
          if (event.ctrlKey || event.metaKey) {
            onWorkspaceViewportChange((current) =>
              zoomWorkspaceViewportAtPoint(current, screenPoint, current.zoom + (event.deltaY > 0 ? -0.08 : 0.08))
            );
            return;
          }
          onWorkspaceViewportChange((current) =>
            clampWorkspacePanToKeepVisible(
              panWorkspaceViewport(current, { x: -event.deltaX, y: -event.deltaY }),
              workspaceModel.bounds,
              viewport
            )
          );
        }}
        onPointerDown={(event) => {
          if (editingNodeId) return; // editing: let the textarea own the pointer
          setHoverNodeId(null);
          const screenPoint = screenPointFromEvent(event);
          if (workspaceTool === "hand") {
            panDragRef.current = {
              pointerId: event.pointerId,
              x: screenPoint.x,
              y: screenPoint.y,
              pan: workspaceViewport.pan
            };
            onWorkspaceFitTargetChange("manual");
            try {
              event.currentTarget.setPointerCapture(event.pointerId);
            } catch {
              // Pointer capture is best-effort (e.g., synthetic pointers in tests).
            }
            return;
          }
          const workspacePoint = screenToWorkspace(screenPoint, workspaceViewport);
          const hitArtboard = artboardAtWorkspacePoint(workspaceModel, workspacePoint);
          if (!hitArtboard) {
            onSelectNode(null);
            return;
          }
          if (hitArtboard.pageId !== activePageId) {
            const hitPage = scene.pages[hitArtboard.pageId] ?? null;
            const hitDescriptor = hitPage ? pageDescriptor(hitPage) : null;
            const localDescriptorPoint = {
              x: workspacePoint.x - hitArtboard.workspaceRect.x,
              y: workspacePoint.y - hitArtboard.workspaceRect.y
            };
            const scenePoint = hitDescriptor
              ? descriptorToScene(localDescriptorPoint, hitDescriptor.unitScale)
              : null;
            const hit = scenePoint
              ? engine?.hitTest?.(hitArtboard.pageId, scenePoint.x, scenePoint.y)
              : null;
            onSelectPage?.(hitArtboard.pageId);
            onSelectNode(hit?.hit ?? null);
            return;
          }
          try {
            event.currentTarget.setPointerCapture(event.pointerId);
          } catch {
            // Pointer capture is best-effort (e.g., synthetic pointers in tests).
          }
          dispatch({ kind: "down", point: pointerFromEvent(event), target: pressTargetFor(pointerFromEvent(event)), modifiers: modifiersFromEvent(event) });
        }}
        onPointerMove={(event) => {
          const activePan = panDragRef.current;
          if (activePan && activePan.pointerId === event.pointerId) {
            const screenPoint = screenPointFromEvent(event);
            onWorkspaceViewportChange((current) =>
              clampWorkspacePanToKeepVisible(
                {
                  ...current,
                  pan: {
                    x: activePan.pan.x + screenPoint.x - activePan.x,
                    y: activePan.pan.y + screenPoint.y - activePan.y
                  }
                },
                workspaceModel.bounds,
                viewport
              )
            );
            return;
          }
          if (editingNodeId) {
            setHoverNodeId(null);
            return;
          }
          if (stateRef.current.kind === "idle") {
            updateHoverFromEvent(event);
            return;
          }
          setHoverNodeId(null);
          dispatch({ kind: "move", point: pointerFromEvent(event), modifiers: modifiersFromEvent(event) });
        }}
        onPointerUp={(event) => {
          if (panDragRef.current?.pointerId === event.pointerId) {
            panDragRef.current = null;
            try {
              event.currentTarget.releasePointerCapture(event.pointerId);
            } catch {
              // Pointer capture is best-effort.
            }
            return;
          }
          if (editingNodeId) return;
          dispatch({ kind: "up", point: pointerFromEvent(event), modifiers: modifiersFromEvent(event) });
        }}
        onPointerCancel={() => {
          panDragRef.current = null;
          stateRef.current = initialGestureState;
          setPreview(null);
          setMarquee(null);
          setHoverNodeId(null);
        }}
        onPointerLeave={() => setHoverNodeId(null)}
        onDoubleClick={onDoubleClick}
      >
        <SelectionOverlay
          selection={
            selectionBox && !editingNodeId
              ? { box: selectionBox.box, rotation: selectionBox.rotation }
              : null
          }
          hover={
            hoverNodeId && hoverNodeId !== selectedNodeId && !editingNodeId
              ? boxForNode(hoverNodeId)
              : null
          }
          containerChildren={editingNodeId ? [] : containerChildBoxes(scene, selectedNodeId, unitScale)}
          containerLabel={editingNodeId ? undefined : containerLabel(scene, selectedNodeId)}
          marquee={marquee}
          pageOrigin={pageOrigin}
          zoom={zoom}
          showHandles={showHandles && !editingNodeId}
          disabledReason={editingNodeId ? null : chromeModel.disabledReason}
          slotKeys={chromeModel.slotKeys}
          diagnosticCounts={chromeModel.diagnosticCounts}
          focal={editingNodeId ? null : focalPoint}
          onFocalChange={commitFocalPoint}
        />
        {editing ? (
          <TextEditOverlay
            box={editing.box}
            rotation={editing.rotation}
            content={editing.content}
            style={editing.style}
            pageOrigin={pageOrigin}
            zoom={zoom}
            onCommit={commitTextEdit}
            onCancel={() => setEditingNodeId(null)}
          />
        ) : null}
      </div>
    </section>
  );
}

function containerChildBoxes(scene: Scene, nodeId: NodeId | null, unitScale: number): Box[] {
  const geometry = containerSelectionGeometry(scene, nodeId);
  if (!geometry) return [];
  // containerSelectionGeometry returns absolute scene-unit rects; the overlay
  // works in descriptor space (scene × unitScale), so scale them up.
  return geometry.children.map((c) => ({
    x: c.x * unitScale,
    y: c.y * unitScale,
    width: c.width * unitScale,
    height: c.height * unitScale
  }));
}

function CanvasKitArtboardLabels({
  workspaceModel,
  viewport
}: {
  workspaceModel: WorkspaceModel;
  viewport: WorkspaceViewport;
}) {
  return (
    <div className="canvaskit-artboard-labels" aria-hidden>
      {workspaceModel.artboards.map((artboard) => (
        <span
          key={artboard.pageId}
          className={artboard.isActive ? "canvaskit-artboard-label active" : "canvaskit-artboard-label"}
          style={{
            transform: `translate(${viewport.pan.x + artboard.workspaceRect.x * viewport.zoom}px, ${
              viewport.pan.y + artboard.workspaceRect.y * viewport.zoom - 30
            }px)`
          }}
        >
          {artboard.label}
        </span>
      ))}
    </div>
  );
}

function screenPointFromEvent(
  event: React.PointerEvent | React.WheelEvent | React.MouseEvent,
  fallbackElement?: Element | null
): { x: number; y: number } {
  const currentTarget = event.currentTarget as Element | null;
  const rect = (currentTarget ?? fallbackElement)?.getBoundingClientRect();
  return {
    x: event.clientX - (rect?.left ?? 0),
    y: event.clientY - (rect?.top ?? 0)
  };
}

function formatDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}

function containerLabel(scene: Scene, nodeId: NodeId | null): string | undefined {
  const geometry = containerSelectionGeometry(scene, nodeId);
  if (!geometry) return undefined;
  const node = getNode(scene, nodeId);
  const name = node ? nodeDisplayName(node) : geometry.label;
  return `${name} · ${geometry.children.length} inside`;
}
