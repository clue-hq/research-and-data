"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Box } from "@/engine/transformerMath";

/**
 * Wave 3 C4: the text edit surface. CanvasKit (like Konva) cannot host a live
 * caret, so editing happens in a DOM `<textarea>` positioned over the text
 * node and styled to match it. Commit on blur (or ⌘/Ctrl+Enter); Escape
 * cancels. The host hides the CanvasKit text under it and writes an
 * `updateTextNode` operation on commit.
 *
 * Geometry is descriptor space; the overlay maps it to screen with the same
 * `pageOrigin + p × zoom` transform the stage uses, and applies the node's
 * rotation about its top-left (the renderer's pivot).
 */

export interface TextEditStyle {
  fontFamily: string;
  /** Descriptor-space font size (canvas px at zoom 1). */
  fontSize: number;
  fontWeight: number;
  align: "left" | "center" | "right" | "justify";
  /** A7a: vertical placement — drives a computed `paddingTop` so the textarea
   * visually matches the painted position for center/bottom text. */
  valign: "top" | "center" | "bottom";
  /** A7b: block italic → the textarea's `font-style` so the edit surface matches
   * the painted glyphs (block-level only; spans don't render in the overlay). */
  italic: boolean;
  lineHeight: number;
  letterSpacing: number;
  color: string;
}

export interface TextEditOverlayProps {
  box: Box;
  rotation: number;
  content: string;
  style: TextEditStyle;
  pageOrigin: { x: number; y: number };
  zoom: number;
  onCommit: (content: string) => void;
  onCancel: () => void;
}

export function TextEditOverlay({
  box,
  rotation,
  content,
  style,
  pageOrigin,
  zoom,
  onCommit,
  onCancel
}: TextEditOverlayProps) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [value, setValue] = useState(content);
  // Guard so an Escape-driven blur does not also commit.
  const cancelledRef = useRef(false);

  // A7a: match the painted vertical position with a computed top padding. The
  // same clamped-slack formula as the canvas legs: content lives at
  // `max(boxH - contentH, 0) * factor`, factor top=0 / center=0.5 / bottom=1.
  // `scrollHeight` tracks live content, so recomputing on input keeps the
  // caret aligned as the text grows/shrinks; padding never goes negative
  // (clamp at 0), so overflowing content keeps today's top-anchored scroll.
  const boxHeightPx = Math.max(8, box.height * zoom);
  const paddingRef = useRef(0);
  const [paddingTop, setPaddingTop] = useState(0);

  const recomputePadding = useCallback(() => {
    const el = ref.current;
    if (!el) {
      return;
    }
    const factor = style.valign === "center" ? 0.5 : style.valign === "bottom" ? 1 : 0;
    if (factor === 0) {
      paddingRef.current = 0;
      setPaddingTop(0);
      return;
    }
    // `scrollHeight` floors at clientHeight, so content shorter than the box
    // reads back as the box height and the padding would stay 0 forever. Zero
    // the height for the read to get the true content height (scrollHeight
    // then reports content plus the padding applied last pass — subtract it),
    // then restore the height before the browser paints.
    const prevHeight = el.style.height;
    el.style.height = "0px";
    const contentHeight = el.scrollHeight - paddingRef.current;
    el.style.height = prevHeight;
    const next = Math.max((boxHeightPx - contentHeight) * factor, 0);
    paddingRef.current = next;
    setPaddingTop(next);
  }, [style.valign, boxHeightPx]);

  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.focus();
      el.select();
    }
    recomputePadding();
  }, [recomputePadding]);

  const left = pageOrigin.x + box.x * zoom;
  const top = pageOrigin.y + box.y * zoom;

  return (
    <textarea
      ref={ref}
      data-testid="text-edit-overlay"
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
        recomputePadding();
      }}
      onPointerDown={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onBlur={() => {
        if (!cancelledRef.current) {
          onCommit(value);
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          cancelledRef.current = true;
          onCancel();
        } else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          onCommit(value);
        }
        event.stopPropagation();
      }}
      style={{
        position: "absolute",
        left,
        top,
        width: Math.max(8, box.width * zoom),
        height: boxHeightPx,
        transform: rotation ? `rotate(${rotation}deg)` : undefined,
        transformOrigin: "top left",
        margin: 0,
        // A7a: only the top pads (bottom/left/right stay 0) so center/bottom
        // text sits where the canvas paints it; clamped at 0 for overflow.
        padding: 0,
        paddingTop,
        border: "1px solid #256c70",
        outline: "none",
        resize: "none",
        overflow: "hidden",
        background: "#ffffff",
        color: style.color,
        fontFamily: style.fontFamily,
        fontSize: style.fontSize * zoom,
        fontWeight: style.fontWeight,
        fontStyle: style.italic ? "italic" : "normal",
        textAlign: style.align === "justify" ? "justify" : style.align,
        lineHeight: String(style.lineHeight),
        letterSpacing: `${style.letterSpacing * zoom}px`,
        boxSizing: "border-box"
      }}
    />
  );
}
