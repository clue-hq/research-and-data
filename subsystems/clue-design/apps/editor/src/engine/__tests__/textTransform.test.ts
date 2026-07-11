import { describe, expect, it } from "vitest";
import { applyTextTransform } from "../textTransform";

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
