"use client";

import { useCallback, useRef, useState, type DragEvent } from "react";
import {
  dragCarriesFiles,
  filesFromDrop,
  nextDragDepth,
} from "../model/file-drag";

/**
 * Drop-target handlers for a pane that accepts files.
 *
 * `active` is driven by a nesting DEPTH, not a boolean (see `nextDragDepth`,
 * where that rule and its tests live). The hook itself holds only the React
 * wiring: the ref, the flag, and which DOM events map to which transition.
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
      depth.current = nextDragDepth(depth.current, "enter");
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
      depth.current = nextDragDepth(depth.current, "leave");
      if (depth.current === 0) setActive(false);
    },
    [enabled],
  );
  const onDrop = useCallback(
    (event: DragEvent) => {
      if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
      event.preventDefault();
      const files = filesFromDrop(event.dataTransfer);
      reset();
      if (files.length) onFiles(files);
    },
    [enabled, onFiles, reset],
  );
  return { active, handlers: { onDragEnter, onDragOver, onDragLeave, onDrop } };
}
