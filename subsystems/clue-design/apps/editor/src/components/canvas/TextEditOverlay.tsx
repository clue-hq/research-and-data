"use client";

import { useEffect, useRef, useState } from "react";
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

  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.focus();
      el.select();
    }
  }, []);

  const left = pageOrigin.x + box.x * zoom;
  const top = pageOrigin.y + box.y * zoom;

  return (
    <textarea
      ref={ref}
      data-testid="text-edit-overlay"
      value={value}
      onChange={(event) => setValue(event.target.value)}
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
        height: Math.max(8, box.height * zoom),
        transform: rotation ? `rotate(${rotation}deg)` : undefined,
        transformOrigin: "top left",
        margin: 0,
        padding: 0,
        border: "1px solid #256c70",
        outline: "none",
        resize: "none",
        overflow: "hidden",
        background: "#ffffff",
        color: style.color,
        fontFamily: style.fontFamily,
        fontSize: style.fontSize * zoom,
        fontWeight: style.fontWeight,
        textAlign: style.align === "justify" ? "justify" : style.align,
        lineHeight: String(style.lineHeight),
        letterSpacing: `${style.letterSpacing * zoom}px`,
        boxSizing: "border-box"
      }}
    />
  );
}
