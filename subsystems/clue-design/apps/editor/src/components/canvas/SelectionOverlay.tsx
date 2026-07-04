"use client";

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { SnapGuide } from "@/engine/canvasOperations";
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
/** Smart-guide accent — Moda's alternate-object-selection magenta
 * (`--color-accent-magenta-selection`), reserved for guides so they read as
 * a distinct signal from the teal selection chrome. */
const GUIDE_COLOR = "#f052cf";

export interface SelectionOverlayProps {
  /** Selected node box + rotation in descriptor space (null = no selection). */
  selection: { box: Box; rotation: number } | null;
  /** Non-primary members of a multi-selection (shift/Cmd+click). Drawn as
   * plain outlines with no handles — they are agent edit targets, not the
   * active transform target. */
  secondarySelections?: Array<{ box: Box; rotation: number }>;
  /** Hovered hit target in descriptor space. Hover chrome is intentionally DOM/SVG-only. */
  hover?: { box: Box; rotation: number } | null;
  /** Direct children of a selected container, for the labeled-container chrome. */
  containerChildren?: Box[];
  /** Optional container label ("Hero · 3 inside"). */
  containerLabel?: string;
  /** Live marquee rect in descriptor space (null when not marqueeing). */
  marquee?: Box | null;
  /** Active snap guides in descriptor space, engaged only while a drag/resize
   * is currently snapped; empty otherwise. */
  guides?: SnapGuide[];
  pageOrigin: { x: number; y: number };
  zoom: number;
  /** Whether to show resize/rotate handles (false for layout-managed nodes). */
  showHandles?: boolean;
  /** Human-readable reason shown when direct geometry handles are suppressed. */
  disabledReason?: string | null;
  /** Slot keys bound to the selected node; used for subtle selected-node chrome. */
  slotKeys?: string[];
  /** Focused diagnostics relevant to the selected node/artboard. */
  diagnosticCounts?: { errors: number; warnings: number };
  /** Normalized 0..1 focal point of a selected image node; null = no focal dot. */
  focal?: { x: number; y: number } | null;
  /** Commit a new focal point (drag end); only wired for image nodes. */
  onFocalChange?: (focal: { x: number; y: number }) => void;
}

export function SelectionOverlay({
  selection,
  secondarySelections = [],
  hover = null,
  containerChildren = [],
  containerLabel,
  marquee = null,
  guides = [],
  pageOrigin,
  zoom,
  showHandles = true,
  disabledReason = null,
  slotKeys = [],
  diagnosticCounts = { errors: 0, warnings: 0 },
  focal = null,
  onFocalChange
}: SelectionOverlayProps) {
  const toScreen = (p: { x: number; y: number }) => ({
    x: pageOrigin.x + p.x * zoom,
    y: pageOrigin.y + p.y * zoom
  });
  const hasSlotKeys = slotKeys.length > 0;
  const diagnosticTone =
    diagnosticCounts.errors > 0 ? "error" : diagnosticCounts.warnings > 0 ? "warning" : null;

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

      {hover ? (
        <SelectionBox
          box={hover.box}
          rotation={hover.rotation}
          toScreen={toScreen}
          role="hover-box"
          stroke="#5bb6ff"
          strokeWidth={1}
          strokeDasharray="4 3"
          opacity={0.8}
        />
      ) : null}

      {secondarySelections.map((secondary, index) => (
        <SelectionBox
          key={`secondary-${index}`}
          box={secondary.box}
          rotation={secondary.rotation}
          toScreen={toScreen}
          role="secondary-selection-box"
          stroke="#256c70"
          strokeWidth={1.5}
          strokeDasharray="5 3"
          opacity={0.8}
        />
      ))}

      {selection ? (
        <SelectionBox
          box={selection.box}
          rotation={selection.rotation}
          toScreen={toScreen}
          role="selection-box"
          stroke={diagnosticTone === "error" ? "#ef4444" : diagnosticTone === "warning" ? "#f59e0b" : "#256c70"}
          strokeWidth={diagnosticTone ? 2 : 1.5}
        />
      ) : null}

      {selection && hasSlotKeys ? (
        <SlotBoundAccent selection={selection} toScreen={toScreen} slotCount={slotKeys.length} />
      ) : null}

      {selection && diagnosticTone ? (
        <DiagnosticBadge selection={selection} toScreen={toScreen} counts={diagnosticCounts} tone={diagnosticTone} />
      ) : null}

      {selection && !showHandles && disabledReason ? (
        <DisabledNotice point={toScreen(selection.box)} text={disabledReason} />
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

      {selection && focal && onFocalChange ? (
        <FocalHandle
          box={selection.box}
          focal={focal}
          pageOrigin={pageOrigin}
          zoom={zoom}
          toScreen={toScreen}
          onFocalChange={onFocalChange}
        />
      ) : null}

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

      {guides.map((guide, index) => (
        <SnapGuideLine key={`guide-${guide.axis}-${index}`} guide={guide} toScreen={toScreen} />
      ))}
    </svg>
  );
}

function SnapGuideLine({
  guide,
  toScreen
}: {
  guide: SnapGuide;
  toScreen: (p: { x: number; y: number }) => { x: number; y: number };
}) {
  const a =
    guide.axis === "x"
      ? toScreen({ x: guide.position, y: guide.from })
      : toScreen({ x: guide.from, y: guide.position });
  const b =
    guide.axis === "x"
      ? toScreen({ x: guide.position, y: guide.to })
      : toScreen({ x: guide.to, y: guide.position });
  return (
    <line
      data-role="snap-guide"
      data-axis={guide.axis}
      x1={a.x}
      y1={a.y}
      x2={b.x}
      y2={b.y}
      stroke={GUIDE_COLOR}
      strokeWidth={1}
    />
  );
}

function SelectionBox({
  box,
  rotation,
  toScreen,
  role,
  stroke,
  strokeWidth,
  strokeDasharray,
  opacity
}: {
  box: Box;
  rotation: number;
  toScreen: (p: { x: number; y: number }) => { x: number; y: number };
  role: string;
  stroke: string;
  strokeWidth: number;
  strokeDasharray?: string;
  opacity?: number;
}) {
  // Four corners via handlePoint → a rotated polygon.
  const corners = (["top-left", "top-right", "bottom-right", "bottom-left"] as ResizeHandle[])
    .map((h) => toScreen(handlePoint(box, h, rotation)))
    .map((p) => `${p.x},${p.y}`)
    .join(" ");
  return (
    <polygon
      data-role={role}
      points={corners}
      fill="none"
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeDasharray={strokeDasharray}
      opacity={opacity}
    />
  );
}

/**
 * Convert a screen point (SVG-local px) to a normalized 0..1 focal point within a
 * descriptor-space box, using the overlay's `pageOrigin + p × zoom` transform. Pure
 * + exported so the drag math is unit-tested without a DOM. Mirrors the cover/focal
 * crop semantics the renderers use (focal is the point kept in view).
 */
export function focalFromScreenPoint(
  point: { x: number; y: number },
  box: Box,
  pageOrigin: { x: number; y: number },
  zoom: number
): { x: number; y: number } {
  const descriptorX = zoom !== 0 ? (point.x - pageOrigin.x) / zoom : box.x;
  const descriptorY = zoom !== 0 ? (point.y - pageOrigin.y) / zoom : box.y;
  const clamp01 = (value: number) => Math.min(1, Math.max(0, value));
  return {
    x: box.width > 0 ? clamp01((descriptorX - box.x) / box.width) : 0.5,
    y: box.height > 0 ? clamp01((descriptorY - box.y) / box.height) : 0.5
  };
}

function FocalHandle({
  box,
  focal,
  pageOrigin,
  zoom,
  toScreen,
  onFocalChange
}: {
  box: Box;
  focal: { x: number; y: number };
  pageOrigin: { x: number; y: number };
  zoom: number;
  toScreen: (p: { x: number; y: number }) => { x: number; y: number };
  onFocalChange: (focal: { x: number; y: number }) => void;
}) {
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const draggingRef = useRef(false);
  const latestRef = useRef(focal);
  const current = drag ?? focal;
  const point = toScreen({ x: box.x + box.width * current.x, y: box.y + box.height * current.y });

  const svgLocal = (event: ReactPointerEvent<SVGCircleElement>) => {
    const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) };
  };
  const compute = (event: ReactPointerEvent<SVGCircleElement>) => {
    const next = focalFromScreenPoint(svgLocal(event), box, pageOrigin, zoom);
    latestRef.current = next;
    return next;
  };

  return (
    <g data-role="focal-point" aria-label="Image focal point">
      <circle cx={point.x} cy={point.y} r={11} fill="#256c70" fillOpacity={0.18} stroke="#256c70" strokeWidth={1} />
      <circle
        data-testid="focal-handle"
        cx={point.x}
        cy={point.y}
        r={6}
        fill="#256c70"
        stroke="#ffffff"
        strokeWidth={2}
        style={{ pointerEvents: "auto", cursor: "grab" }}
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
          draggingRef.current = true;
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setDrag(compute(event));
        }}
        onPointerMove={(event) => {
          if (draggingRef.current) {
            setDrag(compute(event));
          }
        }}
        onPointerUp={(event) => {
          if (!draggingRef.current) {
            return;
          }
          draggingRef.current = false;
          event.currentTarget.releasePointerCapture?.(event.pointerId);
          onFocalChange(latestRef.current);
          setDrag(null);
        }}
      />
    </g>
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

function SlotBoundAccent({
  selection,
  toScreen,
  slotCount
}: {
  selection: { box: Box; rotation: number };
  toScreen: (p: { x: number; y: number }) => { x: number; y: number };
  slotCount: number;
}) {
  const topRight = toScreen(handlePoint(selection.box, "top-right", selection.rotation));
  const label = slotCount === 1 ? "slot" : `${slotCount} slots`;
  const width = Math.max(38, Math.min(86, label.length * 6.4 + 14));
  return (
    <g data-role="slot-bound-accent">
      <circle cx={topRight.x} cy={topRight.y} r={5} fill="#7c3aed" stroke="#ffffff" strokeWidth={1.5} />
      <rect x={topRight.x + 8} y={topRight.y - 9} width={width} height={18} rx={4} fill="#35205f" opacity={0.92} />
      <text x={topRight.x + 8 + width / 2} y={topRight.y + 4} fontSize={10} fontWeight={700} fill="#ede9fe" textAnchor="middle">
        {label}
      </text>
    </g>
  );
}

function DiagnosticBadge({
  selection,
  toScreen,
  counts,
  tone
}: {
  selection: { box: Box; rotation: number };
  toScreen: (p: { x: number; y: number }) => { x: number; y: number };
  counts: { errors: number; warnings: number };
  tone: "error" | "warning";
}) {
  const topLeft = toScreen(handlePoint(selection.box, "top-left", selection.rotation));
  const total = counts.errors + counts.warnings;
  const fill = tone === "error" ? "#b91c1c" : "#b45309";
  return (
    <g data-role="diagnostic-badge">
      <circle cx={topLeft.x - 8} cy={topLeft.y - 8} r={8} fill={fill} stroke="#ffffff" strokeWidth={1.5} />
      <text x={topLeft.x - 8} y={topLeft.y - 4.5} fontSize={9} fontWeight={800} fill="#ffffff" textAnchor="middle">
        {total}
      </text>
    </g>
  );
}

function DisabledNotice({ point, text }: { point: { x: number; y: number }; text: string }) {
  const trimmed = text.length > 86 ? `${text.slice(0, 83)}...` : text;
  const width = Math.max(160, Math.min(420, trimmed.length * 5.8 + 18));
  return (
    <g data-role="disabled-handle-notice">
      <rect x={point.x} y={point.y + 8} width={width} height={20} rx={4} fill="#30343a" opacity={0.94} />
      <text x={point.x + 9} y={point.y + 22} fontSize={10} fontWeight={650} fill="#f3f4f6">
        {trimmed}
      </text>
    </g>
  );
}
