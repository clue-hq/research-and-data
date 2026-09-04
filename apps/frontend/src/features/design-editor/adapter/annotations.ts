import { addressKey, type WebElementAddress, type WebNodeGeometry } from "../engine/webBridge";

/**
 * Slice 2 (rulings R-A1..R-A3): the pure state behind the web canvas's element
 * annotations — one click opens a comment box on the element under the cursor,
 * **Add** stores the note as a numbered chip, and the numbered badge is drawn
 * back into the frame.
 *
 * A reducer rather than a bag of setters because two invariants are worth
 * pinning in one place:
 *
 *  1. The numbering. `nextN` only ever moves forward, so removing chip 1 does
 *     not renumber chip 2 (a badge in the frame and a chip in the composer
 *     would otherwise disagree with what the user just read), and the turn's
 *     prose can refer to "annotation 2" for as long as the session lives.
 *  2. Spec §3.4's draft rule — a comment box you click away from does not throw
 *     away what you typed. The DRAFT therefore lives in `pending.note`, not in
 *     the popover's local state, so the reducer can commit it on its own when
 *     the box is replaced by a click on a different element.
 */

/** One stored annotation: the element it points at, plus what to do about it. */
export interface WebAnnotation {
  n: number;
  address: WebElementAddress;
  name: string;
  note: string;
  pageId: string;
  textLike: boolean;
}

/** The open comment box — an annotation that has not been written yet. Carries
 * the element geometry the popover positions against, and the draft note (see
 * the header: a draft survives a click-away, so it cannot live in the view). */
export interface PendingAnnotation {
  address: WebElementAddress;
  name: string;
  textLike: boolean;
  geometry: WebNodeGeometry;
  pageId: string;
  note: string;
}

export interface AnnotationState {
  items: WebAnnotation[];
  pending: PendingAnnotation | null;
  nextN: number;
}

export type AnnotationAction =
  /** A click reported by the bridge. Born with an empty note — the draft of any
   * box this one replaces is committed first, never carried across. */
  | ({ type: "open" } & Omit<PendingAnnotation, "note">)
  /** The textarea, on every change. */
  | { type: "edit"; note: string }
  /** Escape / the close button: an explicit cancel, draft and all. */
  | { type: "dismiss" }
  /** The Add button, or a click-away with a non-blank draft. Without a `note`
   * the pending draft is what gets stored. */
  | { type: "add"; note?: string }
  | { type: "remove"; n: number }
  | { type: "clear" };

/** Ruling R-A3: session-only. This state lives in React memory for one document
 * and dies with it; the sent turn's context refs are the durable record. */
export const EMPTY_ANNOTATIONS: AnnotationState = {
  items: [],
  pending: null,
  nextN: 1,
};

/** Turn the open box into a numbered annotation. A blank note is not an
 * annotation, so the state (box included) is returned untouched — which is what
 * makes Add inert on an empty box and makes a click-away on one a plain
 * dismiss. */
function commitPending(state: AnnotationState, note: string): AnnotationState {
  const trimmed = note.trim();
  if (!state.pending || trimmed.length === 0) return state;
  const item: WebAnnotation = {
    n: state.nextN,
    note: trimmed,
    address: state.pending.address,
    name: state.pending.name,
    pageId: state.pending.pageId,
    textLike: state.pending.textLike,
  };
  return {
    items: [...state.items, item],
    pending: null,
    nextN: state.nextN + 1,
  };
}

/** Two boxes are "the same box" when they point at the same element on the same
 * page — clicking the element you are already commenting on must keep your
 * half-typed note, not bank it and hand you an empty field. */
function samePending(
  pending: PendingAnnotation,
  next: Omit<PendingAnnotation, "note">,
): boolean {
  return (
    pending.pageId === next.pageId &&
    addressKey(pending.address) === addressKey(next.address)
  );
}

export function annotationsReducer(
  state: AnnotationState,
  action: AnnotationAction,
): AnnotationState {
  switch (action.type) {
    case "open": {
      // Spec §3.4: replacing a box with a non-blank draft STORES that draft
      // first. The click that opens the next box is the same gesture as a
      // click-away from this one, and the two must not disagree.
      if (state.pending && samePending(state.pending, action)) {
        return state;
      }
      const committed = commitPending(state, state.pending?.note ?? "");
      return {
        ...committed,
        pending: {
          address: action.address,
          name: action.name,
          textLike: action.textLike,
          geometry: action.geometry,
          pageId: action.pageId,
          note: "",
        },
      };
    }
    case "edit":
      return state.pending
        ? { ...state, pending: { ...state.pending, note: action.note } }
        : state;
    case "dismiss":
      return { ...state, pending: null };
    case "add":
      return commitPending(state, action.note ?? state.pending?.note ?? "");
    case "remove":
      return { ...state, items: state.items.filter((item) => item.n !== action.n) };
    case "clear":
      return EMPTY_ANNOTATIONS;
  }
}
