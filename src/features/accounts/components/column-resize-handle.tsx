"use client";

import { useResizableColumn } from "../hooks/use-resizable-column";

export function ColumnResizeHandle({
  label,
  max,
  min,
  onChange,
  onReset,
  width,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (width: number) => void;
  onReset: () => void;
  width: number;
}) {
  const resize = useResizableColumn({
    max,
    min,
    onChange,
    onReset,
    width,
  });

  return (
    <button
      aria-label={`Resize ${label} column`}
      aria-orientation="vertical"
      aria-valuemax={max}
      aria-valuemin={min}
      aria-valuenow={width}
      className={`group/resize absolute inset-y-0 -right-1 z-40 w-2 cursor-col-resize touch-none outline-none ${
        resize.resizing ? "is-resizing" : ""
      }`}
      onDoubleClick={resize.onDoubleClick}
      onKeyDown={resize.onKeyDown}
      onPointerDown={resize.onPointerDown}
      role="separator"
      type="button"
    >
      <span
        aria-hidden="true"
        className={`absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors group-hover/resize:bg-[#87a8ff] group-focus-visible/resize:bg-[#567ee8] ${
          resize.resizing ? "bg-[#567ee8]" : "bg-transparent"
        }`}
      />
    </button>
  );
}
