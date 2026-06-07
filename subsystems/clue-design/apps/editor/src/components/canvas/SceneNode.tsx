"use client";

import { Fragment } from "react";
import { Group, Line, Path, Rect, Text } from "react-konva";
import type Konva from "konva";
import type { NodeId, Operation, Page, Scene, Transform } from "@/engine/contracts";
import {
  fixedSize,
  nodeDescriptor,
  pageDescriptor,
  sceneUnitFromCanvas,
  sizeFromCanvas
} from "@/engine/renderAdapter";
import { updateNodeTransform, updateNodeTransformAndSize } from "@/engine/operations";

interface SceneNodeProps {
  scene: Scene;
  page: Page;
  nodeId: NodeId;
  pageOrigin: { x: number; y: number };
  selectedNodeId: NodeId | null;
  onSelectNode: (nodeId: NodeId) => void;
  onOperation: (operation: Operation) => void;
  registerNode: (nodeId: NodeId, node: Konva.Node | null) => void;
}

export function SceneNode({
  scene,
  page,
  nodeId,
  pageOrigin,
  selectedNodeId,
  onSelectNode,
  onOperation,
  registerNode
}: SceneNodeProps) {
  const node = scene.nodes[nodeId];
  if (!node) {
    return null;
  }
  const descriptor = nodeDescriptor(scene, node, page);
  const selected = selectedNodeId === node.id;
  const draggable = !node.locked;

  const handleDragEnd = (event: Konva.KonvaEventObject<DragEvent>) => {
    const nextTransform: Transform = {
      ...node.transform,
      x: sceneUnitFromCanvas(event.target.x() - pageOrigin.x, page),
      y: sceneUnitFromCanvas(event.target.y() - pageOrigin.y, page)
    };
    onOperation(updateNodeTransform(node, nextTransform));
  };

  const handleTransformEnd = (event: Konva.KonvaEventObject<Event>) => {
    const target = event.target;
    const scaleX = target.scaleX();
    const scaleY = target.scaleY();
    target.scaleX(1);
    target.scaleY(1);

    const baseSize = fixedSize(node.size, pageDescriptor(page).unitScale);
    const nextWidth = Math.max(2, baseSize.width * scaleX);
    const nextHeight = Math.max(2, baseSize.height * scaleY);
    const nextTransform: Transform = {
      ...node.transform,
      x: sceneUnitFromCanvas(target.x() - pageOrigin.x, page),
      y: sceneUnitFromCanvas(target.y() - pageOrigin.y, page),
      rotation: target.rotation()
    };

    onOperation(updateNodeTransformAndSize(node, nextTransform, sizeFromCanvas(nextWidth, nextHeight, page)));
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
      draggable={draggable}
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
        />
      ))}
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
        height={descriptor.height}
        fill={descriptor.fill}
        fontFamily={descriptor.text.fontFamily}
        fontSize={descriptor.text.fontSize}
        fontStyle={fontStyleFromWeight(descriptor.text.fontWeight)}
        align={descriptor.text.align}
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
          text="Image"
          width={descriptor.width}
          height={descriptor.height}
          fill="#5f574c"
          fontSize={13}
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
