import assert from "node:assert/strict";
import test from "node:test";
import type {
  Node,
  Paint,
  Scene,
  TextNode,
  TextSpan,
} from "../engine/scene/contracts";
import { HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  textEditByteRange,
  textEditFormatState,
  textEditReplacement,
  textEditSessionAfterInput,
  textEditSessionAfterReplacement,
  textEditSessionAfterStyleCommit,
  textEditSessionEnds,
  textEditSessionNode,
  textEditSessionOperations,
  textEditSessionResync,
  textEditSessionReseed,
  textEditSessionSeed,
  textEditStyledSpans,
  type TextEditSession,
} from "./scene-text-session";

/**
 * Rung C (rich-text plan, 2026-08-24): the pure half of the caret session's
 * SPAN state — what a `beforeinput` event means as a contiguous replacement,
 * how the working spans move across it, how an untracked mutation is recovered,
 * and what the toolbar reads and writes for the live selection.
 *
 * The node under test is AD2.2's harvested `text_proof_stat` — "3.4x faster
 * triage", 18 ASCII bytes, `font_weight: 600` (so the node's own base is NOT
 * bold, and a bold override is a real one). Byte offsets: `3.4x` 0..4,
 * `faster` 5..11, `triage` 12..18.
 */

const TEXT = HARVESTED_AD_PAGE.nodes.text_proof_stat.kind as TextNode;
const RED: Paint = { kind: "solid", color: { kind: "hex", value: "#ff0000" } };

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** The node's text kind, narrowed — every case that reaches for it is about a
 * text node. */
function textKind(node: Node): TextNode {
  assert.ok(node.kind.kind === "text");
  return node.kind;
}

function session(overrides: Partial<TextEditSession> = {}): TextEditSession {
  return { content: TEXT.content, spans: [], dirty: false, ...overrides };
}

/** `faster` in bold — the span every typing case moves around. */
const BOLD_FASTER: TextSpan = { start: 5, end: 11, font_weight: 700 };

/* -------------------------------------------------------------------------
 * `beforeinput` → a contiguous replacement
 * ---------------------------------------------------------------------- */

test("a typed character is the replacement of the caret's empty range", () => {
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: "s",
      inputType: "insertText",
      selection: { start: 18, end: 18 },
      targetRange: null,
    }),
    { start: 18, end: 18, text: "s" },
  );
});

test("typing over a selection replaces exactly that range", () => {
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: "quicker",
      inputType: "insertText",
      selection: { start: 5, end: 11 },
      targetRange: null,
    }),
    { start: 5, end: 11, text: "quicker" },
  );
});

test("a browser-supplied target range OUTRANKS the reported selection", () => {
  // `getTargetRanges()` is the authority when the browser offers one: it says
  // where the change is actually landing, which an IME's reported selection
  // need not.
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: "X",
      inputType: "insertText",
      selection: { start: 0, end: 0 },
      targetRange: { start: 5, end: 11 },
    }),
    { start: 5, end: 11, text: "X" },
  );
});

test("Enter inserts a newline — the overlay's plain-Enter contract", () => {
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: null,
      inputType: "insertLineBreak",
      selection: { start: 4, end: 4 },
      targetRange: null,
    }),
    { start: 4, end: 4, text: "\n" },
  );
});

test("backspace on a caret deletes the code point to its LEFT", () => {
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: null,
      inputType: "deleteContentBackward",
      selection: { start: 18, end: 18 },
      targetRange: null,
    }),
    { start: 17, end: 18, text: "" },
  );
});

test("backspace at the very start deletes nothing", () => {
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: null,
      inputType: "deleteContentBackward",
      selection: { start: 0, end: 0 },
      targetRange: null,
    }),
    { start: 0, end: 0, text: "" },
  );
});

test("backspace over an EMOJI deletes the whole code point, never half a pair", () => {
  assert.deepEqual(
    textEditReplacement({
      content: "a\u{1F600}b",
      data: null,
      inputType: "deleteContentBackward",
      selection: { start: 3, end: 3 },
      targetRange: null,
    }),
    { start: 1, end: 3, text: "" },
  );
});

test("forward-delete on a caret deletes the code point to its RIGHT", () => {
  assert.deepEqual(
    textEditReplacement({
      content: "a\u{1F600}b",
      data: null,
      inputType: "deleteContentForward",
      selection: { start: 1, end: 1 },
      targetRange: null,
    }),
    { start: 1, end: 3, text: "" },
  );
});

test("a selected range is deleted whole, whichever delete asked for it", () => {
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: null,
      inputType: "deleteByCut",
      selection: { start: 5, end: 11 },
      targetRange: null,
    }),
    { start: 5, end: 11, text: "" },
  );
});

test("an inverted selection is read low-to-high", () => {
  assert.deepEqual(
    textEditReplacement({
      content: TEXT.content,
      data: "x",
      inputType: "insertText",
      selection: { start: 11, end: 5 },
      targetRange: null,
    }),
    { start: 5, end: 11, text: "x" },
  );
});

test("an input type this session cannot place is NOT tracked — the diff recovers it", () => {
  // `deleteWordBackward` names no range, and guessing one would move spans to
  // text they were never applied to. Null routes the mutation to the
  // conservative prefix/suffix remap instead.
  for (const inputType of [
    "deleteWordBackward",
    "deleteSoftLineBackward",
    "historyUndo",
    "formatBold",
  ]) {
    assert.equal(
      textEditReplacement({
        content: TEXT.content,
        data: null,
        inputType,
        selection: { start: 5, end: 5 },
        targetRange: null,
      }),
      null,
      inputType,
    );
  }
});

test("an insert with no data at all is not tracked (the IME edge)", () => {
  assert.equal(
    textEditReplacement({
      content: TEXT.content,
      data: null,
      inputType: "insertCompositionText",
      selection: { start: 5, end: 5 },
      targetRange: null,
    }),
    null,
  );
});

/* -------------------------------------------------------------------------
 * The tracked transition — styling survives typing
 * ---------------------------------------------------------------------- */

test("typing INSIDE a styled run keeps the run styled, and grows it", () => {
  const next = textEditSessionAfterReplacement(
    session({ spans: [BOLD_FASTER] }),
    { start: 8, end: 8, text: "XY" },
  );
  assert.equal(next.content, "3.4x fasXYter triage");
  assert.deepEqual(next.spans, [{ start: 5, end: 13, font_weight: 700 }]);
});

test("typing BEFORE a styled run shifts it without styling the new text", () => {
  const next = textEditSessionAfterReplacement(
    session({ spans: [BOLD_FASTER] }),
    { start: 0, end: 0, text: "Up to " },
  );
  assert.equal(next.content, "Up to 3.4x faster triage");
  assert.deepEqual(next.spans, [{ start: 11, end: 17, font_weight: 700 }]);
});

test("typing AFTER every span leaves the vector byte-identical", () => {
  const next = textEditSessionAfterReplacement(
    session({ spans: [BOLD_FASTER] }),
    { start: 18, end: 18, text: "!" },
  );
  assert.equal(next.content, "3.4x faster triage!");
  assert.deepEqual(next.spans, [BOLD_FASTER]);
});

test("deleting a styled run entirely drops its span", () => {
  const next = textEditSessionAfterReplacement(
    session({ spans: [BOLD_FASTER] }),
    { start: 4, end: 11, text: "" },
  );
  assert.equal(next.content, "3.4x triage");
  assert.deepEqual(next.spans, []);
});

test("the replacement's own offsets are UTF-16 and cross into byte space", () => {
  // "3.4x 😀 triage": the caret sits after the emoji at UTF-16 7, which is byte
  // 9. A span applied to the emoji must survive an edit that follows it.
  const emoji = session({
    content: "3.4x \u{1F600} triage",
    spans: [{ start: 5, end: 9, italic: true }],
  });
  const next = textEditSessionAfterReplacement(emoji, {
    start: 7,
    end: 7,
    text: "!",
  });
  assert.equal(next.content, "3.4x \u{1F600}! triage");
  assert.deepEqual(next.spans, [{ start: 5, end: 9, italic: true }]);
});

/* -------------------------------------------------------------------------
 * The untracked fallback — conservative, never a guess
 * ---------------------------------------------------------------------- */

test("an untracked mutation remaps spans by prefix/suffix diff", () => {
  const next = textEditSessionResync(
    session({ spans: [BOLD_FASTER] }),
    "3.4x faster triage today",
  );
  assert.equal(next.content, "3.4x faster triage today");
  assert.deepEqual(next.spans, [BOLD_FASTER]);
});

test("an untracked mutation THROUGH a styled run trims it back to what survived", () => {
  const next = textEditSessionResync(
    session({ spans: [BOLD_FASTER] }),
    "3.4x fXr triage",
  );
  assert.equal(next.content, "3.4x fXr triage");
  // Only the EDGES of the run are still attributable — the `f` inside the
  // common prefix and the `r` inside the common suffix. The middle, which the
  // diff cannot account for, takes the node's own style rather than a guess.
  assert.deepEqual(next.spans, [
    { start: 5, end: 6, font_weight: 700 },
    { start: 7, end: 8, font_weight: 700 },
  ]);
});

test("a resync to the same string changes nothing at all", () => {
  const before = session({ spans: [BOLD_FASTER] });
  assert.equal(textEditSessionResync(before, TEXT.content), before);
});

test("the tracked prediction is used when the DOM agrees with it", () => {
  const before = session({ spans: [BOLD_FASTER] });
  const predicted = textEditSessionAfterReplacement(before, {
    start: 8,
    end: 8,
    text: "X",
  });
  assert.equal(
    textEditSessionAfterInput(before, predicted, predicted.content),
    predicted,
  );
});

test("a prediction the DOM contradicts is discarded for the diff remap", () => {
  const before = session({ spans: [BOLD_FASTER] });
  const predicted = textEditSessionAfterReplacement(before, {
    start: 8,
    end: 8,
    text: "X",
  });
  // Autofill/IME landed something else entirely: the prediction is not what
  // the textarea now holds, so it may not be trusted with the offsets.
  const observed = textEditSessionAfterInput(
    before,
    predicted,
    "3.4x faster triage today",
  );
  assert.equal(observed.content, "3.4x faster triage today");
  assert.deepEqual(observed.spans, [BOLD_FASTER]);
});

test("no prediction at all still lands on the session's own content", () => {
  const observed = textEditSessionAfterInput(
    session({ spans: [BOLD_FASTER] }),
    null,
    "3.4x faster triage today",
  );
  assert.equal(observed.content, "3.4x faster triage today");
  assert.deepEqual(observed.spans, [BOLD_FASTER]);
});

/* -------------------------------------------------------------------------
 * What the toolbar reads and writes
 * ---------------------------------------------------------------------- */

test("the session's node is the stored kind wearing the live draft and spans", () => {
  const node = textEditSessionNode(
    TEXT,
    session({ content: "3.4x quicker triage", spans: [BOLD_FASTER] }),
  );
  assert.equal(node.content, "3.4x quicker triage");
  assert.deepEqual(node.spans, [BOLD_FASTER]);
  // Everything else is the stored node's, untouched.
  assert.equal(node.font_weight, 600);
  assert.equal(node.font_family, "Inter");
});

test("a UTF-16 selection becomes the byte range span math runs in", () => {
  assert.deepEqual(
    textEditByteRange(session({ content: "a\u{1F600}b" }), { start: 1, end: 3 }),
    [1, 5],
  );
  // Inverted selections are ordered, and a mid-surrogate index snaps left.
  assert.deepEqual(
    textEditByteRange(session({ content: "a\u{1F600}b" }), { start: 3, end: 2 }),
    [1, 5],
  );
});

test("the toolbar reads OFF for an unstyled selection over an unbold node", () => {
  const state = textEditFormatState(TEXT, session(), { start: 5, end: 11 });
  assert.equal(state.bold, "off");
  assert.equal(state.italic, "off");
  assert.deepEqual(state.fill, { kind: "uniform", paint: null });
});

test("the toolbar reads ON over a fully styled selection and MIXED across an edge", () => {
  const styled = session({ spans: [BOLD_FASTER] });
  assert.equal(textEditFormatState(TEXT, styled, { start: 5, end: 11 }).bold, "on");
  assert.equal(textEditFormatState(TEXT, styled, { start: 0, end: 11 }).bold, "mixed");
});

test("the toolbar reads the DRAFT, not the stored content", () => {
  // The draft is longer than the stored string; a selection past the stored
  // end must still resolve rather than reading against a stale content.
  const drafted = session({
    content: "3.4x faster triage today",
    spans: [{ start: 19, end: 24, italic: true }],
  });
  assert.equal(
    textEditFormatState(TEXT, drafted, { start: 19, end: 24 }).italic,
    "on",
  );
});

test("applying a style to the selection returns the whole new vector", () => {
  const next = textEditStyledSpans(TEXT, session(), { start: 5, end: 11 }, {
    bold: true,
  });
  assert.deepEqual(next, [BOLD_FASTER]);
});

test("a style applied over the DRAFT uses the draft's own byte offsets", () => {
  const drafted = session({ content: "3.4x \u{1F600} triage" });
  const next = textEditStyledSpans(TEXT, drafted, { start: 5, end: 7 }, {
    fill: RED,
  });
  // UTF-16 5..7 is the emoji: bytes 5..9.
  assert.deepEqual(next, [{ start: 5, end: 9, fill: RED }]);
});

test("a COLLAPSED selection applies nothing — the toolbar disables it anyway", () => {
  const styled = session({ spans: [BOLD_FASTER] });
  assert.deepEqual(
    textEditStyledSpans(TEXT, styled, { start: 7, end: 7 }, { bold: false }),
    [BOLD_FASTER],
  );
});

test("a formatting action can legitimately empty the vector", () => {
  const styled = session({ spans: [BOLD_FASTER] });
  assert.deepEqual(
    textEditStyledSpans(TEXT, styled, { start: 5, end: 11 }, { bold: false }),
    [],
  );
});

/* -------------------------------------------------------------------------
 * F3 (review 2026-08-24, P2): DIRTY — an idle session must not revert a
 * concurrent write.
 *
 * A session seeds ONCE, from the node as it read when the caret opened, and a
 * D10 reload or an agent turn keeps that session alive (the scene comes back
 * ready and the node still exists). So an untouched open session was carrying a
 * stale snapshot and writing it back over whatever landed underneath it. The
 * flag is set by the human's own edits and by a formatting action, and by
 * NOTHING the model does: while it is clear the session follows the document,
 * and once it is set the draft is the human's and the document may not take it
 * back.
 * ---------------------------------------------------------------------- */

test("a freshly seeded session is CLEAN", () => {
  const seeded = textEditSessionSeed(TEXT.content, [BOLD_FASTER]);
  assert.equal(seeded.dirty, false);
  assert.equal(seeded.content, TEXT.content);
  assert.deepEqual(seeded.spans, [BOLD_FASTER]);
});

test("typing marks the session dirty — tracked, untracked and arbitrated alike", () => {
  assert.equal(
    textEditSessionAfterReplacement(session(), { start: 18, end: 18, text: "!" })
      .dirty,
    true,
  );
  assert.equal(textEditSessionResync(session(), "3.4x faster triage!").dirty, true);
  assert.equal(
    textEditSessionAfterInput(session(), null, "3.4x faster triage!").dirty,
    true,
  );
});

test("a CLEAN session re-seeds from a model that changed underneath it", () => {
  // The agent rewrote the node while the caret sat in it untouched. The overlay
  // must show the new text — the old snapshot is not the human's work, and
  // nothing of theirs is lost by dropping it.
  const reseeded = textEditSessionReseed(session(), "An agent wrote this", []);
  assert.equal(reseeded.content, "An agent wrote this");
  assert.equal(reseeded.dirty, false);
});

test("a CLEAN session re-seeds when only the SPANS moved underneath it", () => {
  const reseeded = textEditSessionReseed(session(), TEXT.content, [BOLD_FASTER]);
  assert.deepEqual(reseeded.spans, [BOLD_FASTER]);
});

test("a clean session whose model did not move is the SAME object (no churn)", () => {
  const before = session({ spans: [BOLD_FASTER] });
  assert.equal(textEditSessionReseed(before, TEXT.content, [BOLD_FASTER]), before);
  // …including when the stored spans come back in the engine's own key order.
  assert.equal(
    textEditSessionReseed(before, TEXT.content, [
      { font_weight: 700, end: 11, start: 5 },
    ]),
    before,
  );
});

test("a DIRTY session keeps its draft across a model change", () => {
  // The pre-existing posture, and the one that must not regress: mid-typing
  // drafts survive a reload (AD4.R's own rule).
  const typed = session({ content: "half-typed thought", dirty: true });
  assert.equal(textEditSessionReseed(typed, "An agent wrote this", []), typed);
});

test("an UNTOUCHED session writes nothing, even when the model moved under it", () => {
  // The defect: `draft !== node.kind.content` was true here — not because the
  // human typed, but because the DOCUMENT moved — so a blur wrote the session's
  // opening snapshot back over the agent's work.
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  textKind(node).content = "An agent wrote this";
  assert.equal(textEditSessionOperations(node, session()), null);
});

test("a DIRTY session writes, through the ordinary commit builder", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const operations = textEditSessionOperations(
    node,
    session({ content: "4.1x faster triage", dirty: true }),
  );
  assert.ok(operations);
  assert.equal(operations.length, 1);
});

/* -------------------------------------------------------------------------
 * F4 (review 2026-08-24, P2/P3-4): a REFUSED write loses nothing.
 *
 * The plan's error-handling contract: "overlay commit failure keeps the session
 * open with the typed text (nothing lost)". This deliberately differs from the
 * inspector's revert-on-refusal (AD4.R) — see `textEditSessionEnds`.
 * ---------------------------------------------------------------------- */

test("a commit ENDS the session when the write landed", () => {
  assert.equal(textEditSessionEnds([], true), true);
});

test("a REFUSED commit keeps the session open — the typed text is not thrown away", () => {
  assert.equal(textEditSessionEnds([], false), false);
});

test("a commit with nothing to write ends the session regardless", () => {
  // Null is not a refusal: there was no write to refuse.
  assert.equal(textEditSessionEnds(null, false), true);
});

test("a refused FORMATTING commit reverts the session's working spans", () => {
  const before = session({ spans: [] });
  const after = session({ spans: [BOLD_FASTER], dirty: true });
  assert.equal(textEditSessionAfterStyleCommit(before, after, false), before);
  assert.equal(textEditSessionAfterStyleCommit(before, after, true), after);
});
