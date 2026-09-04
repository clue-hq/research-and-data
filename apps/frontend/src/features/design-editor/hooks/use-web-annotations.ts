"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  annotationsReducer,
  EMPTY_ANNOTATIONS,
  type AnnotationState,
  type PendingAnnotation,
  type WebAnnotation,
} from "../adapter/annotations";

export interface WebAnnotationsSession {
  state: AnnotationState;
  /** A click reported by the bridge opens the comment box on that element.
   * Spec §3.4: a non-blank draft in the box this replaces is banked first (the
   * reducer's `open` case), so clicking a second element never loses the first
   * note. Re-clicking the SAME element keeps the draft. */
  open: (pending: Omit<PendingAnnotation, "pageId" | "note">) => void;
  /** The textarea, on every keystroke — the draft is reducer state so it can
   * survive the box being replaced. */
  editNote: (note: string) => void;
  /** An explicit cancel: the draft goes with it. */
  dismiss: () => void;
  /** Commit the open box. Returns the stored annotation so a caller that
   * submits immediately ("Send to chat", task 7) has the numbered record
   * without waiting a render for the reduced state. `null` for a blank note. */
  add: (note?: string) => WebAnnotation | null;
  remove: (n: number) => void;
  clear: () => void;
  /** The badge map for one page, as the frame's `annotations` message wants
   * it. Page-scoped because an address only resolves in the page it was taken
   * on — a badge for another page would silently land on whatever element
   * happens to sit at the same path here. */
  itemsForPage: (pageId: string) => { address: WebAnnotation["address"]; n: number }[];
}

/**
 * Slice 2 (ruling R-A3): the web canvas's annotations, for ONE document, for
 * ONE session. They live in React memory and die with the document — a reload
 * or a document switch drops them, and the sent turn's context refs are the
 * durable record. Nothing here is persisted or fetched.
 */
export function useWebAnnotations(
  documentId: string | null,
  pageId: string | null,
): WebAnnotationsSession {
  const [state, dispatch] = useReducer(annotationsReducer, EMPTY_ANNOTATIONS);

  // R-A3: a document switch drops everything. The reset is a passive effect
  // rather than a render-time derivation because the state has to survive an
  // ordinary re-render of the SAME document (a page switch, a write reload)
  // and only a genuine change of owner may empty it.
  const owner = useRef(documentId);
  useEffect(() => {
    if (owner.current !== documentId) {
      owner.current = documentId;
      dispatch({ type: "clear" });
    }
  }, [documentId]);

  const open = useCallback(
    (pending: Omit<PendingAnnotation, "pageId" | "note">) => {
      // No active page means no resolvable address — the click is dropped
      // rather than stored against a page the badge could never be drawn on.
      if (pageId) dispatch({ type: "open", ...pending, pageId });
    },
    [pageId],
  );

  const pending = state.pending;
  const nextN = state.nextN;
  const add = useCallback(
    (note?: string): WebAnnotation | null => {
      // No argument = store the pending draft (the click-away path); an
      // argument = what the Add button had on screen. Same precedence as the
      // reducer's, so the returned record and the stored one cannot disagree.
      const trimmed = (note ?? pending?.note ?? "").trim();
      dispatch({ type: "add", note });
      if (!pending || trimmed.length === 0) return null;
      return {
        n: nextN,
        note: trimmed,
        address: pending.address,
        name: pending.name,
        pageId: pending.pageId,
        textLike: pending.textLike,
      };
    },
    [nextN, pending],
  );

  const editNote = useCallback((note: string) => dispatch({ type: "edit", note }), []);
  const dismiss = useCallback(() => dispatch({ type: "dismiss" }), []);
  const remove = useCallback((n: number) => dispatch({ type: "remove", n }), []);
  const clear = useCallback(() => dispatch({ type: "clear" }), []);

  const items = state.items;
  const itemsForPage = useCallback(
    (page: string) =>
      items
        .filter((item) => item.pageId === page)
        .map((item) => ({ address: item.address, n: item.n })),
    [items],
  );

  return { state, open, editNote, dismiss, add, remove, clear, itemsForPage };
}
