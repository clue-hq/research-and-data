"use client";

import { useEffect, useRef, useState } from "react";

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function useResizableColumn({
  max,
  min,
  onChange,
  onReset,
  step = 16,
  width,
}: {
  max: number;
  min: number;
  onChange: (width: number) => void;
  onReset: () => void;
  step?: number;
  width: number;
}) {
  const [resizing, setResizing] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(
    () => () => {
      cleanupRef.current?.();
    },
    [],
  );

  function onPointerDown(
    event: React.PointerEvent<HTMLButtonElement>,
  ) {
    if (event.button !== 0) return;

    event.preventDefault();
    cleanupRef.current?.();

    const startX = event.clientX;
    const startWidth = width;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    setResizing(true);

    function onPointerMove(pointerEvent: PointerEvent) {
      onChange(
        clamp(startWidth + pointerEvent.clientX - startX, min, max),
      );
    }

    function finishResize() {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", finishResize);
      window.removeEventListener("pointercancel", finishResize);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      cleanupRef.current = null;
      setResizing(false);
    }

    cleanupRef.current = finishResize;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", finishResize);
    window.addEventListener("pointercancel", finishResize);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    let nextWidth: number | null = null;

    if (event.key === "ArrowLeft") nextWidth = width - step;
    if (event.key === "ArrowRight") nextWidth = width + step;
    if (event.key === "Home") nextWidth = min;
    if (event.key === "End") nextWidth = max;

    if (nextWidth === null) return;
    event.preventDefault();
    onChange(clamp(nextWidth, min, max));
  }

  return {
    onDoubleClick: onReset,
    onKeyDown,
    onPointerDown,
    resizing,
  };
}
