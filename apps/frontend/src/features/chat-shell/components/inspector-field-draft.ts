/**
 * AD4.R (the MVP state model): the two pure decisions a self-drafting typed
 * inspector field makes. They live in this sibling module — not inside the
 * component — so they are testable under `tsx --test` with no DOM.
 *
 * The model: the accepted scene owns the document value; React derives it; a
 * typed field holds a draft ONLY while it is being edited. Nothing here knows
 * about React, the editor, or the write adapters.
 */

/**
 * What the box shows: the draft while one exists, the document value otherwise.
 *
 * A draft of `""` is a real draft (an emptied box shows empty, it does not snap
 * back to the document value) — only `null` means "not being edited".
 */
export function fieldDisplay(draft: string | null, value: string): string {
  return draft ?? value;
}

/**
 * What a blur/Enter writes: the draft, or `null` when there is nothing new to
 * say — either the field was never typed in (`draft === null`) or the draft is
 * already what the document says.
 *
 * The dirty check made structural: **the comparison target is the LIVE document
 * value** — under live hydration it cannot be stale, which is what retires the
 * A27 committed-snapshot pattern (a separately-tracked "last committed" copy
 * that drifted whenever the document moved underneath it).
 *
 * An explicit clear (`draft === ""` against a non-empty value) IS a commit: the
 * write adapter decides what an empty string means for its row (radius: no
 * write; alt text: clear), exactly as it does today.
 */
export function fieldCommit(draft: string | null, value: string): string | null {
  if (draft === null) return null;
  if (draft === value) return null;
  return draft;
}

/**
 * Whether a keypress in a MULTILINE inspector field is its commit chord.
 *
 * `InspectorInput` commits on a bare Enter; a textarea cannot, because the
 * content it edits may legitimately contain newlines and Enter is the only way
 * to type one. So the commit moves to ⌘/Ctrl+Enter and Enter stays a newline —
 * the one deliberate divergence between the two primitives' key contracts.
 * Blur commits either way, and is the path most users take.
 */
export function textareaCommitKey(event: {
  ctrlKey: boolean;
  key: string;
  metaKey: boolean;
}): boolean {
  return event.key === "Enter" && (event.metaKey || event.ctrlKey);
}
