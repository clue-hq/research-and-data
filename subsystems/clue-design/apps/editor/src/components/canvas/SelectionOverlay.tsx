"use client";

import { handlePoint, type Box, type ResizeHandle } from "@/engine/transformerMath";

/**
 * Wave 3 C3d (Decision 5): selection chrome in a DOM/SVG overlay above the
 * CanvasKit content surface. Crisp at any zoom, gives handle hit-testing for
 * free, and — critically — hover/selection never trigger a wasm redraw.
 *
 * All geometry is DESCRIPTOR space (computed × unitScale, i.e. canvas px at
 * zoom 1); the overlay maps it to screen px with the same `pageOrigin + p ×
 * zoom` transform the stage uses, so chrome lands exactly on the content.
 */

export const RESIZE_HANDLES: ResizeHandle[] = [
  "top-left",
  "top",
  "top-right",
  "right",
  "bottom-right",
  "bottom",
  "bottom-left",
  "left"
];

const HANDLE_SIZE = 8;
const ROTATE_OFFSET = 22;

export interface SelectionOverlayProps {
  /** Selected node box + rotation in descriptor space (null = no selection). */
  selection: { box: Box; rotation: number } | null;
  /** Direct children of a selected container, for the labeled-container chrome. */
  containerChildren?: Box[];
  /** Optional container label ("Hero · 3 inside"). */
  containerLabel?: string;
  /** Live marquee rect in descriptor space (null when not marqueeing). */
  marquee?: Box | null;
  pageOrigin: { x: number; y: number };
  zoom: number;
  /** Whether to show resize/rotate handles (false for layout-managed nodes). */
  showHandles?: boolean;
}

export function SelectionOverlay({
  selection,
  containerChildren = [],
  containerLabel,
  marquee = null,
  pageOrigin,
  zoom,
  showHandles = true
}: SelectionOverlayProps) {
  const toScreen = (p: { x: number; y: number }) => ({
    x: pageOrigin.x + p.x * zoom,
    y: pageOrigin.y + p.y * zoom
  });

  return (
    <svg
      data-testid="selection-overlay"
      style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "visible" }}
    >
      {containerChildren.map((child, index) => {
        const tl = toScreen(child);
        return (
          <rect
            key={`child-${index}`}
            data-role="container-child"
            x={tl.x}
            y={tl.y}
            width={child.width * zoom}
            height={child.height * zoom}
            fill="none"
            stroke="#256c70"
            strokeWidth={1}
            strokeDasharray="3 3"
            opacity={0.4}
          />
        );
      })}

      {containerLabel && selection ? (
        <ContainerLabel point={toScreen(selection.box)} text={containerLabel} />
      ) : null}

      {selection ? (
        <SelectionBox box={selection.box} rotation={selection.rotation} toScreen={toScreen} />
      ) : null}

      {selection && showHandles
        ? RESIZE_HANDLES.map((handle) => {
            const p = toScreen(handlePoint(selection.box, handle, selection.rotation));
            return (
              <rect
                key={handle}
                data-role="resize-handle"
                data-handle={handle}
                x={p.x - HANDLE_SIZE / 2}
                y={p.y - HANDLE_SIZE / 2}
                width={HANDLE_SIZE}
                height={HANDLE_SIZE}
                fill="#ffffff"
                stroke="#256c70"
                strokeWidth={1.5}
              />
            );
          })
        : null}

      {selection && showHandles ? <RotateHandle selection={selection} toScreen={toScreen} /> : null}

      {marquee ? (
        <rect
          data-role="marquee"
          x={toScreen(marquee).x}
          y={toScreen(marquee).y}
          width={marquee.width * zoom}
          height={marquee.height * zoom}
          fill="#256c70"
          fillOpacity={0.08}
          stroke="#256c70"
          strokeWidth={1}
        />
      ) : null}
    </svg>
  );
}

function SelectionBox({
  box,
  rotation,
  toScreen
}: {
  box: Box;
  rotation: number;
  toScreen: (p: { x: number; y: number }) => { x: number; y: number };
}) {
  // Four corners via handlePoint → a rotated polygon.
  const corners = (["top-left", "top-right", "bottom-right", "bottom-left"] as ResizeHandle[])
    .map((h) => toScreen(handlePoint(box, h, rotation)))
    .map((p) => `${p.x},${p.y}`)
    .join(" ");
  return (
    <polygon
      data-role="selection-box"
      points={corners}
      fill="none"
      stroke="#256c70"
      strokeWidth={1.5}
    />
  );
}

function RotateHandle({
  selection,
  toScreen
}: {
  selection: { box: Box; rotation: number };
  toScreen: (p: { x: number; y: number }) => { x: number; y: number };
}) {
  const top = handlePoint(selection.box, "top", selection.rotation);
  // Push the handle outward along the box's rotated -y axis.
  const rad = (selection.rotation * Math.PI) / 180;
  const out = { x: top.x + Math.sin(rad) * ROTATE_OFFSET, y: top.y - Math.cos(rad) * ROTATE_OFFSET };
  const a = toScreen(top);
  const b = toScreen(out);
  return (
    <g data-role="rotate-handle">
      <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#256c70" strokeWidth={1.5} />
      <circle cx={b.x} cy={b.y} r={HANDLE_SIZE / 2 + 1} fill="#ffffff" stroke="#256c70" strokeWidth={1.5} />
    </g>
  );
}

function ContainerLabel({ point, text }: { point: { x: number; y: number }; text: string }) {
  const width = Math.max(48, Math.min(220, text.length * 6.6 + 12));
  return (
    <g data-role="container-label">
      <rect x={point.x} y={point.y - 18} width={width} height={16} rx={3} fill="#174f52" />
      <text x={point.x + width / 2} y={point.y - 6} fontSize={10} fontWeight={700} fill="#ffffff" textAnchor="middle">
        {text}
      </text>
    </g>
  );
}
