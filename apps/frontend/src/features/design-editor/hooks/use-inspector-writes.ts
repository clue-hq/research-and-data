"use client";

import { useEffect, useRef } from "react";
import {
  inspectorChangeToOperation,
  nextVisibilityMemory,
  type VisibilityMemory,
} from "../adapter/apply";
import type { LoadedWebDocument } from "../engine/webDocuments";
import type { WebArtifactSelection } from "./use-web-artifact-selection";
import {
  useWebManualEdits,
  type WebManualEdits,
} from "./use-web-manual-edits";

/**
 * W3.2: the write wiring — listens to the inspector's
 * `clue:inspector-property-change` events (the W3.1-addressed seam), maps
 * each addressable change through the pure `inspectorChangeToOperation`
 * adapter, and persists it via the ported manual-edits controller (one
 * in-flight mutation, `base_version` on every apply, 409 → quiet reload +
 * note, 422 → first diagnostic as inline error).
 *
 * The W3.1 null contract is enforced here: an event without a `selectionId`
 * or `documentVersion`, or addressed to a node other than the current
 * selection, is IGNORED — dummy-state interactions can never become writes.
 */
export function useInspectorWrites({
  document,
  documentId,
  onReload,
  selection,
}: {
  document: LoadedWebDocument | null;
  documentId: string | null;
  onReload: () => void;
  selection: WebArtifactSelection | null;
}): WebManualEdits {
  const edits = useWebManualEdits({
    baseVersion: document?.currentVersion ?? null,
    documentId: documentId ?? "",
    onReload,
  });

  // Latest-value refs so the one listener reads current state without
  // re-arming (updated passively per the repo's react-hooks rules).
  const selectionRef = useRef(selection);
  const documentRef = useRef(document);
  const applyOpsRef = useRef(edits.applyOps);
  useEffect(() => {
    applyOpsRef.current = edits.applyOps;
    documentRef.current = document;
    selectionRef.current = selection;
  });

  // W4.9 (row 40): the visibility eye's per-session memory of the display
  // value it displaced, so an un-hide restores what was actually observed and
  // never guesses. A ref, not state: it must not re-arm the listener or
  // re-render, and its lifetime — this mounted editor — IS the "captured in
  // this session" scope the ruling names. `nextVisibilityMemory` owns every
  // decision (see `adapter/apply.ts`); this is just where it lives.
  const visibilityMemoryRef = useRef<VisibilityMemory | null>(null);

  useEffect(() => {
    if (!documentId) return;
    // A different document is a different session for the eye: node ids are
    // page-local, so a capture from the previous document must not be handed
    // to a same-named node here (that would restore an unobserved value).
    visibilityMemoryRef.current = null;
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        artifactId?: unknown;
        documentVersion?: unknown;
        property?: unknown;
        selectionId?: unknown;
        value?: unknown;
      } | null;
      if (!detail || typeof detail.property !== "string") return;
      // W3.1 null contract: not addressable → not a write.
      if (typeof detail.selectionId !== "string") return;
      if (typeof detail.documentVersion !== "number") return;
      const current = selectionRef.current;
      if (!current || current.node.id !== detail.selectionId) return;
      const loaded = documentRef.current;
      const pages = loaded?.webDoc?.pages;
      const page = pages?.find((candidate) =>
        Boolean(candidate.nodes?.[current.node.id]),
      );
      if (!page) return;
      let restoreDisplay: string | null = null;
      if (detail.property === "visible" && typeof detail.value === "boolean") {
        const next = nextVisibilityMemory(
          visibilityMemoryRef.current,
          current.node,
          detail.value,
        );
        visibilityMemoryRef.current = next.memory;
        restoreDisplay = next.restoreDisplay;
      }
      const operation = inspectorChangeToOperation(
        {
          property: detail.property,
          restoreDisplay,
          selectionId: detail.selectionId,
          value: detail.value,
        },
        current.node,
        page.id,
      );
      if (!operation) return;
      applyOpsRef.current([operation], `inspector: ${detail.property}`);
    };
    window.addEventListener("clue:inspector-property-change", onChange);
    return () =>
      window.removeEventListener("clue:inspector-property-change", onChange);
  }, [documentId]);

  // W3.4: the action menu's Undo/Redo (the dummy's own items, dispatching
  // `clue:artifact-action-request`) and their ⌘Z/⇧⌘Z shortcuts bind to the
  // engine's web undo/redo — the ported manual-edits controller already
  // carries both (same discipline: one in-flight, quiet resync on an
  // empty-stack 409). Scope: the engine-owned document stack only, never a
  // general chrome undo.
  const undoRef = useRef(edits.undo);
  const redoRef = useRef(edits.redo);
  useEffect(() => {
    redoRef.current = edits.redo;
    undoRef.current = edits.undo;
  });

  useEffect(() => {
    if (!documentId) return;
    const onAction = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        action?: unknown;
        kind?: unknown;
      } | null;
      if (detail?.kind !== "web") return;
      if (detail.action === "undo") undoRef.current();
      if (detail.action === "redo") redoRef.current();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z")
        return;
      // Native text-editing undo owns focused inputs/contenteditables.
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA")
      )
        return;
      event.preventDefault();
      if (event.shiftKey) redoRef.current();
      else undoRef.current();
    };
    // window, not document: the hook's `document` prop (the loaded web
    // document) shadows the global here; keydown bubbles to window anyway.
    window.addEventListener("clue:artifact-action-request", onAction);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("clue:artifact-action-request", onAction);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [documentId]);

  return edits;
}
