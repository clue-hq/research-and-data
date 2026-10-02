import type { Paint, TextNode, TextSpan } from "./contracts";

/**
 * Rung C core — the span algebra behind range styling in the scene editor.
 *
 * THE ONE COORDINATE SPACE: every offset in this module is a UTF-8 **byte**
 * offset into a text node's **stored** `content` (A6b D1) — never a UTF-16
 * index, never an offset into the transformed/normalized string the painter
 * shapes (`textTransform.ts` owns that relocation, and does it from these same
 * stored-space offsets). A textarea's `selectionStart`/`selectionEnd` are
 * UTF-16 code units, so every UI caller crosses the seam through
 * {@link utf16ToByteOffset} / {@link byteToUtf16Offset} first.
 *
 * THE FIVE RULES: lumen-core's `span_validation_errors` (`scene.rs:754`)
 * requires each span to be in bounds, `start < end`, aligned to UTF-8 char
 * boundaries, sorted and non-overlapping against its predecessor, and to carry
 * a solid-or-token fill (never a gradient). That gate runs at **layout**
 * (LUMV0906), not at apply — an invalid vector applies clean and then silently
 * drops the node out of measurement. This module is therefore the pre-send
 * gate: every function returns a vector that satisfies
 * {@link spanValidationIssues}, whatever it is handed. Callers additionally run
 * `spanValidationIssues` as a production guard before writing.
 *
 * THE D4 EDGE: `Document::update_node` (`operations.rs:620-631`) clears spans
 * when a write changes `content` while carrying a byte-identical spans vector —
 * identical spans on changed content are indistinguishable from a stale
 * carry-forward, so honesty wins. A re-authored, structurally different vector
 * survives. {@link spansVectorForContentEdit} is the deliberate dance with that
 * rule.
 */

const utf8Encoder = new TextEncoder();
const utf8Decoder = new TextDecoder();

/** The CSS weight at and above which text counts as bold, in the engine and here. */
const BOLD_WEIGHT_THRESHOLD = 700;
/** The weight a "bold on" override authors, and the fallback for a weightless node. */
const BOLD_WEIGHT = 700;
const REGULAR_WEIGHT = 400;

/** A half-open `[start, end)` byte range over the stored content. */
export type ByteRange = readonly [number, number];

/** Toolbar tri-state for one formatting channel across a selection. */
export type TriState = "on" | "off" | "mixed";

/** The paints a span fill may legally carry (gradients are rejected, LUMV0908). */
export type SpanPaint = Extract<Paint, { kind: "solid" } | { kind: "token" }>;

/** A `null` paint means "no override" — the range inherits the node's fill. */
export type RangeFillState = { kind: "uniform"; paint: Paint | null } | { kind: "mixed" };

export interface RangeFormatState {
  bold: TriState;
  italic: TriState;
  underline: TriState;
  strikethrough: TriState;
  fill: RangeFillState;
}

/**
 * One formatting channel at a time — the toolbar never authors two at once, and
 * one channel per call keeps every apply a single undoable intent. `fill: null`
 * clears the override (back to the node fill); the paint is narrowed to
 * solid/token so a gradient is unrepresentable at the call site.
 */
export type StylePatch =
  | { bold: boolean }
  | { italic: boolean }
  | { underline: boolean }
  | { strikethrough: boolean }
  | { fill: SpanPaint | null };

/** The result of reconciling a content edit against a spans vector. */
export interface SpanReconciliation {
  content: string;
  spans: TextSpan[];
}

// ---------------------------------------------------------------------------
// Offset mapping (UTF-16 ⇄ UTF-8 byte space)
// ---------------------------------------------------------------------------

/**
 * Byte and UTF-16 offsets of every code point start, plus a terminal entry
 * holding each total length. Both arrays are strictly increasing, so a snap is
 * a binary search and a char-boundary test is a membership test.
 */
interface ContentIndex {
  byteStarts: number[];
  utf16Starts: number[];
}

function indexContent(content: string): ContentIndex {
  const byteStarts: number[] = [];
  const utf16Starts: number[] = [];
  let byte = 0;
  let unit = 0;
  for (const char of content) {
    byteStarts.push(byte);
    utf16Starts.push(unit);
    byte += utf8LengthOfCodePoint(char.codePointAt(0) ?? 0);
    unit += char.length;
  }
  byteStarts.push(byte);
  utf16Starts.push(unit);
  return { byteStarts, utf16Starts };
}

/** UTF-8 width of one code point. A lone surrogate encodes as U+FFFD (3 bytes),
 * matching what `TextEncoder` actually emits for it. */
function utf8LengthOfCodePoint(codePoint: number): number {
  if (codePoint < 0x80) return 1;
  if (codePoint < 0x800) return 2;
  if (codePoint < 0x10000) return 3;
  return 4;
}

/** Largest index `i` with `values[i] <= target`; `values` is strictly increasing. */
function floorIndex(values: number[], target: number): number {
  let low = 0;
  let high = values.length - 1;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (values[mid] <= target) {
      low = mid;
    } else {
      high = mid - 1;
    }
  }
  return low;
}

/** UTF-8 byte length of `content` (what span offsets are measured in). */
export function utf8ByteLength(content: string): number {
  const { byteStarts } = indexContent(content);
  return byteStarts[byteStarts.length - 1];
}

/**
 * A UTF-16 index (what `selectionStart`/`selectionEnd` report) → the UTF-8 byte
 * offset span math runs in. An index landing INSIDE a surrogate pair snaps LEFT
 * to the code point start; out-of-range clamps into the content.
 */
export function utf16ToByteOffset(content: string, utf16Index: number): number {
  const { byteStarts, utf16Starts } = indexContent(content);
  const target = Number.isFinite(utf16Index) ? Math.floor(utf16Index) : 0;
  if (target <= 0) return 0;
  const last = utf16Starts.length - 1;
  if (target >= utf16Starts[last]) return byteStarts[last];
  return byteStarts[floorIndex(utf16Starts, target)];
}

/**
 * The inverse: a UTF-8 byte offset → the UTF-16 index a textarea selection
 * speaks. A byte inside a multi-byte character snaps LEFT to that character's
 * start; out-of-range clamps.
 */
export function byteToUtf16Offset(content: string, byteIndex: number): number {
  const { byteStarts, utf16Starts } = indexContent(content);
  const target = Number.isFinite(byteIndex) ? Math.floor(byteIndex) : 0;
  if (target <= 0) return 0;
  const last = byteStarts.length - 1;
  if (target >= byteStarts[last]) return utf16Starts[last];
  return utf16Starts[floorIndex(byteStarts, target)];
}

/** Clamp+snap one byte offset onto a char boundary (leftwards). */
function snapByteOffset(index: ContentIndex, byteOffset: number): number {
  const { byteStarts } = index;
  const target = Number.isFinite(byteOffset) ? Math.floor(byteOffset) : 0;
  if (target <= 0) return 0;
  const last = byteStarts.length - 1;
  if (target >= byteStarts[last]) return byteStarts[last];
  return byteStarts[floorIndex(byteStarts, target)];
}

/**
 * Order, clamp and snap a byte range onto char boundaries, so nothing
 * downstream can author a span that splits a character. Snapping is always
 * LEFT, so a range can collapse to empty (a mid-character selection is a no-op,
 * never a corruption).
 */
export function snapRangeToCharBoundaries(content: string, range: ByteRange): [number, number] {
  const index = indexContent(content);
  const low = Math.min(range[0], range[1]);
  const high = Math.max(range[0], range[1]);
  return [snapByteOffset(index, low), snapByteOffset(index, high)];
}

// ---------------------------------------------------------------------------
// Validation — the client twin of lumen-core `span_validation_errors`
// ---------------------------------------------------------------------------

/**
 * The five rules, mirrored from lumen-core `span_validation_errors`
 * (`scene.rs:754`), returning one human-readable issue per violation (empty =
 * valid). Exported both for the tests and as the production pre-send guard: the
 * engine only runs these at layout, where a violation is a silently unmeasured
 * node rather than a refused write.
 */
export function spanValidationIssues(content: string, spans: readonly TextSpan[]): string[] {
  const issues: string[] = [];
  const { byteStarts } = indexContent(content);
  const length = byteStarts[byteStarts.length - 1];
  const boundaries = new Set(byteStarts);
  let previousEnd: number | null = null;

  spans.forEach((span, index) => {
    if (!(span.start < span.end)) {
      issues.push(
        `span ${index}: start ${span.start} is not before end ${span.end} (empty or inverted range)`,
      );
    }
    if (span.start > length || span.end > length) {
      issues.push(
        `span ${index}: range ${span.start}..${span.end} is out of bounds for content of ${length} bytes`,
      );
    } else {
      if (!boundaries.has(span.start)) {
        issues.push(`span ${index}: start ${span.start} is not on a UTF-8 char boundary`);
      }
      if (!boundaries.has(span.end)) {
        issues.push(`span ${index}: end ${span.end} is not on a UTF-8 char boundary`);
      }
    }
    if (previousEnd !== null && span.start < previousEnd) {
      issues.push(
        `span ${index}: start ${span.start} overlaps or is unsorted against the previous span ending at ${previousEnd}`,
      );
    }
    previousEnd = Math.max(span.end, previousEnd ?? 0);
    if (span.fill && (span.fill.kind === "linear_gradient" || span.fill.kind === "radial_gradient")) {
      issues.push(`span ${index}: fill must be a solid color or token, not a gradient`);
    }
  });

  return issues;
}

// ---------------------------------------------------------------------------
// Span overrides + normalization
// ---------------------------------------------------------------------------

/** The channel bag of a span, without its range. */
interface SpanOverrides {
  fill?: Paint;
  font_weight?: number;
  underline?: boolean;
  strikethrough?: boolean;
  italic?: boolean;
}

/** Read a span's overrides, dropping a gradient fill (unrepresentable in the
 * engine, so it can never leave this module). */
function spanOverrides(span: TextSpan): SpanOverrides {
  const overrides: SpanOverrides = {};
  if (span.fill && span.fill.kind !== "linear_gradient" && span.fill.kind !== "radial_gradient") {
    overrides.fill = span.fill;
  }
  if (span.font_weight !== undefined) overrides.font_weight = span.font_weight;
  if (span.underline !== undefined) overrides.underline = span.underline;
  if (span.strikethrough !== undefined) overrides.strikethrough = span.strikethrough;
  if (span.italic !== undefined) overrides.italic = span.italic;
  return overrides;
}

function hasOverrides(overrides: SpanOverrides): boolean {
  return (
    overrides.fill !== undefined ||
    overrides.font_weight !== undefined ||
    overrides.underline !== undefined ||
    overrides.strikethrough !== undefined ||
    overrides.italic !== undefined
  );
}

/** Build a span with the contract's key order and no `undefined` members, so it
 * serializes exactly like the engine's `skip_serializing_if` serde. */
function makeSpan(start: number, end: number, overrides: SpanOverrides): TextSpan {
  const span: TextSpan = { start, end };
  if (overrides.fill !== undefined) span.fill = overrides.fill;
  if (overrides.font_weight !== undefined) span.font_weight = overrides.font_weight;
  if (overrides.underline !== undefined) span.underline = overrides.underline;
  if (overrides.strikethrough !== undefined) span.strikethrough = overrides.strikethrough;
  if (overrides.italic !== undefined) span.italic = overrides.italic;
  return span;
}

/** Key-sorted structural key — object key ORDER must not decide equality (spans
 * arrive from the wire, from the engine, and from this module). */
function stableKey(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(stableKey).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableKey(item)}`).join(",")}}`;
}

/**
 * Structural equality key for a whole spans vector, exported because more than
 * one surface has to ask "is this the same styling?" — the commit path (against
 * the stored vector), the session's re-seed (against the model's) and this
 * module's own D4 guard (against what the engine will compare). Key ORDER must
 * not decide it: the engine's serde, the wire and this module each emit their
 * own, and one re-typed span must never read as a change.
 */
export function spansStableKey(spans: readonly TextSpan[]): string {
  return stableKey(spans);
}

function sameOverrides(left: SpanOverrides, right: SpanOverrides): boolean {
  return stableKey(left) === stableKey(right);
}

/**
 * The single exit gate: snap every offset onto a char boundary of `content`,
 * clamp into bounds, drop empty/override-less spans and gradient fills, sort,
 * clip any overlap against the previous span, and merge adjacent spans carrying
 * identical overrides. Output always satisfies {@link spanValidationIssues},
 * whatever came in.
 *
 * NOTE the merge: adjacent-identical spans collapse here, which is exactly what
 * {@link spansVectorForContentEdit}'s split must NOT be re-run through.
 */
export function normalizeSpans(content: string, spans: readonly TextSpan[]): TextSpan[] {
  const index = indexContent(content);
  const limit = index.byteStarts[index.byteStarts.length - 1];
  const prepared = spans
    .map((span) => ({
      start: snapByteOffset(index, span.start),
      end: snapByteOffset(index, span.end),
      overrides: spanOverrides(span),
    }))
    .filter((entry) => entry.start < entry.end && hasOverrides(entry.overrides))
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const out: TextSpan[] = [];
  let previousEnd = 0;
  for (const entry of prepared) {
    const start = Math.max(entry.start, previousEnd);
    const end = Math.min(entry.end, limit);
    if (start >= end) continue;
    const previous = out[out.length - 1];
    if (previous && previous.end === start && sameOverrides(spanOverrides(previous), entry.overrides)) {
      out[out.length - 1] = makeSpan(previous.start, end, entry.overrides);
    } else {
      out.push(makeSpan(start, end, entry.overrides));
    }
    previousEnd = end;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Format state for a selection
// ---------------------------------------------------------------------------

/** The effective (post-override) style of one stretch of content. */
interface EffectiveStyle {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strikethrough: boolean;
  /** `null` = no span override; the range paints with the node's own fill. */
  fill: Paint | null;
}

function baseStyle(node: TextNode): EffectiveStyle {
  return {
    bold: (node.font_weight ?? REGULAR_WEIGHT) >= BOLD_WEIGHT_THRESHOLD,
    italic: node.italic ?? false,
    underline: node.underline ?? false,
    strikethrough: node.strikethrough ?? false,
    fill: null,
  };
}

/** Override semantics, matching the engine's `span.italic.unwrap_or(block.italic)`:
 * an absent channel inherits the node, a present one wins outright (including
 * `false`, which de-italicizes a run inside an italic block). */
function effectiveStyle(node: TextNode, span: TextSpan): EffectiveStyle {
  return {
    bold: (span.font_weight ?? node.font_weight ?? REGULAR_WEIGHT) >= BOLD_WEIGHT_THRESHOLD,
    italic: span.italic ?? node.italic ?? false,
    underline: span.underline ?? node.underline ?? false,
    strikethrough: span.strikethrough ?? node.strikethrough ?? false,
    fill: span.fill ?? null,
  };
}

/** The effective styles of every distinct stretch inside `[start, end)`, in
 * order. A collapsed range yields exactly one style: the one AT the caret. */
function stylePiecesForRange(node: TextNode, start: number, end: number): EffectiveStyle[] {
  const spans = normalizeSpans(node.content, node.spans ?? []);
  if (start >= end) {
    const covering = spans.find((span) => span.start <= start && start < span.end);
    return [covering ? effectiveStyle(node, covering) : baseStyle(node)];
  }
  const pieces: EffectiveStyle[] = [];
  let cursor = start;
  for (const span of spans) {
    if (span.end <= start || span.start >= end) continue;
    if (span.start > cursor) pieces.push(baseStyle(node));
    pieces.push(effectiveStyle(node, span));
    cursor = Math.min(end, span.end);
  }
  if (cursor < end) pieces.push(baseStyle(node));
  return pieces;
}

function triState(values: boolean[]): TriState {
  const first = values[0] ?? false;
  return values.every((value) => value === first) ? (first ? "on" : "off") : "mixed";
}

/**
 * What the toolbar shows for the current selection: a tri-state per flag
 * channel plus a uniform-or-mixed fill. Effective value per stretch is
 * `span override ?? node base`; a stretch with no span contributes the node
 * base, so styling a range that already matches the base reads "on" rather than
 * "mixed". Bold is derived, not stored: effective `font_weight >= 700`.
 *
 * A collapsed range (`start === end`) reports the state AT the caret — the span
 * covering that byte (`start <= caret < end`), else the node base. v1's toolbar
 * disables the toggles for a collapsed selection, but the reading is defined so
 * a future caret-typing-style can use it.
 */
export function formatStateForRange(node: TextNode, range: ByteRange): RangeFormatState {
  const [start, end] = snapRangeToCharBoundaries(node.content, range);
  const pieces = stylePiecesForRange(node, start, end);
  const fillKeys = new Set(pieces.map((piece) => stableKey(piece.fill)));
  return {
    bold: triState(pieces.map((piece) => piece.bold)),
    italic: triState(pieces.map((piece) => piece.italic)),
    underline: triState(pieces.map((piece) => piece.underline)),
    strikethrough: triState(pieces.map((piece) => piece.strikethrough)),
    fill:
      fillKeys.size <= 1
        ? { kind: "uniform", paint: pieces[0]?.fill ?? null }
        : { kind: "mixed" },
  };
}

// ---------------------------------------------------------------------------
// Applying a style to a range
// ---------------------------------------------------------------------------

/** Apply one channel to one run's overrides. Setting a channel to the value the
 * NODE already carries REMOVES the override instead of restating it, so the
 * vector stays as small as the document allows and "bold inside a bold headline"
 * or "un-bold inside a bold headline" both do the right thing:
 * - bold on/off with a node base on the other side of 700 → explicit override
 *   (700 / 400); on the same side → the override drops away.
 * - italic/underline/strikethrough → explicit override unless it equals the base.
 * - fill → set, or `null` to clear the override back to the node fill.
 */
function applyPatchToOverrides(
  overrides: SpanOverrides,
  patch: StylePatch,
  node: TextNode,
): SpanOverrides {
  const next: SpanOverrides = { ...overrides };
  if ("bold" in patch) {
    const baseBold = (node.font_weight ?? REGULAR_WEIGHT) >= BOLD_WEIGHT_THRESHOLD;
    if (patch.bold === baseBold) {
      delete next.font_weight;
    } else {
      next.font_weight = patch.bold ? BOLD_WEIGHT : REGULAR_WEIGHT;
    }
    return next;
  }
  if ("italic" in patch) {
    if (patch.italic === (node.italic ?? false)) delete next.italic;
    else next.italic = patch.italic;
    return next;
  }
  if ("underline" in patch) {
    if (patch.underline === (node.underline ?? false)) delete next.underline;
    else next.underline = patch.underline;
    return next;
  }
  if ("strikethrough" in patch) {
    if (patch.strikethrough === (node.strikethrough ?? false)) delete next.strikethrough;
    else next.strikethrough = patch.strikethrough;
    return next;
  }
  if (patch.fill === null) delete next.fill;
  else next.fill = patch.fill;
  return next;
}

/**
 * Apply one formatting channel across `[start, end)` and return the whole new
 * spans vector for the node (the write vehicle is `updateTextNode(node,
 * {spans})`, which replaces the vector wholesale).
 *
 * Mechanics: split every existing span at the range edges, synthesize
 * override-less runs for the uncovered parts of the range, apply the channel to
 * every run inside the range (other channels of overlapped spans ride along
 * untouched), then normalize — dropping runs whose overrides all fell away and
 * merging adjacent runs with identical props. A collapsed or mid-character
 * range is a no-op returning the normalized existing vector.
 */
export function applyStyleToRange(
  node: TextNode,
  range: ByteRange,
  patch: StylePatch,
): TextSpan[] {
  const content = node.content;
  const existing = normalizeSpans(content, node.spans ?? []);
  const [start, end] = snapRangeToCharBoundaries(content, range);
  if (start >= end) return existing;

  const runs: Array<{ start: number; end: number; overrides: SpanOverrides }> = [];
  let cursor = start;
  for (const span of existing) {
    const overrides = spanOverrides(span);
    // The parts of this span outside the range keep their overrides verbatim.
    if (span.start < start) {
      runs.push({ start: span.start, end: Math.min(span.end, start), overrides });
    }
    const insideStart = Math.max(span.start, start);
    const insideEnd = Math.min(span.end, end);
    if (insideStart < insideEnd) {
      if (insideStart > cursor) {
        runs.push({ start: cursor, end: insideStart, overrides: {} });
      }
      runs.push({ start: insideStart, end: insideEnd, overrides });
      cursor = insideEnd;
    }
    if (span.end > end) {
      runs.push({ start: Math.max(span.start, end), end: span.end, overrides });
    }
  }
  if (cursor < end) {
    runs.push({ start: cursor, end, overrides: {} });
  }

  const patched = runs.map((run) => {
    const inside = run.start >= start && run.end <= end;
    return makeSpan(
      run.start,
      run.end,
      inside ? applyPatchToOverrides(run.overrides, patch, node) : run.overrides,
    );
  });
  return normalizeSpans(content, patched);
}

// ---------------------------------------------------------------------------
// Reconciliation across a content edit
// ---------------------------------------------------------------------------

/**
 * Remap spans across one contiguous replacement of `[removedStart, removedEnd)`
 * by `insertedLength` bytes.
 *
 * `absorbInterior` distinguishes the two callers. A TRACKED edit (`beforeinput`)
 * knows the replacement really happened there, so a span that strictly surrounds
 * it absorbs the inserted text — typing inside a bold word stays bold, like any
 * real editor. An UNTRACKED edit recovered by diffing only *guesses* where the
 * change was, so it stays conservative: the surrounding span is trimmed back to
 * the unchanged prefix/suffix and the middle takes the node's base style.
 *
 * A contiguous replacement can never split one span into two: the pieces left of
 * and right of a pure deletion become adjacent in the new content and merge in
 * {@link normalizeSpans}; only an insertion separates them, and that is exactly
 * the case `absorbInterior` decides.
 */
function remapAcrossReplacement(
  spans: readonly TextSpan[],
  removedStart: number,
  removedEnd: number,
  insertedLength: number,
  absorbInterior: boolean,
): TextSpan[] {
  const delta = insertedLength - (removedEnd - removedStart);
  const out: TextSpan[] = [];
  for (const span of spans) {
    const overrides = spanOverrides(span);
    if (span.end <= removedStart) {
      out.push(makeSpan(span.start, span.end, overrides));
      continue;
    }
    if (span.start >= removedEnd) {
      out.push(makeSpan(span.start + delta, span.end + delta, overrides));
      continue;
    }
    if (absorbInterior && span.start < removedStart && removedEnd < span.end) {
      out.push(makeSpan(span.start, span.end + delta, overrides));
      continue;
    }
    const leftEnd = Math.min(span.end, removedStart);
    if (span.start < leftEnd) {
      out.push(makeSpan(span.start, leftEnd, overrides));
    }
    const rightStart = Math.max(span.start, removedEnd);
    if (rightStart < span.end) {
      out.push(makeSpan(rightStart + delta, span.end + delta, overrides));
    }
  }
  return out;
}

/**
 * The in-session typing path: one contiguous replacement (the `beforeinput`
 * shape — an old byte range plus the text replacing it) produces the new content
 * AND the spans vector that keeps styling attached to the text it was applied
 * to. Offsets are snapped to char boundaries first, so a mid-character range
 * degrades to a boundary-aligned edit rather than corrupting the string.
 */
export function reconcileSpansForReplacement(
  content: string,
  spans: readonly TextSpan[],
  replaceStart: number,
  replaceEnd: number,
  insertedText: string,
): SpanReconciliation {
  const [removedStart, removedEnd] = snapRangeToCharBoundaries(content, [replaceStart, replaceEnd]);
  const bytes = utf8Encoder.encode(content);
  const inserted = utf8Encoder.encode(insertedText);
  const merged = new Uint8Array(bytes.length - (removedEnd - removedStart) + inserted.length);
  merged.set(bytes.subarray(0, removedStart), 0);
  merged.set(inserted, removedStart);
  merged.set(bytes.subarray(removedEnd), removedStart + inserted.length);
  const nextContent = utf8Decoder.decode(merged);
  const remapped = remapAcrossReplacement(
    normalizeSpans(content, spans),
    removedStart,
    removedEnd,
    inserted.length,
    true,
  );
  return { content: nextContent, spans: normalizeSpans(nextContent, remapped) };
}

/**
 * The fallback for an edit nobody tracked (an inspector commit, an autofill, an
 * IME edge): treat the change as the single middle between the longest common
 * prefix and the longest common suffix. Both are computed in CODE POINT space
 * and converted to bytes, so the derived edges are char boundaries on both
 * sides by construction.
 *
 * Conservative by contract — it never guesses what happened in the middle:
 * spans wholly inside the common prefix keep their offsets, spans wholly inside
 * the common suffix shift by the byte delta, and a span touching the middle is
 * trimmed back to the prefix/suffix or dropped.
 */
export function remapSpansByDiff(
  before: string,
  after: string,
  spans: readonly TextSpan[],
): TextSpan[] {
  const beforeChars = Array.from(before);
  const afterChars = Array.from(after);
  const shortest = Math.min(beforeChars.length, afterChars.length);

  let prefix = 0;
  while (prefix < shortest && beforeChars[prefix] === afterChars[prefix]) prefix += 1;

  let suffix = 0;
  while (
    suffix < shortest - prefix &&
    beforeChars[beforeChars.length - 1 - suffix] === afterChars[afterChars.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  const beforeIndex = indexContent(before);
  const afterIndex = indexContent(after);
  const prefixBytes = beforeIndex.byteStarts[prefix];
  const suffixStartBefore = beforeIndex.byteStarts[beforeChars.length - suffix];
  const suffixStartAfter = afterIndex.byteStarts[afterChars.length - suffix];

  const remapped = remapAcrossReplacement(
    normalizeSpans(before, spans),
    prefixBytes,
    suffixStartBefore,
    suffixStartAfter - prefixBytes,
    false,
  );
  return normalizeSpans(after, remapped);
}

/**
 * The D4 dance. `Document::update_node` (`operations.rs:620-631`) clears a
 * node's spans when a write changes `content` while carrying a spans vector
 * byte-identical to the stored one — identical spans over changed content are
 * indistinguishable from a stale carry-forward, so the engine drops them.
 *
 * That is right for a caller who forgot the spans, and wrong for us: a session
 * whose edits all landed AFTER the last span legitimately maintains the same
 * vector, and it would be cleared. So when the content changed and the
 * maintained vector would reach the engine byte-identical to the stored one,
 * this returns a semantically identical but structurally DIFFERENT vector.
 *
 * ── WHAT IS COMPARED (F1, review 2026-08-24) ─────────────────────────────
 * The candidate is compared against `node.spans` **RAW** — exactly the bytes
 * the document holds — because that is what the engine compares against. It is
 * NOT compared against a normalized copy of them: normalizing hid the very
 * collision this function exists to prevent. The split output is deterministic,
 * so a SECOND suffix edit on an already-split node maintains that split vector,
 * normalizes it back to the merged shape, matched the normalized stored vector,
 * re-split it into precisely what the document already held — and the engine
 * cleared every span. Reading raw, that second edit's merged candidate already
 * differs from the stored split and goes out untouched, which is why a
 * re-authoring is only ever attempted for a vector that really would collide.
 *
 * ── THE TWO RE-AUTHORINGS, IN ORDER ──────────────────────────────────────
 *  1. **SPLIT** one span at an interior char boundary into two adjacent spans
 *     with identical props. Renders identically; adjacency is legal (only
 *     overlap is not). Since the candidate that collided is fully normalized,
 *     any split of it carries one more span than the stored vector and cannot
 *     itself collide — the collision check is kept anyway, because a rule this
 *     load-bearing should not rest on a counting argument.
 *  2. **RESTATE** a channel (F2): when no span has an interior boundary — every
 *     span a single character, e.g. a coloured "!" — set a channel the span
 *     does NOT carry to the node's own value for it. `span.underline ??
 *     node.underline` means an override equal to the base paints identically,
 *     so this changes no pixel while changing the bytes. Order is most-inert
 *     first: the two decorations, then italic (a measurement input, but the
 *     same value measures the same), then the weight — and the weight ONLY for
 *     a node whose weight is its OWN literal, i.e. no `style_token` AND no
 *     token-ref `font_family` ({@link namesTokenRef}, G3), because
 *     `resolvedTextFields` resolves a typography token's weight OVER the node
 *     literal, so restating that literal on a span (which outranks both) would
 *     be a real weight change.
 *
 * ── TWO HONEST LIMITS OF THE RESTATEMENT (G4, review round 2) ────────────
 * Neither is a defect to fix here; both are recorded so nobody reads this
 * fallback as unconditional.
 *
 *  • It is **exhaustible, and reachably so.** Each restatement consumes one
 *    channel of one span, so an unsplittable span (every span one character)
 *    has at most FOUR of them: four consecutive suffix edits burn underline,
 *    strikethrough, italic and the weight, and the FIFTH collides with the
 *    stored vector again — at which point the engine's D4 clear stands. That is
 *    an ordinary sequence of keystrokes on a coloured "!", not a contrived one,
 *    so the earlier "constructible" framing understated it. The clear is still
 *    honest and undo still restores it.
 *  • A restatement is **durable**, not a marker: it writes a real span override
 *    at the node's current value, and the span then STOPS following later
 *    changes to the node's own base. Restating `italic: false` or the weight
 *    pins real pixels; restating a decoration pins what the union-painted
 *    toolbar reads, so a later node-level change can leave the toolbar and the
 *    paint disagreeing over that run.
 *
 * `node` is the STORED node (its `content` and `spans` are what the document
 * holds, and the write is a content edit exactly when `content !== node.content`);
 * `content` is the content BEING WRITTEN, so every offset and split point is a
 * char boundary of IT. The result is deliberately NOT re-normalized — that
 * would merge the split straight back together.
 */
export function spansVectorForContentEdit(
  node: TextNode,
  content: string,
  nextSpans: readonly TextSpan[],
): TextSpan[] {
  const spans = normalizeSpans(content, nextSpans);
  if (content === node.content || spans.length === 0) return spans;
  const storedKey = stableKey(node.spans ?? []);
  if (stableKey(spans) !== storedKey) return spans;
  return (
    splitOneSpan(content, spans, storedKey) ??
    restateOneChannel(node, spans, storedKey) ??
    spans
  );
}

/** Re-authoring 1: the last span that HAS an interior char boundary, split. */
function splitOneSpan(
  content: string,
  spans: readonly TextSpan[],
  storedKey: string,
): TextSpan[] | null {
  const { byteStarts } = indexContent(content);
  for (let index = spans.length - 1; index >= 0; index -= 1) {
    const span = spans[index];
    const split = byteStarts.find((offset) => offset > span.start && offset < span.end);
    if (split === undefined) continue;
    const overrides = spanOverrides(span);
    const candidate = [
      ...spans.slice(0, index),
      makeSpan(span.start, split, overrides),
      makeSpan(split, span.end, overrides),
      ...spans.slice(index + 1),
    ];
    if (stableKey(candidate) !== storedKey) return candidate;
  }
  return null;
}

/** One channel restated at the node's own value — a no-op to the painter. */
type Restatement =
  | { channel: "underline" | "strikethrough" | "italic"; value: boolean }
  | { channel: "font_weight"; value: number };

/**
 * Does this `font_family` name a TOKEN rather than a literal family?
 *
 * The engine's own rule, ported: `resolve_text_style` takes `style_token` when
 * there is one and otherwise falls back to the `font_family` whenever it
 * `looks_like_token_ref` — `$…` or `token(…)`, after trimming
 * (`lumen-core/src/brand.rs:6154`, consumed at `:3928`). A node whose family is
 * a token ref therefore resolves its weight from that typography token exactly
 * as a `style_token` node does, so it has no literal weight to restate either.
 */
export function namesTokenRef(fontFamily: string): boolean {
  return /^\s*(\$|token\()/.test(fontFamily);
}

/** The channels this node can restate without moving a pixel, most inert
 * first. See {@link spansVectorForContentEdit} for why the weight is last and
 * why a token-styled node has no weight to restate. */
function baseRestatements(node: TextNode): Restatement[] {
  const restatements: Restatement[] = [
    { channel: "underline", value: node.underline ?? false },
    { channel: "strikethrough", value: node.strikethrough ?? false },
    { channel: "italic", value: node.italic ?? false },
  ];
  if (!node.style_token && !namesTokenRef(node.font_family)) {
    restatements.push({ channel: "font_weight", value: node.font_weight });
  }
  return restatements;
}

function withRestatement(overrides: SpanOverrides, restatement: Restatement): SpanOverrides {
  switch (restatement.channel) {
    case "font_weight":
      return { ...overrides, font_weight: restatement.value };
    case "underline":
      return { ...overrides, underline: restatement.value };
    case "strikethrough":
      return { ...overrides, strikethrough: restatement.value };
    default:
      return { ...overrides, italic: restatement.value };
  }
}

/** Re-authoring 2: the last span LACKING the most inert restatable channel,
 * wearing that channel at the node's own value. Null when every span already
 * states every channel — the one case where the engine's clear stands. */
function restateOneChannel(
  node: TextNode,
  spans: readonly TextSpan[],
  storedKey: string,
): TextSpan[] | null {
  for (const restatement of baseRestatements(node)) {
    for (let index = spans.length - 1; index >= 0; index -= 1) {
      const span = spans[index];
      if (span[restatement.channel] !== undefined) continue;
      const candidate = [
        ...spans.slice(0, index),
        makeSpan(
          span.start,
          span.end,
          withRestatement(spanOverrides(span), restatement),
        ),
        ...spans.slice(index + 1),
      ];
      if (stableKey(candidate) !== storedKey) return candidate;
    }
  }
  return null;
}
