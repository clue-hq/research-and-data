import type { TextTransform } from "./contracts";

/**
 * A6a D1 — the client twin of lumen-core `TextTransform::apply` + `title_case`
 * (`crates/lumen-core/src/scene.rs`). The single helper EVERY editor consumer
 * (SkParagraph measurement + the CanvasKit painter) calls before shaping, so
 * the cased string the editor draws can never disagree with the engine's.
 *
 * Semantics, byte-for-byte with Rust:
 * - `none`      → the content verbatim (never allocates a new string).
 * - `uppercase` → `String::to_uppercase` ≡ JS `toUpperCase` (Unicode-correct;
 *                 "ß" → "SS" in both).
 * - `lowercase` → `String::to_lowercase` ≡ JS `toLowerCase`.
 * - `title`     → uppercase the first ALPHABETIC char of each whitespace-
 *                 separated word, leaving the rest of the word untouched;
 *                 whitespace runs are preserved verbatim so line/word structure
 *                 is stable. Mirrors Rust's `char::is_whitespace` /
 *                 `is_alphabetic` word-start machine.
 *
 * `content` is NEVER mutated: the model string stays canonical; only the
 * display shaping sees the transformed value.
 */
export function applyTextTransform(transform: TextTransform | undefined, content: string): string {
  switch (transform) {
    case "uppercase":
      return content.toUpperCase();
    case "lowercase":
      return content.toLowerCase();
    case "title":
      return titleCase(content);
    case "none":
    case undefined:
    default:
      return content;
  }
}

/** Uppercase the first alphabetic char of each whitespace-separated word, the
 * rest untouched; whitespace preserved. Iterates by code point (spread) so
 * astral characters and multi-char uppercase expansions behave like Rust's
 * `char`-wise loop. */
function titleCase(content: string): string {
  let out = "";
  let atWordStart = true;
  for (const ch of content) {
    if (isWhitespace(ch)) {
      atWordStart = true;
      out += ch;
    } else if (atWordStart && isAlphabetic(ch)) {
      out += ch.toUpperCase();
      atWordStart = false;
    } else {
      out += ch;
      atWordStart = false;
    }
  }
  return out;
}

/** Unicode whitespace, matching Rust `char::is_whitespace` for the characters
 * that appear in real content (spaces, tabs, newlines, and the Unicode space
 * separators). `\s` plus the Rust-only U+0085/U+00A0 cases JS `\s` already
 * covers via the `\s` Unicode class in the RegExp below. */
function isWhitespace(ch: string): boolean {
  // JS \s plus U+0085 (NEL), which Rust char::is_whitespace matches but \s omits.
  return /\s/u.test(ch) || ch === "\u0085";
}

/** Unicode alphabetic, matching Rust `char::is_alphabetic` closely enough for
 * word-start detection (the Unicode `Alphabetic` derived property). */
function isAlphabetic(ch: string): boolean {
  return /\p{Alphabetic}/u.test(ch);
}
