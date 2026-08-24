import type { TextNode, TextSpan } from "../engine/scene/contracts";
import {
  applyStyleToRange,
  formatStateForRange,
  reconcileSpansForReplacement,
  remapSpansByDiff,
  utf16ToByteOffset,
  type ByteRange,
  type RangeFormatState,
  type StylePatch,
} from "../engine/scene/textSpans";

/**
 * Rung C of the rich-text ladder (`docs/superpowers/plans/2026-08-24-rich-text-editing.md`):
 * the caret session's SPAN state, as pure functions.
 *
 * Rung B's session held one thing — the draft string. Rung C makes it a pair:
 * the draft AND the spans vector the range toolbar is authoring, maintained
 * across every keystroke so styling stays attached to the text it was applied
 * to. All of that reasoning lives here rather than in the overlay component,
 * for this lane's standing reason: `tsx --test` cannot render React, so what
 * could be a function IS one.
 *
 * ── THE TWO SPACES, AND THE ONE SEAM ─────────────────────────────────────
 * A textarea speaks UTF-16 (`selectionStart`, `selectionEnd`, `beforeinput`
 * offsets). The engine's spans are UTF-8 BYTE offsets into the STORED content.
 * Every function here that takes a UI offset crosses that seam through
 * `textSpans.ts`'s `utf16ToByteOffset` (which snaps a mid-surrogate index LEFT)
 * before any span math runs. No byte offset ever leaves this module for the
 * DOM, and no UTF-16 index ever reaches the engine.
 *
 * ── THE TWO RECONCILIATION PATHS, AND WHY BOTH EXIST ─────────────────────
 * {@link textEditSessionAfterReplacement} is the TRACKED path: `beforeinput`
 * named the exact range being replaced, so a span that strictly surrounds it
 * absorbs the typed text — typing inside a bold word stays bold, like any real
 * editor. {@link textEditSessionResync} is the UNTRACKED one: an autofill, an
 * IME commit, or any mutation whose `beforeinput` this module refused to place
 * is recovered by prefix/suffix diff, which never guesses what happened in the
 * middle. {@link textEditSessionAfterInput} is the arbiter — it trusts a
 * prediction only when the DOM's own value proves it right.
 */

/** The live session: what the textarea shows, and the spans riding it. */
export interface TextEditSession {
  content: string;
  spans: TextSpan[];
}

/** A textarea selection, in the UTF-16 code units it reports. */
export interface TextEditSelection {
  start: number;
  end: number;
}

/** One contiguous replacement, in UTF-16 units over the session's content —
 * the shape a `beforeinput` event reduces to. */
export interface TextEditReplacement {
  start: number;
  end: number;
  text: string;
}

/**
 * The `inputType`s that insert their event `data` verbatim. Anything not named
 * here (or in the two sets below) is deliberately NOT placed: see
 * {@link textEditReplacement}.
 */
const DATA_INSERTS = new Set([
  "insertText",
  "insertFromPaste",
  "insertFromDrop",
  "insertFromYank",
  "insertReplacementText",
  "insertCompositionText",
  "insertTranspose",
]);

/** The `inputType`s that insert a newline. The overlay's plain Enter is one of
 * these — multiline content is real (rung A's `InspectorTextArea` takes the
 * same position). */
const NEWLINE_INSERTS = new Set(["insertLineBreak", "insertParagraph"]);

/** Deletes whose range is either the live selection or, for a caret, exactly
 * one code point in the named direction. */
const DIRECTIONAL_DELETES = new Set([
  "deleteContentBackward",
  "deleteContentForward",
]);

/** Deletes that can only mean "the selected range" — a caret gives them
 * nothing to act on, so a collapsed one is untracked. */
const RANGE_DELETES = new Set(["deleteByCut", "deleteByDrag", "deleteContent"]);

/** Order a reported selection and clamp it into the content. */
function orderedSelection(
  content: string,
  selection: TextEditSelection,
): [number, number] {
  const limit = content.length;
  const low = Math.max(0, Math.min(limit, Math.min(selection.start, selection.end)));
  const high = Math.max(0, Math.min(limit, Math.max(selection.start, selection.end)));
  return [low, high];
}

/** One code point to the left of `index`, in UTF-16 units — never half a
 * surrogate pair. */
function codePointStartBefore(content: string, index: number): number {
  if (index <= 0) return 0;
  const previous = content.codePointAt(index - 2);
  return previous !== undefined && previous > 0xffff ? index - 2 : index - 1;
}

/** One code point to the right of `index`, in UTF-16 units. */
function codePointEndAfter(content: string, index: number): number {
  if (index >= content.length) return content.length;
  const current = content.codePointAt(index);
  return current !== undefined && current > 0xffff ? index + 2 : index + 1;
}

/**
 * One `beforeinput` event → the contiguous replacement it is about to make, or
 * `null` when this module cannot say where the change lands.
 *
 * `targetRange` — the browser's own `getTargetRanges()[0]`, converted to the
 * textarea's own offsets by the caller — OUTRANKS the reported selection
 * whenever it is offered, because it states where the change is actually
 * landing and an IME's reported selection need not.
 *
 * NULL IS A FIRST-CLASS ANSWER, not a failure: a `deleteWordBackward`, a
 * `historyUndo`, a composition with no data — none of them name a range, and
 * inventing one would drag styling onto text it was never applied to. The
 * caller answers null by resyncing off the DOM's own value
 * ({@link textEditSessionResync}), which is conservative by contract.
 */
export function textEditReplacement({
  content,
  data,
  inputType,
  selection,
  targetRange,
}: {
  content: string;
  data: string | null;
  inputType: string;
  selection: TextEditSelection;
  /** `getTargetRanges()[0]` in the textarea's UTF-16 offsets, or null. */
  targetRange: TextEditSelection | null;
}): TextEditReplacement | null {
  const [selectionStart, selectionEnd] = orderedSelection(content, selection);
  const [rangeStart, rangeEnd] = targetRange
    ? orderedSelection(content, targetRange)
    : [selectionStart, selectionEnd];

  if (DATA_INSERTS.has(inputType)) {
    // A composition/replacement event with no data at all says nothing about
    // what will be there afterwards — the diff recovers it.
    return data === null
      ? null
      : { start: rangeStart, end: rangeEnd, text: data };
  }
  if (NEWLINE_INSERTS.has(inputType)) {
    return { start: rangeStart, end: rangeEnd, text: "\n" };
  }
  if (RANGE_DELETES.has(inputType)) {
    return rangeStart === rangeEnd
      ? null
      : { start: rangeStart, end: rangeEnd, text: "" };
  }
  if (DIRECTIONAL_DELETES.has(inputType)) {
    if (rangeStart !== rangeEnd) {
      return { start: rangeStart, end: rangeEnd, text: "" };
    }
    // A caret: the browser deletes exactly one code point, so this must too —
    // half a surrogate pair is not a deletion any string can hold.
    return inputType === "deleteContentBackward"
      ? {
          start: codePointStartBefore(content, rangeStart),
          end: rangeEnd,
          text: "",
        }
      : {
          start: rangeStart,
          end: codePointEndAfter(content, rangeEnd),
          text: "",
        };
  }
  return null;
}

/**
 * The TRACKED transition: apply a placed replacement to the session, moving the
 * spans with the text they are attached to.
 *
 * The new content comes back from `reconcileSpansForReplacement` rather than
 * being recomputed here — it splices in BYTE space, and re-deriving it in
 * UTF-16 space would be a second implementation of the same edit, free to
 * disagree with the offsets its spans were computed against.
 */
export function textEditSessionAfterReplacement(
  session: TextEditSession,
  replacement: TextEditReplacement,
): TextEditSession {
  return reconcileSpansForReplacement(
    session.content,
    session.spans,
    utf16ToByteOffset(session.content, replacement.start),
    utf16ToByteOffset(session.content, replacement.end),
    replacement.text,
  );
}

/**
 * The UNTRACKED fallback: the textarea now holds `content` and nobody can say
 * how it got there, so the spans are remapped by prefix/suffix diff — edges
 * that survived keep their styling, the changed middle takes the node's own.
 *
 * An identical string returns the SAME session object, so a spurious `input`
 * event cannot churn React state.
 */
export function textEditSessionResync(
  session: TextEditSession,
  content: string,
): TextEditSession {
  if (content === session.content) {
    return session;
  }
  return {
    content,
    spans: remapSpansByDiff(session.content, content, session.spans),
  };
}

/**
 * The arbiter, run on every `input` event: take the tracked prediction only if
 * the value the textarea actually holds is the one it predicted; otherwise fall
 * back to the diff.
 *
 * This is what makes the tracked path SAFE to be optimistic. A prediction that
 * matched byte-for-byte cannot have mis-placed its spans (the same edit
 * produced both); one that did not match is discarded whole, rather than
 * patched up.
 */
export function textEditSessionAfterInput(
  session: TextEditSession,
  prediction: TextEditSession | null,
  content: string,
): TextEditSession {
  if (prediction && prediction.content === content) {
    return prediction;
  }
  return textEditSessionResync(session, content);
}

/**
 * The session's node as it currently reads: the STORED text kind wearing the
 * live draft and the working spans.
 *
 * Every span read and write goes through this, because both
 * `formatStateForRange` and `applyStyleToRange` resolve override semantics
 * against the NODE's own base (a span whose weight equals the node's is no
 * override at all), and they must resolve against the string the offsets were
 * computed in — the draft, not the stored content it will replace.
 */
export function textEditSessionNode(
  text: TextNode,
  session: TextEditSession,
): TextNode {
  return { ...text, content: session.content, spans: session.spans };
}

/** A textarea selection as the byte range span math runs in. */
export function textEditByteRange(
  session: TextEditSession,
  selection: TextEditSelection,
): ByteRange {
  const [start, end] = orderedSelection(session.content, selection);
  return [
    utf16ToByteOffset(session.content, start),
    utf16ToByteOffset(session.content, end),
  ];
}

/** What the toolbar shows for the live selection (tri-states + the fill). */
export function textEditFormatState(
  text: TextNode,
  session: TextEditSession,
  selection: TextEditSelection,
): RangeFormatState {
  return formatStateForRange(
    textEditSessionNode(text, session),
    textEditByteRange(session, selection),
  );
}

/**
 * The whole new spans vector one formatting action produces.
 *
 * An EMPTY result is a real answer — un-bolding the only bold run leaves a node
 * with no spans at all — and the commit path sends it as `spans: []` rather
 * than reading it as "nothing to write". A collapsed selection applies nothing
 * (the toolbar disables the toggles for one; founder-visible item 4).
 */
export function textEditStyledSpans(
  text: TextNode,
  session: TextEditSession,
  selection: TextEditSelection,
  patch: StylePatch,
): TextSpan[] {
  return applyStyleToRange(
    textEditSessionNode(text, session),
    textEditByteRange(session, selection),
    patch,
  );
}
