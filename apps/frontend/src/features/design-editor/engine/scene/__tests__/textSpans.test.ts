import { describe, expect, it } from "../../__tests__/vitest-shim";
import type { Paint, TextNode, TextSpan } from "../contracts";
import {
  applyStyleToRange,
  byteToUtf16Offset,
  formatStateForRange,
  normalizeSpans,
  reconcileSpansForReplacement,
  remapSpansByDiff,
  snapRangeToCharBoundaries,
  spanValidationIssues,
  spansVectorForContentEdit,
  utf16ToByteOffset,
  utf8ByteLength,
} from "../textSpans";

/**
 * Rung C core. Every assertion here is in UTF-8 BYTE space over the STORED
 * `content` (A6b D1) — the same space `span_validation_errors` (lumen-core
 * `scene.rs:754`) validates in, and the same space the engine's D4
 * content-edit-clears-spans rule (`operations.rs:620-631`) compares in.
 */

function textNode(overrides: Partial<TextNode> = {}): TextNode {
  return {
    content: "Hello World",
    font_family: "Inter",
    font_size: 24,
    font_weight: 400,
    align: "left",
    ...overrides,
  };
}

const RED: Paint = { kind: "solid", color: { kind: "hex", value: "#ff0000" } };
const BLUE: Paint = { kind: "solid", color: { kind: "hex", value: "#0000ff" } };
const BRAND: Paint = { kind: "token", token: "color.brand.primary" };
const GRADIENT: Paint = {
  kind: "linear_gradient",
  angle: 90,
  stops: [
    { color: { kind: "hex", value: "#ff0000" }, position: 0 },
    { color: { kind: "hex", value: "#0000ff" }, position: 1 },
  ],
};

/** "Hello World" byte offsets: H0 e1 l2 l3 o4 ␠5 W6 o7 r8 l9 d10, len 11. */
const HELLO = "Hello World";
/** a(1 byte) 😀(4 bytes) b(1 byte) = 6 bytes; UTF-16 units: a1 😀2 b1 = 4. */
const EMOJI = "a\u{1F600}b";

describe("utf8ByteLength", () => {
  it("counts UTF-8 bytes, not UTF-16 units", () => {
    expect(utf8ByteLength("")).toBe(0);
    expect(utf8ByteLength(HELLO)).toBe(11);
    expect(utf8ByteLength(EMOJI)).toBe(6);
    expect(utf8ByteLength("café")).toBe(5);
    expect(utf8ByteLength("日本語")).toBe(9);
    expect(utf8ByteLength("é")).toBe(3);
  });
});

describe("utf16ToByteOffset", () => {
  it("is the identity across ASCII", () => {
    for (let index = 0; index <= 11; index += 1) {
      expect(utf16ToByteOffset(HELLO, index)).toBe(index);
    }
  });

  it("maps across a surrogate pair (one emoji = 2 UTF-16 units = 4 bytes)", () => {
    expect(utf16ToByteOffset(EMOJI, 0)).toBe(0);
    expect(utf16ToByteOffset(EMOJI, 1)).toBe(1);
    expect(utf16ToByteOffset(EMOJI, 3)).toBe(5);
    expect(utf16ToByteOffset(EMOJI, 4)).toBe(6);
  });

  it("snaps an index landing inside a surrogate pair LEFT to the code point", () => {
    expect(utf16ToByteOffset(EMOJI, 2)).toBe(1);
  });

  it("clamps out-of-range indices into the content", () => {
    expect(utf16ToByteOffset(EMOJI, -7)).toBe(0);
    expect(utf16ToByteOffset(EMOJI, 99)).toBe(6);
    expect(utf16ToByteOffset("", 4)).toBe(0);
  });

  it("maps multi-byte BMP characters (CJK, accents, combining marks)", () => {
    expect(utf16ToByteOffset("日本語", 1)).toBe(3);
    expect(utf16ToByteOffset("日本語", 2)).toBe(6);
    expect(utf16ToByteOffset("café", 3)).toBe(3);
    expect(utf16ToByteOffset("café", 4)).toBe(5);
    // A combining mark is its own code point: "e" + U+0301 has a boundary at 1.
    expect(utf16ToByteOffset("é", 1)).toBe(1);
    expect(utf16ToByteOffset("é", 2)).toBe(3);
  });
});

describe("byteToUtf16Offset", () => {
  it("inverts the mapping on char boundaries", () => {
    expect(byteToUtf16Offset(EMOJI, 0)).toBe(0);
    expect(byteToUtf16Offset(EMOJI, 1)).toBe(1);
    expect(byteToUtf16Offset(EMOJI, 5)).toBe(3);
    expect(byteToUtf16Offset(EMOJI, 6)).toBe(4);
  });

  it("snaps a byte index inside a multi-byte char LEFT to that char's start", () => {
    expect(byteToUtf16Offset(EMOJI, 2)).toBe(1);
    expect(byteToUtf16Offset(EMOJI, 3)).toBe(1);
    expect(byteToUtf16Offset(EMOJI, 4)).toBe(1);
    expect(byteToUtf16Offset("日本語", 4)).toBe(1);
  });

  it("clamps out-of-range byte indices", () => {
    expect(byteToUtf16Offset(EMOJI, -3)).toBe(0);
    expect(byteToUtf16Offset(EMOJI, 99)).toBe(4);
  });

  it("round-trips every char boundary of mixed-width content", () => {
    const content = "a\u{1F600}b日é";
    let unit = 0;
    for (const char of content) {
      const byte = utf16ToByteOffset(content, unit);
      expect(byteToUtf16Offset(content, byte)).toBe(unit);
      unit += char.length;
    }
    expect(byteToUtf16Offset(content, utf16ToByteOffset(content, unit))).toBe(unit);
  });
});

describe("snapRangeToCharBoundaries", () => {
  it("leaves an already-aligned range alone", () => {
    expect(snapRangeToCharBoundaries(EMOJI, [0, 5])).toEqual([0, 5]);
    expect(snapRangeToCharBoundaries(HELLO, [0, 11])).toEqual([0, 11]);
  });

  it("snaps both edges LEFT onto char boundaries", () => {
    expect(snapRangeToCharBoundaries(EMOJI, [1, 3])).toEqual([1, 1]);
    expect(snapRangeToCharBoundaries(EMOJI, [2, 6])).toEqual([1, 6]);
  });

  it("orders an inverted range and clamps out-of-range edges", () => {
    expect(snapRangeToCharBoundaries(HELLO, [7, 2])).toEqual([2, 7]);
    expect(snapRangeToCharBoundaries(HELLO, [-4, 99])).toEqual([0, 11]);
  });
});

/**
 * The five rules of lumen-core `span_validation_errors`. They run at LAYOUT
 * (LUMV0906), not at apply — an invalid vector applies clean and silently drops
 * the node out of measurement, which is why this is the pre-send gate.
 */
describe("spanValidationIssues", () => {
  it("accepts a sorted, non-overlapping, char-aligned vector", () => {
    expect(
      spanValidationIssues(HELLO, [
        { start: 0, end: 5, font_weight: 700 },
        { start: 6, end: 11, italic: true },
      ]),
    ).toEqual([]);
  });

  it("accepts an empty vector and adjacent spans with identical props", () => {
    expect(spanValidationIssues(HELLO, [])).toEqual([]);
    expect(
      spanValidationIssues(HELLO, [
        { start: 0, end: 2, font_weight: 700 },
        { start: 2, end: 5, font_weight: 700 },
      ]),
    ).toEqual([]);
  });

  it("rejects a range out of bounds for the content", () => {
    const issues = spanValidationIssues(HELLO, [{ start: 0, end: 99, font_weight: 700 }]);
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatch(/out of bounds/);
  });

  it("rejects an empty or inverted range", () => {
    expect(spanValidationIssues(HELLO, [{ start: 5, end: 5, italic: true }])[0]).toMatch(
      /not before/,
    );
    expect(spanValidationIssues(HELLO, [{ start: 7, end: 3, italic: true }])[0]).toMatch(
      /not before/,
    );
  });

  it("rejects offsets off a UTF-8 char boundary", () => {
    const issues = spanValidationIssues(EMOJI, [{ start: 2, end: 4, font_weight: 700 }]);
    expect(issues.some((issue) => /start 2 is not on a UTF-8 char boundary/.test(issue))).toBe(
      true,
    );
    expect(issues.some((issue) => /end 4 is not on a UTF-8 char boundary/.test(issue))).toBe(true);
  });

  it("rejects unsorted or overlapping spans", () => {
    expect(
      spanValidationIssues(HELLO, [
        { start: 6, end: 11, italic: true },
        { start: 0, end: 5, font_weight: 700 },
      ])[0],
    ).toMatch(/overlaps or is unsorted/);
    expect(
      spanValidationIssues(HELLO, [
        { start: 0, end: 6, font_weight: 700 },
        { start: 3, end: 11, italic: true },
      ])[0],
    ).toMatch(/overlaps or is unsorted/);
  });

  it("rejects a gradient span fill (solid or token only)", () => {
    const issues = spanValidationIssues(HELLO, [{ start: 0, end: 5, fill: GRADIENT }]);
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatch(/gradient/);
  });
});

describe("normalizeSpans", () => {
  it("drops override-less spans, merges adjacent identical props, and sorts", () => {
    expect(
      normalizeSpans(HELLO, [
        { start: 6, end: 11, font_weight: 700 },
        { start: 0, end: 3, font_weight: 700 },
        { start: 3, end: 6, font_weight: 700 },
        { start: 5, end: 5 },
      ]),
    ).toEqual([{ start: 0, end: 11, font_weight: 700 }]);
  });

  it("keeps adjacent spans whose props differ", () => {
    expect(
      normalizeSpans(HELLO, [
        { start: 0, end: 5, font_weight: 700 },
        { start: 5, end: 11, italic: true },
      ]),
    ).toEqual([
      { start: 0, end: 5, font_weight: 700 },
      { start: 5, end: 11, italic: true },
    ]);
  });

  it("sanitizes garbage into a vector the engine accepts", () => {
    const spans = normalizeSpans(EMOJI, [
      { start: 2, end: 4, font_weight: 700 },
      { start: 0, end: 99, italic: true },
      { start: 3, end: 3 },
      { start: 0, end: 6, fill: GRADIENT },
    ]);
    expect(spanValidationIssues(EMOJI, spans)).toEqual([]);
  });
});

describe("formatStateForRange", () => {
  const boldHalf = textNode({ spans: [{ start: 0, end: 5, font_weight: 700 }] });

  it("reports on/off per channel for a fully covered range", () => {
    const state = formatStateForRange(boldHalf, [0, 5]);
    expect(state.bold).toBe("on");
    expect(state.italic).toBe("off");
    expect(state.underline).toBe("off");
    expect(state.strikethrough).toBe("off");
  });

  it("reports mixed when the range straddles a span edge", () => {
    expect(formatStateForRange(boldHalf, [0, 11]).bold).toBe("mixed");
    expect(formatStateForRange(boldHalf, [5, 11]).bold).toBe("off");
  });

  it("honours override semantics: italic(false) inside an italic node", () => {
    const node = textNode({ italic: true, spans: [{ start: 0, end: 5, italic: false }] });
    expect(formatStateForRange(node, [0, 5]).italic).toBe("off");
    expect(formatStateForRange(node, [5, 11]).italic).toBe("on");
    expect(formatStateForRange(node, [0, 11]).italic).toBe("mixed");
  });

  it("derives bold from the effective weight against the 700 threshold", () => {
    expect(formatStateForRange(textNode({ font_weight: 600 }), [0, 11]).bold).toBe("off");
    expect(formatStateForRange(textNode({ font_weight: 700 }), [0, 11]).bold).toBe("on");
    const unbolded = textNode({
      font_weight: 800,
      spans: [{ start: 0, end: 5, font_weight: 400 }],
    });
    expect(formatStateForRange(unbolded, [0, 5]).bold).toBe("off");
    expect(formatStateForRange(unbolded, [5, 11]).bold).toBe("on");
    expect(formatStateForRange(unbolded, [0, 11]).bold).toBe("mixed");
  });

  it("reads the effective state AT the caret for a collapsed range", () => {
    expect(formatStateForRange(boldHalf, [2, 2]).bold).toBe("on");
    expect(formatStateForRange(boldHalf, [7, 7]).bold).toBe("off");
    // The span's exclusive end is NOT covered; the caret there reads the base.
    expect(formatStateForRange(boldHalf, [5, 5]).bold).toBe("off");
    expect(formatStateForRange(boldHalf, [11, 11]).bold).toBe("off");
  });

  it("reports a uniform fill of null when no span in the range overrides it", () => {
    expect(formatStateForRange(textNode(), [0, 11]).fill).toEqual({
      kind: "uniform",
      paint: null,
    });
  });

  it("reports a uniform fill when every piece carries the same paint", () => {
    const node = textNode({
      spans: [
        { start: 0, end: 5, fill: BRAND },
        { start: 5, end: 11, fill: BRAND },
      ],
    });
    expect(formatStateForRange(node, [0, 11]).fill).toEqual({ kind: "uniform", paint: BRAND });
  });

  it("reports mixed for solid-vs-token and for a span-vs-inherit mix", () => {
    const twoTone = textNode({
      spans: [
        { start: 0, end: 5, fill: RED },
        { start: 5, end: 11, fill: BRAND },
      ],
    });
    expect(formatStateForRange(twoTone, [0, 11]).fill).toEqual({ kind: "mixed" });
    const partial = textNode({ spans: [{ start: 0, end: 5, fill: RED }] });
    expect(formatStateForRange(partial, [0, 11]).fill).toEqual({ kind: "mixed" });
    expect(formatStateForRange(partial, [0, 5]).fill).toEqual({ kind: "uniform", paint: RED });
    const twoSolids = textNode({
      spans: [
        { start: 0, end: 5, fill: RED },
        { start: 6, end: 11, fill: BLUE },
      ],
    });
    expect(formatStateForRange(twoSolids, [0, 11]).fill).toEqual({ kind: "mixed" });
  });

  it("falls back to the node base for an empty or span-less node", () => {
    const state = formatStateForRange(textNode({ content: "", spans: [] }), [0, 0]);
    expect(state.bold).toBe("off");
    expect(state.fill).toEqual({ kind: "uniform", paint: null });
  });
});

describe("applyStyleToRange", () => {
  const validated = (node: TextNode, spans: TextSpan[]): TextSpan[] => {
    expect(spanValidationIssues(node.content, spans)).toEqual([]);
    return spans;
  };

  it("creates a span for a range with no existing spans", () => {
    const node = textNode();
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: true }))).toEqual([
      { start: 0, end: 5, font_weight: 700 },
    ]);
  });

  it("leaves a disjoint span untouched and does not merge across a gap", () => {
    const node = textNode({ spans: [{ start: 6, end: 11, font_weight: 700 }] });
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: true }))).toEqual([
      { start: 0, end: 5, font_weight: 700 },
      { start: 6, end: 11, font_weight: 700 },
    ]);
  });

  it("merges an abutting span with identical props", () => {
    const node = textNode({ spans: [{ start: 5, end: 11, font_weight: 700 }] });
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: true }))).toEqual([
      { start: 0, end: 11, font_weight: 700 },
    ]);
  });

  it("splits a span that contains the range, preserving the outer parts", () => {
    const node = textNode({ spans: [{ start: 0, end: 11, font_weight: 700 }] });
    expect(validated(node, applyStyleToRange(node, [3, 5], { italic: true }))).toEqual([
      { start: 0, end: 3, font_weight: 700 },
      { start: 3, end: 5, font_weight: 700, italic: true },
      { start: 5, end: 11, font_weight: 700 },
    ]);
  });

  it("absorbs a span contained by the range", () => {
    const node = textNode({ spans: [{ start: 3, end: 5, font_weight: 700 }] });
    expect(validated(node, applyStyleToRange(node, [0, 11], { bold: true }))).toEqual([
      { start: 0, end: 11, font_weight: 700 },
    ]);
  });

  it("trims a span overlapping the range start", () => {
    const node = textNode({ spans: [{ start: 0, end: 6, fill: RED }] });
    expect(validated(node, applyStyleToRange(node, [3, 11], { italic: true }))).toEqual([
      { start: 0, end: 3, fill: RED },
      { start: 3, end: 6, fill: RED, italic: true },
      { start: 6, end: 11, italic: true },
    ]);
  });

  it("trims a span overlapping the range end", () => {
    const node = textNode({ spans: [{ start: 6, end: 11, fill: RED }] });
    expect(validated(node, applyStyleToRange(node, [0, 8], { italic: true }))).toEqual([
      { start: 0, end: 6, italic: true },
      { start: 6, end: 8, fill: RED, italic: true },
      { start: 8, end: 11, fill: RED },
    ]);
  });

  it("is a no-op shape for an exact-match range already carrying the style", () => {
    const node = textNode({ spans: [{ start: 0, end: 5, font_weight: 700 }] });
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: true }))).toEqual([
      { start: 0, end: 5, font_weight: 700 },
    ]);
  });

  it("preserves the other channels of every overlapped span", () => {
    const node = textNode({ spans: [{ start: 0, end: 11, fill: RED }] });
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: true }))).toEqual([
      { start: 0, end: 5, fill: RED, font_weight: 700 },
      { start: 5, end: 11, fill: RED },
    ]);
  });

  it("spans a range crossing several existing spans, one channel at a time", () => {
    const node = textNode({
      spans: [
        { start: 0, end: 4, fill: RED },
        { start: 6, end: 11, italic: true },
      ],
    });
    expect(validated(node, applyStyleToRange(node, [2, 8], { underline: true }))).toEqual([
      { start: 0, end: 2, fill: RED },
      { start: 2, end: 4, fill: RED, underline: true },
      { start: 4, end: 6, underline: true },
      { start: 6, end: 8, italic: true, underline: true },
      { start: 8, end: 11, italic: true },
    ]);
  });

  it("un-bolds a range inside a bold-weighted node with an explicit 400 override", () => {
    const node = textNode({ font_weight: 800 });
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: false }))).toEqual([
      { start: 0, end: 5, font_weight: 400 },
    ]);
  });

  it("un-bolds by REMOVING the override when the node base is not bold", () => {
    const node = textNode({ spans: [{ start: 0, end: 5, font_weight: 700 }] });
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: false }))).toEqual([]);
  });

  it("bolds by REMOVING the override when the node base is already bold", () => {
    const node = textNode({ font_weight: 800, spans: [{ start: 0, end: 5, font_weight: 400 }] });
    expect(validated(node, applyStyleToRange(node, [0, 5], { bold: true }))).toEqual([]);
  });

  it("removes an override that matches the node base for the flag channels", () => {
    const node = textNode({ italic: true });
    expect(validated(node, applyStyleToRange(node, [0, 5], { italic: true }))).toEqual([]);
    const strike = textNode({ strikethrough: true, spans: [{ start: 0, end: 5, strikethrough: false }] });
    expect(validated(strike, applyStyleToRange(strike, [0, 5], { strikethrough: true }))).toEqual(
      [],
    );
  });

  it("sets and clears a fill override", () => {
    const plain = textNode();
    expect(validated(plain, applyStyleToRange(plain, [0, 5], { fill: BRAND }))).toEqual([
      { start: 0, end: 5, fill: BRAND },
    ]);
    const filled = textNode({ spans: [{ start: 0, end: 5, fill: RED }] });
    expect(validated(filled, applyStyleToRange(filled, [0, 5], { fill: null }))).toEqual([]);
  });

  it("returns the normalized existing vector for a collapsed range", () => {
    const node = textNode({
      spans: [
        { start: 0, end: 3, font_weight: 700 },
        { start: 3, end: 5, font_weight: 700 },
      ],
    });
    expect(validated(node, applyStyleToRange(node, [4, 4], { italic: true }))).toEqual([
      { start: 0, end: 5, font_weight: 700 },
    ]);
  });

  it("snaps a range off a char boundary before applying anything", () => {
    const node = textNode({ content: EMOJI });
    expect(validated(node, applyStyleToRange(node, [1, 5], { bold: true }))).toEqual([
      { start: 1, end: 5, font_weight: 700 },
    ]);
    // [1,3) collapses onto the emoji's start once snapped: a no-op, never an
    // invalid mid-char span.
    expect(validated(node, applyStyleToRange(node, [1, 3], { bold: true }))).toEqual([]);
  });

  it("never emits a gradient span fill even when handed one", () => {
    const node = textNode();
    const spans = applyStyleToRange(node, [0, 5], { fill: GRADIENT as never });
    expect(spanValidationIssues(node.content, spans)).toEqual([]);
  });
});

describe("reconcileSpansForReplacement", () => {
  const bold = (): TextSpan[] => [{ start: 0, end: 5, font_weight: 700 }];

  it("shifts a span when text is inserted entirely before it", () => {
    const result = reconcileSpansForReplacement(HELLO, bold(), 0, 0, "Say ");
    expect(result.content).toBe("Say Hello World");
    expect(result.spans).toEqual([{ start: 4, end: 9, font_weight: 700 }]);
    expect(spanValidationIssues(result.content, result.spans)).toEqual([]);
  });

  it("extends a span when the edit is strictly inside it (styling survives typing)", () => {
    const result = reconcileSpansForReplacement(HELLO, bold(), 2, 2, "XX");
    expect(result.content).toBe("HeXXllo World");
    expect(result.spans).toEqual([{ start: 0, end: 7, font_weight: 700 }]);
  });

  it("leaves a span alone when text is inserted at its exclusive end", () => {
    const result = reconcileSpansForReplacement(HELLO, bold(), 5, 5, "!");
    expect(result.content).toBe("Hello! World");
    expect(result.spans).toEqual([{ start: 0, end: 5, font_weight: 700 }]);
  });

  it("leaves a span alone when the edit is entirely after it", () => {
    const result = reconcileSpansForReplacement(HELLO, bold(), 6, 11, "Earth");
    expect(result.content).toBe("Hello Earth");
    expect(result.spans).toEqual([{ start: 0, end: 5, font_weight: 700 }]);
  });

  it("trims a span straddling the end of a deletion", () => {
    const result = reconcileSpansForReplacement(HELLO, bold(), 3, 7, "");
    expect(result.content).toBe("Helorld");
    expect(result.spans).toEqual([{ start: 0, end: 3, font_weight: 700 }]);
  });

  it("trims and shifts a span straddling the start of a deletion", () => {
    const result = reconcileSpansForReplacement(
      HELLO,
      [{ start: 6, end: 11, font_weight: 700 }],
      4,
      8,
      "",
    );
    expect(result.content).toBe("Hellrld");
    expect(result.spans).toEqual([{ start: 4, end: 7, font_weight: 700 }]);
  });

  it("drops a span swallowed by the replacement", () => {
    const result = reconcileSpansForReplacement(HELLO, bold(), 0, 11, "Bye");
    expect(result.content).toBe("Bye");
    expect(result.spans).toEqual([]);
  });

  it("shrinks a span when the deletion is strictly inside it", () => {
    const result = reconcileSpansForReplacement(
      HELLO,
      [{ start: 0, end: 11, italic: true }],
      3,
      7,
      "",
    );
    expect(result.content).toBe("Helorld");
    expect(result.spans).toEqual([{ start: 0, end: 7, italic: true }]);
  });

  it("works in byte space over multi-byte content", () => {
    const content = "\u{1F600}\u{1F600}\u{1F600}";
    const result = reconcileSpansForReplacement(
      content,
      [{ start: 4, end: 8, font_weight: 700 }],
      0,
      4,
      "",
    );
    expect(result.content).toBe("\u{1F600}\u{1F600}");
    expect(result.spans).toEqual([{ start: 0, end: 4, font_weight: 700 }]);
    expect(spanValidationIssues(result.content, result.spans)).toEqual([]);
  });

  it("snaps a replacement range that lands mid-character", () => {
    const result = reconcileSpansForReplacement(EMOJI, [], 2, 3, "X");
    expect(result.content).toBe("aX\u{1F600}b");
  });

  it("keeps every other span in the vector sorted and non-overlapping", () => {
    const result = reconcileSpansForReplacement(
      HELLO,
      [
        { start: 0, end: 5, font_weight: 700 },
        { start: 6, end: 11, italic: true },
      ],
      5,
      6,
      " brave ",
    );
    expect(result.content).toBe("Hello brave World");
    expect(result.spans).toEqual([
      { start: 0, end: 5, font_weight: 700 },
      { start: 12, end: 17, italic: true },
    ]);
    expect(spanValidationIssues(result.content, result.spans)).toEqual([]);
  });
});

describe("remapSpansByDiff", () => {
  it("keeps spans that live entirely inside the common prefix", () => {
    expect(
      remapSpansByDiff(HELLO, "Hello Brave World", [{ start: 0, end: 5, font_weight: 700 }]),
    ).toEqual([{ start: 0, end: 5, font_weight: 700 }]);
  });

  it("shifts spans that live entirely inside the common suffix", () => {
    expect(
      remapSpansByDiff(HELLO, "Hello Brave World", [{ start: 6, end: 11, font_weight: 700 }]),
    ).toEqual([{ start: 12, end: 17, font_weight: 700 }]);
  });

  it("trims a span that touches the changed middle back to the prefix", () => {
    expect(remapSpansByDiff(HELLO, "Hello Earth", [{ start: 0, end: 11, font_weight: 700 }])).toEqual(
      [{ start: 0, end: 6, font_weight: 700 }],
    );
  });

  it("drops a span that lives entirely in the changed middle (never guesses)", () => {
    expect(remapSpansByDiff(HELLO, "Hello Earth", [{ start: 6, end: 11, font_weight: 700 }])).toEqual(
      [],
    );
  });

  it("returns the vector untouched when nothing changed", () => {
    expect(remapSpansByDiff(HELLO, HELLO, [{ start: 0, end: 5, italic: true }])).toEqual([
      { start: 0, end: 5, italic: true },
    ]);
  });

  it("computes the prefix/suffix in code points, so multi-byte edges stay aligned", () => {
    expect(remapSpansByDiff("café", "cafés", [{ start: 3, end: 5, font_weight: 700 }])).toEqual([
      { start: 3, end: 5, font_weight: 700 },
    ]);
    const emoji = remapSpansByDiff(
      "\u{1F600}ok",
      "\u{1F600}okay",
      [{ start: 0, end: 4, italic: true }],
    );
    expect(emoji).toEqual([{ start: 0, end: 4, italic: true }]);
  });

  it("survives a full replacement by dropping everything", () => {
    expect(remapSpansByDiff(HELLO, "Totally different", [{ start: 0, end: 5, italic: true }])).toEqual(
      [],
    );
  });

  it("always emits a vector valid against the AFTER content", () => {
    const cases: Array<[string, string]> = [
      [HELLO, "Hello"],
      [HELLO, ""],
      ["", HELLO],
      [EMOJI, "a\u{1F600}\u{1F600}b"],
      ["日本語", "日語"],
    ];
    for (const [before, after] of cases) {
      const spans = remapSpansByDiff(before, after, [
        { start: 0, end: Math.max(1, utf8ByteLength(before)), font_weight: 700 },
      ]);
      expect(spanValidationIssues(after, spans), `${before} -> ${after}`).toEqual([]);
    }
  });
});

/**
 * The D4 dance: `operations.rs:620-631` clears spans when a write changes
 * `content` while carrying a BYTE-IDENTICAL spans vector (indistinguishable
 * from a stale carry-forward). A re-authored, structurally different vector
 * survives.
 */
describe("spansVectorForContentEdit", () => {
  /** The STORED node a commit is measured against: its `content` is what the
   * document holds and its `spans` are the vector the engine will compare the
   * write against — RAW, exactly as they sit in the document. */
  const storedNode = (content: string, spans: TextSpan[], rest: Partial<TextNode> = {}) =>
    textNode({ content, spans, ...rest });

  it("passes the vector through when the content did not change", () => {
    const spans: TextSpan[] = [{ start: 0, end: 5, font_weight: 700 }];
    expect(spansVectorForContentEdit(storedNode(HELLO, spans), HELLO, spans)).toEqual(spans);
  });

  it("passes the vector through when it already differs from the stored one", () => {
    const before: TextSpan[] = [{ start: 0, end: 5, font_weight: 700 }];
    const after: TextSpan[] = [{ start: 0, end: 7, font_weight: 700 }];
    expect(
      spansVectorForContentEdit(storedNode(HELLO, before), "Hello!! World", after),
    ).toEqual(after);
  });

  it("splits the last span so a byte-identical vector survives the content edit", () => {
    const before: TextSpan[] = [{ start: 0, end: 5, font_weight: 700 }];
    const result = spansVectorForContentEdit(
      storedNode(HELLO, before),
      "Hello World!",
      before,
    );
    expect(result).toEqual([
      { start: 0, end: 1, font_weight: 700 },
      { start: 1, end: 5, font_weight: 700 },
    ]);
    // The engine compares the vectors structurally: this one must NOT match.
    expect(JSON.stringify(result)).not.toBe(JSON.stringify(before));
    expect(spanValidationIssues("Hello World!", result)).toEqual([]);
  });

  it("splits the LAST span when several are present", () => {
    const before: TextSpan[] = [
      { start: 0, end: 5, font_weight: 700 },
      { start: 6, end: 11, italic: true },
    ];
    const result = spansVectorForContentEdit(
      storedNode(HELLO, before),
      "Hello World!",
      before,
    );
    expect(result).toEqual([
      { start: 0, end: 5, font_weight: 700 },
      { start: 6, end: 7, italic: true },
      { start: 7, end: 11, italic: true },
    ]);
  });

  it("returns an empty vector as-is (there is nothing for the engine to clear)", () => {
    expect(spansVectorForContentEdit(storedNode("Hello", []), "Hello!", [])).toEqual([]);
  });

  /**
   * F1 (review 2026-08-24, P1): the guard compares against the RAW stored
   * vector, because that is what the engine compares against
   * (`after.spans == before.spans` over the stored bytes). Comparing against
   * the NORMALIZED stored vector made the split self-defeating: the split
   * output is deterministic, so a second suffix edit — whose maintained vector
   * normalizes back to the pre-split shape — regenerated exactly the stored
   * split and the engine cleared every span.
   */
  it("a SECOND suffix edit does not regenerate the stored split (the D4 collision)", () => {
    // What the FIRST suffix edit wrote: one bold run, split in two.
    const stored: TextSpan[] = [
      { start: 0, end: 1, font_weight: 700 },
      { start: 1, end: 5, font_weight: 700 },
    ];
    const result = spansVectorForContentEdit(
      storedNode("Hello World!", stored),
      "Hello World!!",
      stored,
    );
    // The merged shape is itself the re-authoring: same styling, structurally
    // different from what the document holds, so D4 cannot read it as stale.
    expect(result).toEqual([{ start: 0, end: 5, font_weight: 700 }]);
    expect(JSON.stringify(result)).not.toBe(JSON.stringify(stored));
    expect(spanValidationIssues("Hello World!!", result)).toEqual([]);
  });

  it("chains: three suffix edits in a row each keep the styling alive", () => {
    let content = HELLO;
    let stored: TextSpan[] = [{ start: 0, end: 5, font_weight: 700 }];
    for (const suffix of ["!", "!!", "!!!"]) {
      const next = `${HELLO}${suffix}`;
      const vector = spansVectorForContentEdit(storedNode(content, stored), next, stored);
      expect(JSON.stringify(vector), `after "${suffix}"`).not.toBe(JSON.stringify(stored));
      expect(spanValidationIssues(next, vector)).toEqual([]);
      // Whatever shape it takes, it still says "the first five bytes are bold".
      expect(formatStateForRange(textNode({ content: next, spans: vector }), [0, 5]).bold).toBe(
        "on",
      );
      content = next;
      stored = vector;
    }
  });

  /**
   * F2 (review 2026-08-24, P3-1): when nothing can be split — every span one
   * character wide — the vector used to go out unchanged and the engine cleared
   * it (a coloured "!" died on any suffix edit). It now RESTATES a channel the
   * span does not carry at the node's own value: renders identically, and the
   * engine can no longer mistake it for a carry-forward.
   */
  it("restates a no-op channel when no span has an interior char boundary", () => {
    const before: TextSpan[] = [{ start: 1, end: 5, font_weight: 700 }];
    const result = spansVectorForContentEdit(
      storedNode(EMOJI, before, { underline: false }),
      `${EMOJI}!`,
      before,
    );
    expect(result).toEqual([
      { start: 1, end: 5, font_weight: 700, underline: false },
    ]);
    expect(JSON.stringify(result)).not.toBe(JSON.stringify(before));
    expect(spanValidationIssues(`${EMOJI}!`, result)).toEqual([]);
    // Identical pixels: the restated value IS the node's own.
    const painted = textNode({ content: `${EMOJI}!`, spans: result });
    expect(formatStateForRange(painted, [1, 5]).underline).toBe("off");
    expect(formatStateForRange(painted, [1, 5]).bold).toBe("on");
  });

  it("restates the node's TRUE base, not a default (an underlined node restates true)", () => {
    const before: TextSpan[] = [{ start: 1, end: 5, font_weight: 700 }];
    const result = spansVectorForContentEdit(
      storedNode(EMOJI, before, { underline: true }),
      `${EMOJI}!`,
      before,
    );
    expect(result).toEqual([
      { start: 1, end: 5, font_weight: 700, underline: true },
    ]);
    expect(
      formatStateForRange(textNode({ content: `${EMOJI}!`, spans: result, underline: true }), [
        1, 5,
      ]).underline,
    ).toBe("on");
  });

  it("falls through the decoration channels to the WEIGHT when they are all stated", () => {
    const before: TextSpan[] = [
      { start: 1, end: 5, italic: true, underline: true, strikethrough: true },
    ];
    const result = spansVectorForContentEdit(
      storedNode(EMOJI, before, { font_weight: 600 }),
      `${EMOJI}!`,
      before,
    );
    expect(result).toEqual([
      {
        start: 1,
        end: 5,
        font_weight: 600,
        underline: true,
        strikethrough: true,
        italic: true,
      },
    ]);
  });

  it("never restates the weight of a TOKEN-styled node — the token outranks the literal", () => {
    // `resolvedTextFields` resolves `style_token`'s weight OVER `font_weight`,
    // so restating the literal on a span would be a real weight change, not a
    // no-op. The engine's clear is the honest answer instead.
    const before: TextSpan[] = [
      { start: 1, end: 5, italic: true, underline: true, strikethrough: true },
    ];
    expect(
      spansVectorForContentEdit(
        storedNode(EMOJI, before, { font_weight: 600, style_token: "text.heading" }),
        `${EMOJI}!`,
        before,
      ),
    ).toEqual(before);
  });

  it("never restates the weight of a node whose FONT_FAMILY names a token ref", () => {
    // G3 (review round 2, 2026-08-24): `style_token` is not the only style-token
    // source. `resolve_text_style` falls back to the `font_family` when it
    // LOOKS LIKE a token ref — `$…` or `token(…)` (`brand.rs:6154`) — and
    // resolves that typography token's weight over the node literal, exactly as
    // a `style_token` does. So restating the literal weight on a span (which
    // outranks both) is a real change at export for this node too.
    const before: TextSpan[] = [
      { start: 1, end: 5, italic: true, underline: true, strikethrough: true },
    ];
    for (const font_family of ["$text.heading", "token(text.heading)", "  $text.heading"]) {
      expect(
        spansVectorForContentEdit(
          storedNode(EMOJI, before, { font_weight: 600, font_family }),
          `${EMOJI}!`,
          before,
        ),
        font_family,
      ).toEqual(before);
    }
    // …and the guard is not over-broad: a literal family still restates.
    expect(
      spansVectorForContentEdit(
        storedNode(EMOJI, before, { font_weight: 600, font_family: "Inter" }),
        `${EMOJI}!`,
        before,
      ),
    ).toEqual([
      { start: 1, end: 5, font_weight: 600, italic: true, underline: true, strikethrough: true },
    ]);
  });

  it("accepts the engine's clear when every channel is already restated", () => {
    // The one genuinely unconstructible case, and it IS constructible: a
    // single-character span that already states every channel has no split to
    // take and no channel left to restate. The clear is honest, and undo
    // restores it (this was the pre-F2 behaviour of EVERY unsplittable vector).
    const before: TextSpan[] = [
      {
        start: 1,
        end: 5,
        fill: RED,
        font_weight: 700,
        underline: true,
        strikethrough: true,
        italic: true,
      },
    ];
    expect(
      spansVectorForContentEdit(storedNode(EMOJI, before), `${EMOJI}!`, before),
    ).toEqual(before);
  });
});

/**
 * The module's whole reason to exist: an invalid vector applies clean and
 * silently breaks measurement, so NO output of any function here may violate
 * the five rules. This sweep drives every entry point over a deterministic
 * pseudo-random table of unicode contents, ranges and patches.
 */
describe("span validity is closed under every operation", () => {
  const contents = [
    "",
    "a",
    HELLO,
    EMOJI,
    "日本語のテキスト",
    "café naïve",
    "\u{1F600}\u{1F1EE}\u{1F1F3}ok",
    "line one\nline two",
  ];
  const patches = [
    { bold: true },
    { bold: false },
    { italic: true },
    { italic: false },
    { underline: true },
    { strikethrough: false },
    { fill: RED },
    { fill: BRAND },
    { fill: null },
  ] as const;

  /** Deterministic LCG so a failure is reproducible from the case index. */
  const rng = (seed: number) => {
    let state = seed;
    return () => {
      state = (state * 1664525 + 1013904223) % 4294967296;
      return state / 4294967296;
    };
  };

  it("applyStyleToRange output always validates, over random ranges and patches", () => {
    const next = rng(20260824);
    for (const content of contents) {
      const limit = utf8ByteLength(content);
      let node = textNode({ content, font_weight: 400 });
      for (let step = 0; step < 60; step += 1) {
        const a = Math.floor(next() * (limit + 3)) - 1;
        const b = Math.floor(next() * (limit + 3)) - 1;
        const patch = patches[Math.floor(next() * patches.length)];
        const spans = applyStyleToRange(node, [a, b], patch);
        expect(spanValidationIssues(content, spans), `${content} [${a},${b}] step ${step}`).toEqual(
          [],
        );
        node = { ...node, spans };
      }
    }
  });

  it("reconciliation output always validates, over random replacements", () => {
    const next = rng(4242);
    for (const content of contents) {
      const limit = utf8ByteLength(content);
      const spans = normalizeSpans(content, [
        { start: 0, end: Math.max(1, Math.floor(limit / 2)), font_weight: 700 },
        { start: Math.max(1, Math.floor(limit / 2)), end: Math.max(2, limit), italic: true },
      ]);
      for (let step = 0; step < 60; step += 1) {
        const a = Math.floor(next() * (limit + 2));
        const b = Math.floor(next() * (limit + 2));
        const inserted = ["", "x", "\u{1F600}", "日本"][Math.floor(next() * 4)];
        const result = reconcileSpansForReplacement(content, spans, a, b, inserted);
        expect(
          spanValidationIssues(result.content, result.spans),
          `${content} [${a},${b}] +${inserted} step ${step}`,
        ).toEqual([]);
        const remapped = remapSpansByDiff(content, result.content, spans);
        expect(
          spanValidationIssues(result.content, remapped),
          `diff ${content} -> ${result.content} step ${step}`,
        ).toEqual([]);
        const d4 = spansVectorForContentEdit(
          textNode({ content, spans }),
          result.content,
          result.spans,
        );
        expect(spanValidationIssues(result.content, d4), `d4 step ${step}`).toEqual([]);
      }
    }
  });

  it("format state is total over random ranges", () => {
    const next = rng(7);
    for (const content of contents) {
      const limit = utf8ByteLength(content);
      const node = textNode({
        content,
        italic: true,
        spans: normalizeSpans(content, [
          { start: 0, end: Math.max(1, Math.floor(limit / 2)), font_weight: 700, fill: RED },
        ]),
      });
      for (let step = 0; step < 40; step += 1) {
        const a = Math.floor(next() * (limit + 3)) - 1;
        const b = Math.floor(next() * (limit + 3)) - 1;
        const state = formatStateForRange(node, [a, b]);
        expect(["on", "off", "mixed"], `${content} [${a},${b}]`).toContain(state.bold);
        expect(["on", "off", "mixed"]).toContain(state.italic);
        expect(["on", "off", "mixed"]).toContain(state.underline);
        expect(["on", "off", "mixed"]).toContain(state.strikethrough);
        expect(["uniform", "mixed"]).toContain(state.fill.kind);
      }
    }
  });
});
