import assert from "node:assert/strict";
import test from "node:test";
import type {
  Node,
  Operation,
  Paint,
  Scene,
  TextNode,
  TextSpan,
} from "../engine/scene/contracts";
import { spanValidationIssues } from "../engine/scene/textSpans";
import { HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import {
  textEditByteRange,
  textEditFormatState,
  textEditReplacement,
  textEditSessionAfterInput,
  textEditSessionAfterReplacement,
  textEditSessionAfterStyle,
  textEditSessionAfterStyleCommit,
  textEditSessionEnds,
  textEditSessionNode,
  textEditSessionOperations,
  textEditSessionResync,
  textEditSessionReseed,
  textEditSessionReseedSelection,
  textEditSessionSeed,
  textEditStyledSpans,
  type TextEditSelection,
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
  return {
    content: TEXT.content,
    spans: [],
    contentDirty: false,
    spansDirty: false,
    ...overrides,
  };
}

/** The single `update_node` patch a committed batch carries. */
function committedKind(operations: Operation[] | null) {
  assert.ok(operations);
  assert.equal(operations.length, 1);
  const [operation] = operations;
  assert.ok(operation.kind === "update_node");
  return operation.patch.kind;
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
 * F3 (review 2026-08-24, P2) → G1 (review round 2, P2): the TWO dirty channels.
 *
 * A session seeds ONCE, from the node as it read when the caret opened, and a
 * D10 reload or an agent turn keeps that session alive (the scene comes back
 * ready and the node still exists). So an untouched open session was carrying a
 * stale snapshot and writing it back over whatever landed underneath it — F3's
 * `dirty` flag closed that.
 *
 * G1 is the half F3 got wrong: ONE flag for TWO channels. `applyStyle` set it,
 * so a session whose human only clicked Bold stopped re-seeding, and its blur
 * then committed the opening snapshot as a CONTENT write over a concurrent
 * agent write. The flag is now a pair — `contentDirty` (the human typed) and
 * `spansDirty` (the human formatted) — and each channel commits on its own.
 * Neither is ever set by the model.
 * ---------------------------------------------------------------------- */

test("a freshly seeded session is CLEAN in both channels", () => {
  const seeded = textEditSessionSeed(TEXT.content, [BOLD_FASTER]);
  assert.equal(seeded.contentDirty, false);
  assert.equal(seeded.spansDirty, false);
  assert.equal(seeded.content, TEXT.content);
  assert.deepEqual(seeded.spans, [BOLD_FASTER]);
});

test("typing marks the CONTENT channel — tracked, untracked and arbitrated alike", () => {
  const typed = [
    textEditSessionAfterReplacement(session(), { start: 18, end: 18, text: "!" }),
    textEditSessionResync(session(), "3.4x faster triage!"),
    textEditSessionAfterInput(session(), null, "3.4x faster triage!"),
  ];
  for (const after of typed) {
    assert.equal(after.contentDirty, true);
    // G1: typing is NOT a formatting action. The maintained spans ride along
    // with the content commit regardless, so a text mutation has no reason to
    // claim the spans channel — and claiming it would make every keystroke
    // stop the session from following the document's spans.
    assert.equal(after.spansDirty, false);
  }
});

test("typing inside a FORMATTED session keeps the spans channel dirty too", () => {
  const styled = textEditSessionAfterStyle(session(), [BOLD_FASTER]);
  const typed = textEditSessionResync(styled, "3.4x faster triage!");
  assert.equal(typed.contentDirty, true);
  assert.equal(typed.spansDirty, true);
});

test("a formatting action marks ONLY the spans channel", () => {
  const styled = textEditSessionAfterStyle(session(), [BOLD_FASTER]);
  assert.deepEqual(styled.spans, [BOLD_FASTER]);
  assert.equal(styled.spansDirty, true);
  assert.equal(styled.contentDirty, false);
  // …and it leaves the draft exactly as it found it.
  assert.equal(styled.content, TEXT.content);
});

test("a CLEAN session re-seeds from a model that changed underneath it", () => {
  // The agent rewrote the node while the caret sat in it untouched. The overlay
  // must show the new text — the old snapshot is not the human's work, and
  // nothing of theirs is lost by dropping it.
  const reseeded = textEditSessionReseed(session(), "An agent wrote this", []);
  assert.equal(reseeded.content, "An agent wrote this");
  assert.equal(reseeded.contentDirty, false);
  assert.equal(reseeded.spansDirty, false);
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

test("a TYPED session keeps its draft across a model change", () => {
  // The pre-existing posture, and the one that must not regress: mid-typing
  // drafts survive a reload (AD4.R's own rule).
  const typed = session({ content: "half-typed thought", contentDirty: true });
  assert.equal(textEditSessionReseed(typed, "An agent wrote this", []), typed);
  // …and that holds whatever the document does to the spans, too.
  assert.equal(
    textEditSessionReseed(typed, "An agent wrote this", [BOLD_FASTER]),
    typed,
  );
});

test("G1: a FORMATTING-ONLY session adopts a concurrent content change", () => {
  // The whole point of splitting the flag: this session's human never typed, so
  // it has no draft to defend — but it DOES have a spans vector nobody else
  // authored, so the vector is remapped onto the new text rather than dropped.
  const styled = textEditSessionAfterStyle(session(), [BOLD_FASTER]);
  const reseeded = textEditSessionReseed(styled, "3.4x faster triage now", []);
  assert.equal(reseeded.content, "3.4x faster triage now");
  assert.deepEqual(reseeded.spans, [BOLD_FASTER]);
  assert.equal(reseeded.spansDirty, true);
  assert.equal(reseeded.contentDirty, false);
});

test("G1: a formatting-only session does NOT take the document's spans back", () => {
  // The human's vector outranks the document's on the channel they touched —
  // otherwise the toolbar would flip back under them on the next render.
  const styled = textEditSessionAfterStyle(session(), []);
  assert.equal(textEditSessionReseed(styled, TEXT.content, [BOLD_FASTER]), styled);
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

test("a TYPED session writes its draft, through the ordinary commit builder", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const operations = textEditSessionOperations(
    node,
    session({ content: "4.1x faster triage", contentDirty: true }),
  );
  assert.ok(operations);
  assert.equal(operations.length, 1);
});

test("G1: a formatting-only commit sends the LIVE content, never the snapshot", () => {
  // The proven defect: one `dirty` flag meant a Bold-only session stopped
  // re-seeding AND claimed the content channel, so the blur committed its
  // opening snapshot as a content write over the agent's sentence.
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  textKind(node).content = "An agent wrote this";
  const styled = textEditSessionAfterStyle(session(), [BOLD_FASTER]);
  assert.deepEqual(committedKind(textEditSessionOperations(node, styled)), {
    kind: "set",
    value: { ...textKind(node), spans: [BOLD_FASTER] },
  });
});

test("G1: a formatting-only commit still writes when the model did NOT move", () => {
  // The ordinary case, unchanged by the split: nothing concurrent happened, so
  // the live content and the session's snapshot are the same string.
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const styled = textEditSessionAfterStyle(session(), [BOLD_FASTER]);
  assert.deepEqual(committedKind(textEditSessionOperations(node, styled)), {
    kind: "set",
    value: { ...textKind(node), spans: [BOLD_FASTER] },
  });
});

/* -------------------------------------------------------------------------
 * G2 (review round 2, P3): a re-seed must not leave a STALE live selection.
 *
 * The re-seed rewrites the textarea's value, but the selection offsets were
 * measured in the text it replaced — so Bold would style a range of the new
 * string the human never selected. The adopted content resets the selection to
 * the posture a session OPENS in (select-all), which is the only offset pair
 * that is meaningful in a string nobody has looked at yet.
 * ---------------------------------------------------------------------- */

test("G2: a re-seed that adopts new content resets the selection to select-all", () => {
  const before = session();
  const after = textEditSessionReseed(before, "An agent wrote this", []);
  assert.deepEqual(textEditSessionReseedSelection(before, after, { start: 4, end: 9 }), {
    start: 0,
    end: "An agent wrote this".length,
  });
});

test("G2: a re-seed that changed no characters leaves the live selection alone", () => {
  // A spans-only re-seed keeps every offset valid, and stealing the human's
  // range there would be its own defect.
  const before = session();
  const after = textEditSessionReseed(before, TEXT.content, [BOLD_FASTER]);
  const selection = { start: 4, end: 9 };
  assert.equal(
    textEditSessionReseedSelection(before, after, selection),
    selection,
  );
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
  const after = session({ spans: [BOLD_FASTER], spansDirty: true });
  assert.equal(textEditSessionAfterStyleCommit(before, after, false), before);
  assert.equal(textEditSessionAfterStyleCommit(before, after, true), after);
});

/* -------------------------------------------------------------------------
 * Task 11 (scene clipboard, R37 a–c): a PASTE INSIDE the open session.
 *
 * The clipboard lane never built a text-session paste path, because there is
 * nothing to build: a paste into the overlay's textarea arrives as an ordinary
 * `beforeinput`, and `insertFromPaste` sits in the same `DATA_INSERTS` table as
 * `insertText`. So the contract to PIN is an EQUIVALENCE — a paste of some
 * string is the same transition as typing that string — plus the span algebra's
 * own invariants over the result. These are pins, not new behaviour: they fail
 * only if the table, the placement, or the reconciliation moves under them.
 * ---------------------------------------------------------------------- */

/** One `beforeinput` driven end to end — placed by {@link textEditReplacement},
 * then applied by the tracked transition. Exactly the pair the overlay runs
 * (`components/scene-artifact-canvas.tsx`), so the two `inputType`s are
 * compared over the WHOLE path rather than over the table alone. */
function afterBeforeInput(
  before: TextEditSession,
  inputType: string,
  data: string,
  selection: TextEditSelection,
): TextEditSession {
  const replacement = textEditReplacement({
    content: before.content,
    data,
    inputType,
    selection,
    targetRange: null,
  });
  assert.ok(replacement, `${inputType} must place a replacement`);
  return textEditSessionAfterReplacement(before, replacement);
}

/** `triage` in italic — the second span the cross-span paste case needs. */
const ITALIC_TRIAGE: TextSpan = { start: 12, end: 18, italic: true };

test("R37a: a PASTE inside a styled run grows it exactly as typing the same text does", () => {
  const before = session({ spans: [BOLD_FASTER] });
  const caret = { start: 8, end: 8 };
  const pasted = afterBeforeInput(before, "insertFromPaste", "quickly ", caret);
  const typed = afterBeforeInput(before, "insertText", "quickly ", caret);

  // The equivalence itself: same content, same spans, same dirty channels.
  assert.deepEqual(pasted, typed);
  // …and it is not vacuously equal — the run really did absorb the paste.
  assert.equal(pasted.content, "3.4x fasquickly ter triage");
  assert.deepEqual(pasted.spans, [{ start: 5, end: 19, font_weight: 700 }]);
  assert.equal(pasted.contentDirty, true);
  assert.equal(pasted.spansDirty, false);
});

test("R37b: a paste REPLACING a cross-span selection normalizes per the span algebra", () => {
  // The selection runs from inside bold `faster` (8) to inside italic `triage`
  // (15), so BOTH spans are cut and neither may absorb the pasted text.
  const before = session({ spans: [BOLD_FASTER, ITALIC_TRIAGE] });
  const across = { start: 8, end: 15 };
  const pasted = afterBeforeInput(before, "insertFromPaste", "NEW", across);

  assert.deepEqual(pasted, afterBeforeInput(before, "insertText", "NEW", across));
  assert.equal(pasted.content, "3.4x fasNEWage");
  // Each span keeps only the side of the cut that survived: bold's head, and
  // italic's tail shifted by the -4 byte delta. The pasted text takes the
  // node's own style, which is the algebra's no-guess rule.
  assert.deepEqual(pasted.spans, [
    { start: 5, end: 8, font_weight: 700 },
    { start: 11, end: 14, italic: true },
  ]);
  // The engine's own five rules (the client twin of `span_validation_errors`),
  // and the normalized order they are emitted in.
  assert.deepEqual(spanValidationIssues(pasted.content, pasted.spans), []);
  for (let index = 1; index < pasted.spans.length; index += 1) {
    assert.ok(
      pasted.spans[index - 1].end <= pasted.spans[index].start,
      "spans come back sorted and non-overlapping",
    );
  }
});

test("R37c: a MULTI-LINE paste is the same transition as typing that same string", () => {
  // A pasted newline is ordinary data on this path — it is NOT routed through
  // the `NEWLINE_INSERTS` table, which only serves an Enter key that carries no
  // data at all. Multiline content is real here (the overlay's plain-Enter
  // contract), so the newline must land verbatim.
  const before = session({ spans: [BOLD_FASTER] });
  const caret = { start: 18, end: 18 };
  const text = "\nTrusted by 400 clinics\nsince 2019";
  const pasted = afterBeforeInput(before, "insertFromPaste", text, caret);

  assert.deepEqual(pasted, afterBeforeInput(before, "insertText", text, caret));
  assert.equal(pasted.content, `${TEXT.content}${text}`);
  // Appended past every span, so the vector is byte-identical.
  assert.deepEqual(pasted.spans, [BOLD_FASTER]);
  assert.deepEqual(spanValidationIssues(pasted.content, pasted.spans), []);
});
