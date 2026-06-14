"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { NodeId, Operation, PageId, Scene } from "@/engine/contracts";
import type { OptimisticEnginePort } from "@/engine/wasmEngine";
import type { WorkspaceModel } from "@/engine/workspaceLayout";
import { centeredPageOrigin, fitZoomForPage } from "@/engine/canvasViewport";
import { containerSelectionGeometry, isCanvasDirectGeometryEditable } from "@/engine/canvasSelection";
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
import { nodeDescriptor, pageDescriptor } from "@/engine/renderAdapter";
import { loadCanvasKit } from "@/engine/canvaskit/loadCanvasKit";
import { skiaMeasurements } from "@/engine/canvaskit/skiaMeasurements";
import type { Box } from "@/engine/transformerMath";
import { updateTextNode } from "@/engine/operations";
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
 * V0 scope: a fit-to-page viewport (interactive pan/zoom parity with the Konva
 * canvas is a documented follow-up); the interaction layer is the C3 value.
 */

export interface CanvasKitCanvasProps {
  scene: Scene;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId | null) => void;
  onOperation: (operation: Operation) => void;
  /** The engine provides authoritative point→node hit-testing (C3a). */
  engine: OptimisticEnginePort | null;
  workspaceModel?: WorkspaceModel;
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
  onOperation,
  engine,
  onSceneRefresh
}: CanvasKitCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef<GestureState>(initialGestureState);
  const [viewport, setViewport] = useState({ width: 900, height: 720 });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [marquee, setMarquee] = useState<Box | null>(null);
  const [editingNodeId, setEditingNodeId] = useState<NodeId | null>(null);

  const page = getPage(scene, activePageId);
  const pageView = page ? pageDescriptor(page) : null;
  const unitScale = pageView?.unitScale ?? 1;

  const zoom = useMemo(() => {
    if (!pageView) return 1;
    return fitZoomForPage({
      viewportWidth: viewport.width,
      viewportHeight: viewport.height,
      pageWidth: pageView.width,
      pageHeight: pageView.height
    });
  }, [pageView, viewport.height, viewport.width]);

  const pageOrigin = useMemo(() => {
    if (!pageView) return { x: 0, y: 0 };
    return centeredPageOrigin({
      viewportWidth: viewport.width,
      viewportHeight: viewport.height,
      pageWidth: pageView.width,
      pageHeight: pageView.height,
      zoom
    });
  }, [pageView, viewport.height, viewport.width, zoom]);

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

  // Descriptor tree, applying the live preview override to the dragged node.
  const nodes = useMemo<DrawNode[]>(() => {
    if (!page) return [];
    const build = (nodeId: NodeId): DrawNode | null => {
      const node = scene.nodes[nodeId];
      if (!node) return null;
      const descriptor = nodeDescriptor(scene, node, page);
      if (preview && preview.nodeId === nodeId) {
        descriptor.x = preview.box.x;
        descriptor.y = preview.box.y;
        descriptor.width = preview.box.width;
        descriptor.height = preview.box.height;
        descriptor.rotation = preview.rotation;
      }
      return { descriptor, children: node.children.map(build).filter(Boolean) as DrawNode[] };
    };
    return page.children.map(build).filter(Boolean) as DrawNode[];
  }, [scene, page, preview]);

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

  const showHandles = isCanvasDirectGeometryEditable(scene, selectedNodeId);

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
    const rect = containerRef.current?.getBoundingClientRect();
    const sx = event.clientX - (rect?.left ?? 0);
    const sy = event.clientY - (rect?.top ?? 0);
    return screenToDescriptor({ x: sx, y: sy }, pageOrigin, zoom);
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

  return (
    <section className="canvas-shell" ref={containerRef} style={{ position: "relative" }}>
      <CanvasKitStage page={pageView ?? EMPTY_PAGE} nodes={nodes} pageOrigin={pageOrigin} zoom={zoom} />
      <div
        style={{ position: "absolute", inset: 0 }}
        onPointerDown={(event) => {
          if (editingNodeId) return; // editing: let the textarea own the pointer
          try {
            event.currentTarget.setPointerCapture(event.pointerId);
          } catch {
            // Pointer capture is best-effort (e.g., synthetic pointers in tests).
          }
          dispatch({ kind: "down", point: pointerFromEvent(event), target: pressTargetFor(pointerFromEvent(event)), modifiers: modifiersFromEvent(event) });
        }}
        onPointerMove={(event) => {
          if (editingNodeId || stateRef.current.kind === "idle") return;
          dispatch({ kind: "move", point: pointerFromEvent(event), modifiers: modifiersFromEvent(event) });
        }}
        onPointerUp={(event) => {
          if (editingNodeId) return;
          dispatch({ kind: "up", point: pointerFromEvent(event), modifiers: modifiersFromEvent(event) });
        }}
        onDoubleClick={onDoubleClick}
      >
        <SelectionOverlay
          selection={
            selectionBox && !editingNodeId
              ? { box: selectionBox.box, rotation: selectionBox.rotation }
              : null
          }
          containerChildren={editingNodeId ? [] : containerChildBoxes(scene, selectedNodeId, unitScale)}
          containerLabel={editingNodeId ? undefined : containerLabel(scene, selectedNodeId)}
          marquee={marquee}
          pageOrigin={pageOrigin}
          zoom={zoom}
          showHandles={showHandles && !editingNodeId}
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

const EMPTY_PAGE = { id: "", name: "", width: 0, height: 0, unitScale: 1, background: "#ffffff" };

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

function containerLabel(scene: Scene, nodeId: NodeId | null): string | undefined {
  const geometry = containerSelectionGeometry(scene, nodeId);
  if (!geometry) return undefined;
  const node = getNode(scene, nodeId);
  const name = node ? nodeDisplayName(node) : geometry.label;
  return `${name} · ${geometry.children.length} inside`;
}
