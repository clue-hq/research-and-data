"use client";

import { useCallback, useEffect, useRef } from "react";
import {
  inspectorChangeToOperation,
  nextVisibilityMemory,
  type VisibilityMemory,
} from "../adapter/apply";
import {
  addPageOp,
  removePageOp,
  setFragmentTextOverrideOp,
  setPageMetaOp,
  type LoadedWebDocument,
  type WebFragmentTextOverride,
} from "../engine/webDocuments";
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
/**
 * F5 task 19: the manual-edits controller plus the three PAGE writes the web
 * inspector's Page section fires. They sit here, beside the node-write listener,
 * because they are the same write path — one op, through `applyOps`, carrying
 * `base_version`, reloading on success and reporting a refusal in the one inline
 * slot. The only thing that differs is that a page write is addressed by page
 * id, so it comes in as a call rather than through the node-addressed
 * `clue:inspector-property-change` seam.
 */
export interface InspectorWrites extends WebManualEdits {
  /** Rename a page and/or repoint its route (`set_page_meta`). */
  setPageMeta: (pageId: string, meta: { name?: string; route?: string }) => void;
  /** Add an empty page (`add_page`). The caller makes it active afterwards. */
  addPage: (page: { id: string; name: string; route: string }) => void;
  /** Remove a page (`remove_page`). The engine refuses a document's last one. */
  removePage: (pageId: string) => void;
  /** R-A6 (slice 3): set — or clear, with `null` — the human's text override on
   * ONE element inside a cloned section (`set_fragment_text_override`). Same
   * one-op-through-`applyOps` write path as every other inspector edit; the
   * intent tells a set from a take-it-back in the run history. */
  setFragmentTextOverride: (
    pageId: string,
    nodeId: string,
    path: string,
    override: WebFragmentTextOverride | null,
  ) => void;
}

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
}): InspectorWrites {
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

  // F5 task 19: the three page writes. Each is exactly one operation through
  // the SAME `applyOps` every other inspector edit uses — no second write path,
  // no batching, and the intent string names what the user did so the run
  // history reads honestly ("rename_route" only when a route actually moved).
  const setPageMeta = useCallback(
    (pageId: string, meta: { name?: string; route?: string }) => {
      applyOpsRef.current(
        [setPageMetaOp(pageId, meta)],
        meta.route !== undefined ? "rename_route" : "rename_page",
      );
    },
    [],
  );
  const addPage = useCallback((page: { id: string; name: string; route: string }) => {
    applyOpsRef.current([addPageOp(page)], "add_page");
  }, []);
  const removePage = useCallback((pageId: string) => {
    applyOpsRef.current([removePageOp(pageId)], "remove_page");
  }, []);
  const setFragmentTextOverride = useCallback(
    (
      pageId: string,
      nodeId: string,
      path: string,
      override: WebFragmentTextOverride | null,
    ) => {
      applyOpsRef.current(
        [setFragmentTextOverrideOp(pageId, nodeId, path, override)],
        override ? "clone_text_edit" : "clone_text_clear",
      );
    },
    [],
  );

  return { ...edits, addPage, removePage, setFragmentTextOverride, setPageMeta };
}
