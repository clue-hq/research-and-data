"use client";

import { Group, Rect, Text } from "react-konva";
import type { NodeId, Scene } from "@/engine/contracts";
import { containerSelectionGeometry } from "@/engine/canvasSelection";

interface ContainerSelectionOverlayProps {
  scene: Scene;
  selectedNodeId: NodeId | null;
  pageOrigin: { x: number; y: number };
  unitScale: number;
}

const CONTAINER_STROKE = "#256c70";
const CHILD_STROKE = "#256c70";
const LABEL_FILL = "#174f52";
const LABEL_TEXT = "#ffffff";

/**
 * Container selection clarity (coordinate-model fix, Part 2): when the
 * selected node is a container holding children, draw distinct chrome — a
 * labeled bounding box and faint outlines of each direct child — so the user
 * can see "I selected a container of N elements" before dragging it (a drag
 * correctly moves the whole subtree). Purely presentational and
 * non-interactive (`listening={false}`); it never intercepts clicks meant for
 * the nodes underneath.
 */
export function ContainerSelectionOverlay({
  scene,
  selectedNodeId,
  pageOrigin,
  unitScale
}: ContainerSelectionOverlayProps) {
  const geometry = containerSelectionGeometry(scene, selectedNodeId);
  if (!geometry) {
    return null;
  }

  const container = {
    x: pageOrigin.x + geometry.container.x * unitScale,
    y: pageOrigin.y + geometry.container.y * unitScale,
    width: geometry.container.width * unitScale,
    height: geometry.container.height * unitScale
  };

  const label = geometry.label;
  const childCount = geometry.children.length;
  const labelText = childCount > 0 ? `${label} · ${childCount} inside` : label;
  const labelWidth = Math.max(64, Math.min(220, labelText.length * 6.6 + 18));
  const labelHeight = 18;

  return (
    <Group listening={false} name="container-selection-overlay">
      {geometry.children.map((child, index) => (
        <Rect
          key={`container-child-outline-${index}`}
          x={pageOrigin.x + child.x * unitScale}
          y={pageOrigin.y + child.y * unitScale}
          width={child.width * unitScale}
          height={child.height * unitScale}
          stroke={CHILD_STROKE}
          strokeWidth={1}
          dash={[3, 3]}
          opacity={0.4}
          listening={false}
        />
      ))}
      <Rect
        x={container.x}
        y={container.y}
        width={container.width}
        height={container.height}
        stroke={CONTAINER_STROKE}
        strokeWidth={1.5}
        dash={[6, 4]}
        listening={false}
      />
      <Group x={container.x} y={container.y - labelHeight - 3} listening={false}>
        <Rect
          width={labelWidth}
          height={labelHeight}
          fill={LABEL_FILL}
          cornerRadius={4}
          listening={false}
        />
        <Text
          text={labelText}
          width={labelWidth}
          height={labelHeight}
          fill={LABEL_TEXT}
          fontSize={10}
          fontStyle="700"
          align="center"
          verticalAlign="middle"
          ellipsis
          wrap="none"
          listening={false}
        />
      </Group>
    </Group>
  );
}
