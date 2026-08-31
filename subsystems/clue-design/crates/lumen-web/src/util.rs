//! Shared text utilities for the constrained-HTML pipeline.
//!
//! The ingestion contract asks the agent for well-formed markup, but two
//! HTML habits are so ingrained in model output that rejecting them would
//! only burn retry loops: unclosed void elements (`<img …>`, `<br>`) and
//! named HTML entities beyond XML's five (`&nbsp;`, `&mdash;`). Both are
//! normalized deterministically before the strict parse instead.

/// Named HTML entities normalized to UTF-8 before parsing. XML's own five
/// (`amp lt gt quot apos`) are left for the parser.
const NAMED_ENTITIES: &[(&str, &str)] = &[
    ("nbsp", "\u{a0}"),
    ("mdash", "\u{2014}"),
    ("ndash", "\u{2013}"),
    ("lsquo", "\u{2018}"),
    ("rsquo", "\u{2019}"),
    ("ldquo", "\u{201c}"),
    ("rdquo", "\u{201d}"),
    ("hellip", "\u{2026}"),
    ("middot", "\u{b7}"),
    ("bull", "\u{2022}"),
    ("copy", "\u{a9}"),
    ("reg", "\u{ae}"),
    ("trade", "\u{2122}"),
    ("times", "\u{d7}"),
    ("rarr", "\u{2192}"),
    ("larr", "\u{2190}"),
    ("darr", "\u{2193}"),
    ("uarr", "\u{2191}"),
];

const XML_ENTITIES: &[&str] = &["amp", "lt", "gt", "quot", "apos"];

/// Elements that HTML allows to be written unclosed.
const VOID_ELEMENTS: &[&str] = &["img", "br", "hr"];

/// Replace known named HTML entities with their UTF-8 characters and escape
/// any `&` that does not begin a valid XML entity, so the strict XML parser
/// never chokes on tag-soup ampersands.
pub fn normalize_entities(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(input.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] != b'&' {
            let ch_len = utf8_len(bytes[i]);
            out.push_str(&input[i..i + ch_len]);
            i += ch_len;
            continue;
        }
        // Candidate entity: up to 12 chars then ';'.
        let rest = &input[i + 1..];
        let semi = rest.char_indices().take(12).find(|(_, c)| *c == ';');
        if let Some((len, _)) = semi {
            let name = &rest[..len];
            if XML_ENTITIES.contains(&name) {
                out.push('&');
                out.push_str(name);
                out.push(';');
                i += 1 + len + 1;
                continue;
            }
            if let Some((_, replacement)) =
                NAMED_ENTITIES.iter().find(|(entity, _)| *entity == name)
            {
                out.push_str(replacement);
                i += 1 + len + 1;
                continue;
            }
            if is_numeric_entity(name) {
                out.push('&');
                out.push_str(name);
                out.push(';');
                i += 1 + len + 1;
                continue;
            }
        }
        out.push_str("&amp;");
        i += 1;
    }
    out
}

fn utf8_len(first_byte: u8) -> usize {
    match first_byte {
        b if b < 0x80 => 1,
        b if b & 0xE0 == 0xC0 => 2,
        b if b & 0xF0 == 0xE0 => 3,
        _ => 4,
    }
}

fn is_numeric_entity(name: &str) -> bool {
    if let Some(hex) = name.strip_prefix("#x").or_else(|| name.strip_prefix("#X")) {
        !hex.is_empty() && hex.bytes().all(|b| b.is_ascii_hexdigit())
    } else if let Some(dec) = name.strip_prefix('#') {
        !dec.is_empty() && dec.bytes().all(|b| b.is_ascii_digit())
    } else {
        false
    }
}

/// Self-close unclosed void elements (`<img …>` → `<img … />`) so the strict
/// parser accepts HTML5-style markup. Quote-aware; already-closed tags are
/// left untouched.
pub fn self_close_voids(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(input.len() + 16);
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] != b'<' {
            let ch_len = utf8_len(bytes[i]);
            out.push_str(&input[i..i + ch_len]);
            i += ch_len;
            continue;
        }
        // Read the tag name.
        let name_start = i + 1;
        let mut j = name_start;
        while j < bytes.len() && (bytes[j].is_ascii_alphanumeric() || bytes[j] == b'-') {
            j += 1;
        }
        let name = input[name_start..j].to_ascii_lowercase();
        if !VOID_ELEMENTS.contains(&name.as_str()) {
            out.push('<');
            i += 1;
            continue;
        }
        // Find the closing '>' respecting quoted attribute values.
        let mut k = j;
        let mut quote: Option<u8> = None;
        while k < bytes.len() {
            match (quote, bytes[k]) {
                (Some(q), b) if b == q => quote = None,
                (Some(_), _) => {}
                (None, b'"') => quote = Some(b'"'),
                (None, b'\'') => quote = Some(b'\''),
                (None, b'>') => break,
                (None, _) => {}
            }
            k += 1;
        }
        if k >= bytes.len() {
            // Unterminated tag; leave it to the parser to report.
            out.push('<');
            i += 1;
            continue;
        }
        let inner = &input[i..k];
        out.push_str(inner);
        if !inner.trim_end().ends_with('/') {
            out.push_str(" /");
        }
        out.push('>');
        i = k + 1;
    }
    out
}

/// Escape `<` characters that do not begin a tag (`a < b`), so prose with
/// comparison signs parses as text instead of half-opening a bogus element.
pub fn escape_stray_lt(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(input.len());
    for (index, ch) in input.char_indices() {
        if ch == '<' {
            let next = bytes.get(index + 1).copied();
            let starts_tag = matches!(next, Some(b) if b.is_ascii_alphabetic() || b == b'/' || b == b'!');
            if !starts_tag {
                out.push_str("&lt;");
                continue;
            }
        }
        out.push(ch);
    }
    out
}

pub fn escape_text(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for ch in input.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            _ => out.push(ch),
        }
    }
    out
}

pub fn escape_attr(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for ch in input.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            _ => out.push(ch),
        }
    }
    out
}

/// 1-based line/column for a byte offset into `source` (diagnostics only).
pub fn line_col(source: &str, byte_offset: usize) -> (usize, usize) {
    let clamped = byte_offset.min(source.len());
    let prefix = &source[..clamped];
    let line = prefix.bytes().filter(|b| *b == b'\n').count() + 1;
    let col = prefix
        .rfind('\n')
        .map(|pos| prefix[pos + 1..].chars().count() + 1)
        .unwrap_or_else(|| prefix.chars().count() + 1);
    (line, col)
}

/// Allowed href schemes for links authored into web documents.
pub fn href_is_allowed(href: &str) -> bool {
    let trimmed = href.trim();
    if trimmed.is_empty() {
        return false;
    }
    let lower = trimmed.to_ascii_lowercase();
    lower.starts_with("https://")
        || lower.starts_with("http://")
        || lower.starts_with("mailto:")
        || lower.starts_with("tel:")
        || trimmed.starts_with('#')
        || trimmed.starts_with('/')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_named_entities_and_stray_ampersands() {
        assert_eq!(normalize_entities("A&nbsp;B"), "A\u{a0}B");
        assert_eq!(normalize_entities("R&amp;D"), "R&amp;D");
        assert_eq!(normalize_entities("A & B"), "A &amp; B");
        assert_eq!(normalize_entities("x&#160;y"), "x&#160;y");
        assert_eq!(normalize_entities("bad&unknown;end"), "bad&amp;unknown;end");
    }

    #[test]
    fn self_closes_void_elements() {
        assert_eq!(
            self_close_voids(r#"<img src="a" alt="x >y">"#),
            r#"<img src="a" alt="x >y" />"#
        );
        assert_eq!(self_close_voids("<br>"), "<br />");
        assert_eq!(self_close_voids("<br/>"), "<br/>");
        assert_eq!(
            self_close_voids("<div><img data-asset=\"a1\"></div>"),
            "<div><img data-asset=\"a1\" /></div>"
        );
    }

    #[test]
    fn line_col_is_one_based() {
        let src = "ab\ncd\nef";
        assert_eq!(line_col(src, 0), (1, 1));
        assert_eq!(line_col(src, 4), (2, 2));
        assert_eq!(line_col(src, 6), (3, 1));
    }

    #[test]
    fn href_scheme_allowlist() {
        assert!(href_is_allowed("https://example.com/a"));
        assert!(href_is_allowed("#pricing"));
        assert!(href_is_allowed("/about"));
        assert!(href_is_allowed("mailto:hi@x.ai"));
        assert!(!href_is_allowed("javascript:alert(1)"));
        assert!(!href_is_allowed(""));
    }
}

/// How much of a REJECTED id one diagnostic message may quote (clone-fidelity F3.4).
///
/// A valid fragment id is 21 characters and a valid artifact id is not much longer; anything
/// past this is not an id somebody mistyped, it is a payload.
pub const MAX_QUOTED_ID_CHARS: usize = 64;

/// One UNTRUSTED id, made safe to sit inside a diagnostic sentence.
///
/// The diagnostics that report a *rejected* id interpolate the value that failed the grammar —
/// which is the only useful thing to say, and is by definition a string nothing has validated.
/// A raw interpolation therefore lets that value put newlines, backticks and control characters
/// into a message a human reads in a log and a model reads as context: the backtick closes the
/// quoting the sentence set up around it, and a newline forges what looks like the next line of
/// the report. Nothing here is a security boundary — the id has already been refused — but a
/// diagnostic whose structure the offending input can rewrite is a diagnostic that cannot be
/// trusted to describe itself.
///
/// So: control characters become visible escapes, backticks are neutralised, and the whole thing
/// is bounded with the cut made visible. The result is always safe to place between backticks.
pub fn quoted_id(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len().min(MAX_QUOTED_ID_CHARS) + 8);
    let mut taken = 0usize;
    for ch in raw.chars() {
        if taken >= MAX_QUOTED_ID_CHARS {
            out.push_str("…");
            break;
        }
        taken += 1;
        match ch {
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            // The quoting character itself: left in the message it would end the quoted span
            // early and let the rest of the value read as prose.
            '`' => out.push_str("\\`"),
            c if c.is_control() => out.push_str(&format!("\\u{{{:04x}}}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

#[cfg(test)]
mod quoted_id_tests {
    use super::{quoted_id, MAX_QUOTED_ID_CHARS};

    #[test]
    fn an_ordinary_id_is_untouched() {
        assert_eq!(quoted_id("frag_0123456789abcdef"), "frag_0123456789abcdef");
    }

    #[test]
    fn a_backtick_cannot_close_the_span_it_sits_in() {
        assert_eq!(quoted_id("frag_`x`"), "frag_\\`x\\`");
    }

    #[test]
    fn newlines_and_control_characters_become_visible_escapes() {
        assert_eq!(quoted_id("a\nb\tc\u{7}"), "a\\nb\\tc\\u{0007}");
    }

    #[test]
    fn a_payload_wearing_an_ids_clothes_is_bounded_and_says_it_was_cut() {
        let quoted = quoted_id(&"x".repeat(MAX_QUOTED_ID_CHARS * 4));
        assert!(quoted.starts_with(&"x".repeat(MAX_QUOTED_ID_CHARS)));
        assert!(quoted.ends_with('…'));
        assert_eq!(quoted.chars().count(), MAX_QUOTED_ID_CHARS + 1);
    }
}
