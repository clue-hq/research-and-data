"use client";

import { useCallback, useRef, useState, type DragEvent } from "react";
import { dragCarriesFiles } from "../model/file-drag";

/**
 * Drop-target handlers for a pane that accepts files.
 *
 * `active` is driven by a nesting DEPTH, not a boolean: dragging across the
 * pane's children fires `dragleave` on the one you left before `dragenter` on
 * the one you entered, so a plain flag would flicker the outline off and on.
 * Drags that carry no files are ignored entirely — they neither light the
 * target nor have their default prevented, which leaves ordinary text-selection
 * drags in the transcript untouched.
 */
export function useFileDrop({
  enabled,
  onFiles,
}: {
  enabled: boolean;
  onFiles: (files: File[]) => void;
}) {
  const depth = useRef(0);
  const [active, setActive] = useState(false);
  const reset = useCallback(() => {
    depth.current = 0;
    setActive(false);
  }, []);
  const onDragEnter = useCallback(
    (event: DragEvent) => {
      if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
      event.preventDefault();
      depth.current += 1;
      setActive(true);
    },
    [enabled],
  );
  const onDragOver = useCallback(
    (event: DragEvent) => {
      if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    [enabled],
  );
  const onDragLeave = useCallback(
    (event: DragEvent) => {
      if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    },
    [enabled],
  );
  const onDrop = useCallback(
    (event: DragEvent) => {
      if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
      event.preventDefault();
      const files = Array.from(event.dataTransfer.files);
      reset();
      if (files.length) onFiles(files);
    },
    [enabled, onFiles, reset],
  );
  return { active, handlers: { onDragEnter, onDragOver, onDragLeave, onDrop } };
}
