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

// ---------------------------------------------------------------------------
// A6b — the segment-stateful twin of lumen-core `normalize_content_mapped` +
// `transform_segments` (`crates/lumen-core/src/scene.rs`). Span offsets in the
// model are UTF-8 BYTE offsets into the STORED `content` string, so the port
// works in byte space (via TextEncoder/TextDecoder) to stay byte-faithful with
// the Rust byte-index arithmetic — an accented span boundary (e.g. `é` = 2
// bytes) relocates identically on both sides.
// ---------------------------------------------------------------------------

const utf8Encoder = new TextEncoder();
const utf8Decoder = new TextDecoder();

/** One contiguous piece of transformed content (A6b D5/D6), tagged with the
 * span it belongs to (`null` = base style). Concatenating every segment's
 * `text` reproduces the fully transformed content. Mirrors Rust `SpanSegment`
 * (`span: Option<usize>` → `number | null`). */
export interface SpanSegment {
  text: string;
  /** Index into the node's `spans`, or `null` for the base run. */
  span: number | null;
}

/**
 * Port of lumen-core `normalize_content_mapped`: DSL literal `\n` / `\r\n`
 * collapse to a real newline and a trailing newline is trimmed
 * (`normalize_content` semantics), AND a raw-byte → normalized-byte offset map
 * is built so span offsets that index the STORED content (A6b D1) relocate onto
 * the normalized string both the measurer and the painter shape. `map[i]` is
 * the normalized byte offset of raw byte `i`, for every `i` in `0..=raw.len()`
 * (byte lengths, UTF-8). The last entry (`map[rawLen]`) is the normalized byte
 * length, which callers use as the out-of-range fallback.
 */
export function normalizeContentMapped(raw: string): { normalized: string; map: number[] } {
  const rawLen = utf8Encoder.encode(raw).length;
  const map = new Array<number>(rawLen + 1).fill(0);
  const out: number[] = [];
  const chars = Array.from(raw); // iterate by code point, like Rust `char_indices`
  let byteIdx = 0;
  for (let ci = 0; ci < chars.length; ci += 1) {
    const ch = chars[ci];
    const chBytes = utf8Encoder.encode(ch);
    map[byteIdx] = out.length;
    // Literal "\n" (backslash + 'n', two ASCII bytes) → one newline; the 'n'
    // byte collapses onto the newline offset.
    if (ch === "\\" && chars[ci + 1] === "n") {
      map[byteIdx + chBytes.length] = out.length;
      out.push(0x0a);
      byteIdx += chBytes.length + 1;
      ci += 1;
      continue;
    }
    // CRLF → one newline.
    if (ch === "\r" && chars[ci + 1] === "\n") {
      map[byteIdx + chBytes.length] = out.length;
      out.push(0x0a);
      byteIdx += chBytes.length + 1;
      ci += 1;
      continue;
    }
    const start = out.length;
    for (const b of chBytes) {
      out.push(b);
    }
    // Continuation bytes of a multi-byte char point at the char's start (they
    // are never span boundaries — validation requires char alignment).
    for (let cont = byteIdx + 1; cont < byteIdx + chBytes.length; cont += 1) {
      map[cont] = start;
    }
    byteIdx += chBytes.length;
  }
  map[rawLen] = out.length;

  // Trim a trailing newline run (mirrors `trim_end_matches('\n')`) and clamp
  // every mapped offset into the trim.
  let trimmedLen = out.length;
  while (trimmedLen > 0 && out[trimmedLen - 1] === 0x0a) {
    trimmedLen -= 1;
  }
  for (let i = 0; i < map.length; i += 1) {
    map[i] = Math.min(map[i], trimmedLen);
  }
  const normalized = utf8Decoder.decode(Uint8Array.from(out.slice(0, trimmedLen)));
  return { normalized, map };
}

/**
 * Port of lumen-core `transform_segments`: split `normalized` at `boundaries`
 * (already-normalized `[start, end]` byte ranges, in order, non-overlapping) and
 * apply `transform` to each piece with a STATEFUL title-case cursor that carries
 * word-start state across segment boundaries (A6b D5) — a span starting mid-word
 * never re-capitalizes. Uppercase/lowercase are per-char and safe regardless.
 * The Nth boundary maps to `span = N`; gaps and the tail map to `null`.
 */
export function transformSegments(
  normalized: string,
  boundaries: Array<[number, number]>,
  transform: TextTransform | undefined
): SpanSegment[] {
  const normBytes = utf8Encoder.encode(normalized);
  const pieces: Array<[number, number, number | null]> = [];
  let cursor = 0;
  boundaries.forEach(([start, end], index) => {
    if (start > cursor) {
      pieces.push([cursor, start, null]);
    }
    if (end > start) {
      pieces.push([start, end, index]);
    }
    cursor = Math.max(cursor, end);
  });
  if (cursor < normBytes.length) {
    pieces.push([cursor, normBytes.length, null]);
  }

  const state = { atWordStart: true };
  return pieces.map(([start, end, span]) => {
    const slice = utf8Decoder.decode(normBytes.slice(start, end));
    const text = transformSliceStateful(slice, transform, state);
    return { text, span };
  });
}

/** Case-transform one slice, threading the title-case word-start cursor so the
 * caller can continue it across the next segment (A6b D5). Mirrors Rust
 * `transform_slice_stateful` — the non-title arms still advance the cursor to
 * the last char's whitespace-ness even though only title reads it. */
function transformSliceStateful(
  slice: string,
  transform: TextTransform | undefined,
  state: { atWordStart: boolean }
): string {
  switch (transform) {
    case "uppercase":
      for (const ch of slice) {
        state.atWordStart = isWhitespace(ch);
      }
      return slice.toUpperCase();
    case "lowercase":
      for (const ch of slice) {
        state.atWordStart = isWhitespace(ch);
      }
      return slice.toLowerCase();
    case "title": {
      let out = "";
      for (const ch of slice) {
        if (isWhitespace(ch)) {
          state.atWordStart = true;
          out += ch;
        } else if (state.atWordStart && isAlphabetic(ch)) {
          out += ch.toUpperCase();
          state.atWordStart = false;
        } else {
          out += ch;
          state.atWordStart = false;
        }
      }
      return out;
    }
    case "none":
    case undefined:
    default:
      for (const ch of slice) {
        state.atWordStart = isWhitespace(ch);
      }
      return slice;
  }
}
