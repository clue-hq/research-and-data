import { describe, expect, it } from "../../__tests__/vitest-shim";
import { applyTextTransform, normalizeContentMapped, transformSegments } from "../textTransform";

/**
 * A6a D1 parity pin: the same fixture strings as the Rust test
 * `a6_typography_tests::transformed_content_is_unicode_correct_and_never_mutates`
 * in `crates/lumen-core/src/scene.rs`. If either side drifts, one of these
 * assertions breaks — that is the whole point of measuring parity here.
 */
describe("applyTextTransform", () => {
  const base = "hello WORLD ßtraße";

  it("none returns the content verbatim and never mutates it", () => {
    expect(applyTextTransform("none", base)).toBe(base);
    expect(applyTextTransform(undefined, base)).toBe(base);
  });

  it("uppercase is Unicode-correct (ß → SS, matching Rust)", () => {
    expect(applyTextTransform("uppercase", base)).toBe("HELLO WORLD SSTRASSE");
  });

  it("lowercase is Unicode-correct and leaves ß intact", () => {
    expect(applyTextTransform("lowercase", base)).toBe("hello world ßtraße");
  });

  it("title uppercases the first alphabetic char of each word, rest untouched", () => {
    expect(applyTextTransform("title", "the quick brown-fox 3rd")).toBe("The Quick Brown-fox 3rd");
  });

  it("title preserves whitespace runs and skips leading non-alphabetic chars", () => {
    // Hyphen is not whitespace, so "brown-fox" is one word: only 'b' is cased.
    // A digit-led word ("3rd") has no alphabetic first char to raise.
    expect(applyTextTransform("title", "  two   spaces")).toBe("  Two   Spaces");
  });

  it("does not mutate the input string", () => {
    const input = "hello WORLD ßtraße";
    applyTextTransform("uppercase", input);
    expect(input).toBe("hello WORLD ßtraße");
  });
});

/**
 * A6b D5 parity pins: the same fixtures as the Rust integration test
 * `crates/lumen-core/tests/a6b_spans.rs` (`d5_*`, `normalize_map_*`). The
 * stateful title-case cursor and the byte-offset normalize map are the two
 * cross-backend seams the orchestrator flagged, so they are pinned to the exact
 * Rust assertions.
 */
describe("transformSegments (A6b D5 segment-stateful transform)", () => {
  it("title-case carries word-start state across a mid-word span boundary", () => {
    // "sunshine" with a span mid-word [3,8) ("shine"). Title-case must NOT
    // re-capitalize at the boundary — the word started before it.
    const segments = transformSegments("sunshine", [[3, 8]], "title");
    expect(segments.map((s) => s.text).join("")).toBe("Sunshine");
    const spanSeg = segments.find((s) => s.span === 0);
    expect(spanSeg?.text).toBe("shine"); // no phantom capital
  });

  it("uppercase/lowercase are per-segment and UTF-8-byte-offset correct", () => {
    // "héllo world": the span [0,6) covers "héllo" exactly (é is 2 bytes), so
    // byte-offset arithmetic — not char/UTF-16 indices — must slice it.
    const upper = transformSegments("héllo world", [[0, 6]], "uppercase");
    expect(upper.map((s) => s.text).join("")).toBe("HÉLLO WORLD");
    expect(upper.find((s) => s.span === 0)?.text).toBe("HÉLLO");
  });

  it("none returns segments whose concatenation is the verbatim content", () => {
    const segments = transformSegments("Every outage now", [[6, 12]], "none");
    expect(segments.map((s) => s.text).join("")).toBe("Every outage now");
    // Base run before, span run, base run after.
    expect(segments.map((s) => s.span)).toEqual([null, 0, null]);
    expect(segments.map((s) => s.text)).toEqual(["Every ", "outage", " now"]);
  });

  it("emits only base runs when there are no spans", () => {
    const segments = transformSegments("plain text", [], "none");
    expect(segments).toEqual([{ text: "plain text", span: null }]);
  });
});

describe("normalizeContentMapped (A6b offset relocation)", () => {
  it("collapses literal \\n, trims a trailing newline, and relocates offsets", () => {
    // Literal "\n" (2 bytes) collapses to one; a trailing "\n" is trimmed.
    const { normalized, map } = normalizeContentMapped("a\\nbc\\n");
    expect(normalized).toBe("a\nbc");
    // Raw offset of 'b' (after "a\n" = 3 raw bytes) maps to normalized 2.
    expect(map[3]).toBe(2);
  });

  it("is the identity map for content with no escapes", () => {
    const { normalized, map } = normalizeContentMapped("Every outage now");
    expect(normalized).toBe("Every outage now");
    // map's last entry is the normalized byte length (the fallback offset).
    expect(map[map.length - 1]).toBe(16);
    expect(map[6]).toBe(6);
  });
});
