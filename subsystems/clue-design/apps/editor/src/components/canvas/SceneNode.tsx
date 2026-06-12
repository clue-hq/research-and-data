"use client";

import { Fragment } from "react";
import { Group, Line, Path, Rect, Text } from "react-konva";
import type Konva from "konva";
import type { NodeId, Operation, Page, Scene } from "@/engine/contracts";
import { canvasDragOperation, canvasResizeOperation } from "@/engine/canvasOperations";
import type { ParentComputedOrigin } from "@/engine/renderAdapter";
import { nodeDescriptor } from "@/engine/renderAdapter";
import { isNodeDirectGeometryEditable } from "@/engine/sceneQueries";

interface SceneNodeProps {
  scene: Scene;
  page: Page;
  nodeId: NodeId;
  pageOrigin: { x: number; y: number };
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId) => void;
  onOperation: (operation: Operation) => void;
  registerNode: (nodeId: NodeId, node: Konva.Node | null) => void;
  parentComputedOrigin?: ParentComputedOrigin | null;
}

export function SceneNode({
  scene,
  page,
  nodeId,
  pageOrigin,
  selectedNodeId,
  onSelectNode,
  onOperation,
  registerNode,
  parentComputedOrigin = null
}: SceneNodeProps) {
  const node = scene.nodes[nodeId];
  if (!node) {
    return null;
  }
  const descriptor = nodeDescriptor(scene, node, page, parentComputedOrigin);
  const selected = selectedNodeId === node.id;
  const directGeometryEditable = isNodeDirectGeometryEditable(scene, node.id);
  const childParentComputedOrigin = node.computed
    ? {
        x: node.computed.layout_bounds.x,
        y: node.computed.layout_bounds.y
      }
    : null;

  const handleDragEnd = (event: Konva.KonvaEventObject<DragEvent>) => {
    if (!directGeometryEditable) {
      return;
    }
    const operation = canvasDragOperation({
      scene,
      node,
      page,
      pageOrigin,
      canvasX: event.target.x(),
      canvasY: event.target.y()
    });
    if (operation) {
      onOperation(operation);
    }
  };

  const handleTransformEnd = (event: Konva.KonvaEventObject<Event>) => {
    if (!directGeometryEditable) {
      return;
    }
    const target = event.target;
    const scaleX = target.scaleX();
    const scaleY = target.scaleY();
    target.scaleX(1);
    target.scaleY(1);

    const operation = canvasResizeOperation({
      scene,
      node,
      page,
      pageOrigin,
      transform: {
        canvasX: target.x(),
        canvasY: target.y(),
        rotation: target.rotation(),
        scaleX,
        scaleY
      }
    });
    if (operation) {
      onOperation(operation);
    }
  };

  return (
    <Group
      ref={(konvaNode) => registerNode(node.id, konvaNode)}
      id={node.id}
      name="scene-node"
      x={pageOrigin.x + descriptor.x}
      y={pageOrigin.y + descriptor.y}
      rotation={descriptor.rotation}
      opacity={descriptor.opacity}
      draggable={directGeometryEditable}
      onClick={(event) => {
        event.cancelBubble = true;
        onSelectNode(node.id);
      }}
      onTap={(event) => {
        event.cancelBubble = true;
        onSelectNode(node.id);
      }}
      onDragEnd={handleDragEnd}
      onTransformEnd={handleTransformEnd}
    >
      <NodeBody descriptor={descriptor} selected={selected} locked={node.locked} />
      {descriptor.slotKeys.length > 0 ? <SlotBadge descriptor={descriptor} selected={selected} /> : null}
      {node.children.map((childId) => (
        <SceneNode
          key={childId}
          scene={scene}
          page={page}
          nodeId={childId}
          pageOrigin={{ x: 0, y: 0 }}
          selectedNodeId={selectedNodeId}
          onSelectNode={onSelectNode}
          onOperation={onOperation}
          registerNode={registerNode}
          parentComputedOrigin={childParentComputedOrigin}
        />
      ))}
    </Group>
  );
}

function SlotBadge({
  descriptor,
  selected
}: {
  descriptor: ReturnType<typeof nodeDescriptor>;
  selected: boolean;
}) {
  const label = descriptor.slotKeys.length === 1 ? descriptor.slotKeys[0] : `${descriptor.slotKeys.length} slots`;
  const width = Math.max(74, Math.min(170, label.length * 6.8 + 20));
  const y = Math.max(-26, -descriptor.height - 26);
  return (
    <Group x={0} y={y} listening={false}>
      <Rect
        width={width}
        height={20}
        fill={selected ? "#174f52" : "#fffaf2"}
        stroke="#256c70"
        strokeWidth={1}
        cornerRadius={5}
        shadowColor="#000000"
        shadowOpacity={0.12}
        shadowBlur={6}
        shadowOffsetY={2}
      />
      <Text
        text={label}
        width={width}
        height={20}
        fill={selected ? "#ffffff" : "#174f52"}
        fontSize={10}
        fontStyle="700"
        align="center"
        verticalAlign="middle"
        listening={false}
      />
    </Group>
  );
}

function NodeBody({
  descriptor,
  selected,
  locked
}: {
  descriptor: ReturnType<typeof nodeDescriptor>;
  selected: boolean;
  locked: boolean;
}) {
  const selectionStroke = selected ? "#256c70" : locked ? "#9b6b5f" : descriptor.stroke;
  const selectionDash = selected || locked ? [5, 4] : undefined;

  if (descriptor.kind === "text" && descriptor.text) {
    return (
      <Text
        text={descriptor.text.content}
        width={descriptor.width}
        height={textHeightForRender(descriptor)}
        fill={descriptor.fill}
        fontFamily={descriptor.text.fontFamily}
        fontSize={descriptor.text.fontSize}
        fontStyle={fontStyleFromWeight(descriptor.text.fontWeight)}
        align={descriptor.text.align}
        direction={textDirectionForKonva(descriptor.text.direction)}
        lineHeight={descriptor.text.lineHeight}
        letterSpacing={descriptor.text.letterSpacing}
        wrap={descriptor.text.wrap === "wrap" ? "word" : "none"}
        ellipsis={descriptor.text.maxLines !== null}
        verticalAlign="top"
        stroke={selectionStroke ?? undefined}
        strokeWidth={selected ? 0.35 : 0}
      />
    );
  }

  if (descriptor.kind === "line" && descriptor.line) {
    return (
      <Line
        points={descriptor.line.points}
        stroke={selectionStroke ?? descriptor.fill}
        strokeWidth={Math.max(1, descriptor.strokeWidth || 1)}
        dash={selectionDash}
      />
    );
  }

  if (descriptor.kind === "vector" && descriptor.vector) {
    return (
      <Path
        data={descriptor.vector.pathData}
        fill={descriptor.fill}
        stroke={selectionStroke ?? undefined}
        strokeWidth={descriptor.strokeWidth}
        dash={selectionDash}
      />
    );
  }

  if (descriptor.kind === "image") {
    const label = imagePlaceholderLabel(descriptor);
    return (
      <Fragment>
        <Rect
          width={descriptor.width}
          height={descriptor.height}
          fill={descriptor.fill}
          stroke={selectionStroke ?? "#a79c8a"}
          strokeWidth={selected ? 1.5 : 1}
          dash={selectionDash}
          cornerRadius={descriptor.cornerRadius}
        />
        <Text
          text={label}
          width={descriptor.width}
          height={descriptor.height}
          fill="#5f574c"
          fontSize={Math.max(10, Math.min(13, descriptor.width / 16))}
          lineHeight={1.18}
          align="center"
          verticalAlign="middle"
          listening={false}
        />
      </Fragment>
    );
  }

  return (
    <Rect
      width={descriptor.width}
      height={descriptor.height}
      fill={descriptor.fill}
      stroke={selectionStroke ?? undefined}
      strokeWidth={selected ? Math.max(1, descriptor.strokeWidth) : descriptor.strokeWidth}
      dash={selectionDash}
      cornerRadius={descriptor.cornerRadius}
    />
  );
}

function imagePlaceholderLabel(descriptor: ReturnType<typeof nodeDescriptor>): string {
  const image = descriptor.image;
  if (!image) {
    return "Image";
  }
  const label = image.alt || image.assetLabel || "Image asset";
  return `${label}\n${image.assetId}`;
}

function textHeightForRender(descriptor: ReturnType<typeof nodeDescriptor>): number {
  if (!descriptor.text?.maxLines) {
    return descriptor.height;
  }
  const maxTextHeight = descriptor.text.fontSize * descriptor.text.lineHeight * descriptor.text.maxLines;
  return Math.min(descriptor.height, maxTextHeight);
}

function textDirectionForKonva(direction: "ltr" | "rtl" | "auto"): string {
  return direction === "auto" ? "inherit" : direction;
}

function fontStyleFromWeight(weight: number): string {
  if (weight >= 700) {
    return "700";
  }
  if (weight >= 600) {
    return "600";
  }
  if (weight >= 500) {
    return "500";
  }
  return "normal";
}
