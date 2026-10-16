"use client";

import { useEffect, useRef } from "react";
import { deleteShortcut, planSceneDelete } from "../adapter/scene-delete";
import type { Operation, PageId, Scene } from "../engine/scene/contracts";
import type { SceneWriteGate } from "./use-scene-manual-edits";

/**
 * The Delete key (Backspace on a Mac keyboard) over the scene editor. Every rule
 * is `adapter/scene-delete.ts`'s; this hook binds the key and dispatches, the
 * same split `use-scene-arrange.ts` makes for ⌘G and ⌘].
 *
 * The removal travels `applyOps` — ONE call for the whole selection, so it is one
 * optimistic apply and ONE undo frame, and several selected elements come back
 * with a single ⌘Z.
 */
export interface UseSceneDeleteOptions {
  /** The active design document; the listener arms on it, as ⌘Z does. */
  documentId: string | null;
  scene: Scene | null;
  pageId: PageId | null;
  selectedIds: readonly string[];
  applyOps: (operations: Operation[], intent?: string) => boolean;
  writeGate: () => SceneWriteGate;
  clearMessages: () => void;
  onNote: (message: string) => void;
  /** Called after a delete lands, so an undo does not bring the removed
   * elements back still selected. */
  clearSelection: () => void;
}

function undoKeys(): string {
  if (typeof navigator === "undefined") return "Ctrl+Z";
  return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘Z" : "Ctrl+Z";
}

export function useSceneDelete(options: UseSceneDeleteOptions): void {
  const { documentId } = options;
  // Latest-value ref, written in a passive effect (this repo's react-hooks rule),
  // so the listener keeps one identity while reading current state.
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  useEffect(() => {
    if (!documentId) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!deleteShortcut(event, event.target as HTMLElement | null)) return;
      const deps = optionsRef.current;
      const plan = planSceneDelete(deps.scene, deps.pageId, deps.selectedIds, undoKeys());
      // Nothing selected that the key may delete: leave the key alone.
      if (plan.kind === "none") return;
      event.preventDefault();
      // Asked first, like arrange: the agent-run lock is the refusal that speaks.
      const gate = deps.writeGate();
      if (!gate.allowed) {
        if (gate.note !== null) deps.onNote(gate.note);
        return;
      }
      if (plan.kind === "refuse") {
        deps.clearMessages();
        deps.onNote(plan.note);
        return;
      }
      deps.clearMessages();
      if (!deps.applyOps(plan.operations, "delete")) return;
      deps.clearSelection();
      if (plan.note !== null) deps.onNote(plan.note);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [documentId]);
}
