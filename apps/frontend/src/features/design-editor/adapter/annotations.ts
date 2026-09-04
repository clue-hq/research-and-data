import type { WebElementAddress, WebNodeGeometry } from "../engine/webBridge";

/**
 * Slice 3 (rulings R-A1..R-A3): the pure state behind the web canvas's element
 * annotations — one click opens a comment box on the element under the cursor,
 * **Add** stores the note as a numbered chip, and the numbered badge is drawn
 * back into the frame.
 *
 * A reducer rather than a bag of setters because the numbering is the invariant
 * worth pinning: `nextN` only ever moves forward, so removing chip 1 does not
 * renumber chip 2 (a badge in the frame and a chip in the composer would
 * otherwise disagree with what the user just read), and the turn's prose can
 * refer to "annotation 2" for as long as the session lives.
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
 * the element geometry the popover positions against. */
export interface PendingAnnotation {
  address: WebElementAddress;
  name: string;
  textLike: boolean;
  geometry: WebNodeGeometry;
  pageId: string;
}

export interface AnnotationState {
  items: WebAnnotation[];
  pending: PendingAnnotation | null;
  nextN: number;
}

export type AnnotationAction =
  | ({ type: "open" } & PendingAnnotation)
  | { type: "dismiss" }
  | { type: "add"; note: string }
  | { type: "remove"; n: number }
  | { type: "clear" };

/** Ruling R-A3: session-only. This state lives in React memory for one document
 * and dies with it; the sent turn's context refs are the durable record. */
export const EMPTY_ANNOTATIONS: AnnotationState = {
  items: [],
  pending: null,
  nextN: 1,
};

export function annotationsReducer(
  state: AnnotationState,
  action: AnnotationAction,
): AnnotationState {
  switch (action.type) {
    case "open":
      return {
        ...state,
        pending: {
          address: action.address,
          name: action.name,
          textLike: action.textLike,
          geometry: action.geometry,
          pageId: action.pageId,
        },
      };
    case "dismiss":
      return { ...state, pending: null };
    case "add": {
      const note = action.note.trim();
      // A blank note is not an annotation — Add is inert and the box stays open,
      // so the click is not silently thrown away.
      if (!state.pending || note.length === 0) return state;
      const item: WebAnnotation = {
        n: state.nextN,
        note,
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
    case "remove":
      return { ...state, items: state.items.filter((item) => item.n !== action.n) };
    case "clear":
      return EMPTY_ANNOTATIONS;
  }
}
