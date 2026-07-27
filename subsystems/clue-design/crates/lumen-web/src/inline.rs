//! Restricted inline markup sanitizer.
//!
//! Text content and button labels carry rich accent spans without a rich-text
//! dependency: only `strong em u s a br span` survive, with `a[href target]`
//! (allow-listed schemes) and `span[class]` as the only attributes. The
//! sanitizer never fails — disallowed constructs are unwrapped or dropped and
//! reported as notes; unparseable input is stored as escaped plain text.

use crate::util::{
    escape_attr, escape_stray_lt, escape_text, href_is_allowed, normalize_entities,
    self_close_voids,
};
use quick_xml::events::Event;
use quick_xml::Reader;

const ALLOWED_INLINE_TAGS: &[&str] = &["strong", "em", "u", "s", "a", "br", "span"];
const MAX_INLINE_DEPTH: usize = 6;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InlineOutput {
    pub html: String,
    /// Human-readable notes for each removed/unwrapped construct.
    pub removed: Vec<String>,
}

pub fn sanitize_inline(input: &str) -> InlineOutput {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return InlineOutput::default();
    }
    let normalized = self_close_voids(&escape_stray_lt(&normalize_entities(trimmed)));
    let wrapped = format!("<lumen-inline>{normalized}</lumen-inline>");
    let mut reader = Reader::from_str(&wrapped);
    reader.config_mut().trim_text(false);

    let mut out = String::new();
    let mut removed = Vec::new();
    // Full element stack; `emitted` records whether we opened it in `out`
    // (false = unwrapped: children kept, tag dropped).
    let mut stack: Vec<(String, bool)> = Vec::new();
    loop {
        match reader.read_event() {
            Ok(Event::Start(start)) => {
                let name = String::from_utf8_lossy(start.name().as_ref()).to_lowercase();
                if name == "lumen-inline" {
                    continue;
                }
                let in_dropped_subtree = stack
                    .iter()
                    .any(|(open, _)| open == "script" || open == "style");
                let depth = stack.iter().filter(|(_, emitted)| *emitted).count();
                let allowed = !in_dropped_subtree
                    && !matches!(name.as_str(), "script" | "style")
                    && ALLOWED_INLINE_TAGS.contains(&name.as_str())
                    && name != "br"
                    && depth < MAX_INLINE_DEPTH;
                if matches!(name.as_str(), "script" | "style") {
                    removed.push(format!("dropped <{name}> and its content"));
                }
                if allowed {
                    out.push('<');
                    out.push_str(&name);
                    emit_filtered_attrs(&name, &start, &mut out, &mut removed);
                    out.push('>');
                } else if name != "br"
                    && !matches!(name.as_str(), "script" | "style")
                    && !in_dropped_subtree
                {
                    removed.push(format!("unwrapped disallowed inline tag <{name}>"));
                }
                stack.push((name, allowed));
            }
            Ok(Event::Empty(start)) => {
                let name = String::from_utf8_lossy(start.name().as_ref()).to_lowercase();
                if name == "br" {
                    out.push_str("<br />");
                } else if ALLOWED_INLINE_TAGS.contains(&name.as_str()) {
                    out.push('<');
                    out.push_str(&name);
                    emit_filtered_attrs(&name, &start, &mut out, &mut removed);
                    out.push_str(" />");
                } else {
                    removed.push(format!("dropped disallowed inline tag <{name}>"));
                }
            }
            Ok(Event::End(end)) => {
                let name = String::from_utf8_lossy(end.name().as_ref()).to_lowercase();
                if name == "lumen-inline" {
                    continue;
                }
                if let Some((_, emitted)) = stack.pop() {
                    if emitted {
                        out.push_str(&format!("</{name}>"));
                    }
                }
            }
            Ok(Event::Text(text)) => {
                if stack.iter().any(|(open, _)| open == "script" || open == "style") {
                    continue;
                }
                match text.unescape() {
                    Ok(value) => out.push_str(&escape_text(&value)),
                    Err(_) => out.push_str(&escape_text(&String::from_utf8_lossy(text.as_ref()))),
                }
            }
            Ok(Event::CData(data)) => {
                if stack.iter().any(|(open, _)| open == "script" || open == "style") {
                    continue;
                }
                out.push_str(&escape_text(&String::from_utf8_lossy(data.as_ref())));
            }
            Ok(Event::Comment(_)) | Ok(Event::Decl(_)) | Ok(Event::PI(_)) | Ok(Event::DocType(_)) => {}
            Ok(Event::Eof) => break,
            Err(err) => {
                return InlineOutput {
                    html: escape_text(trimmed),
                    removed: vec![format!(
                        "unparseable inline markup ({err}); stored as plain text"
                    )],
                };
            }
        }
    }
    InlineOutput { html: out, removed }
}

fn emit_filtered_attrs(
    tag: &str,
    start: &quick_xml::events::BytesStart<'_>,
    out: &mut String,
    removed: &mut Vec<String>,
) {
    for attr in start.attributes().with_checks(false).flatten() {
        let key = String::from_utf8_lossy(attr.key.as_ref()).to_lowercase();
        let value = match attr.unescape_value() {
            Ok(value) => value.into_owned(),
            Err(_) => String::from_utf8_lossy(&attr.value).into_owned(),
        };
        let keep = match (tag, key.as_str()) {
            ("a", "href") => {
                if href_is_allowed(&value) {
                    true
                } else {
                    removed.push(format!("dropped link href with disallowed scheme: {value}"));
                    false
                }
            }
            ("a", "target") => value == "_blank",
            ("span", "class") => true,
            _ => {
                if key.starts_with("on") {
                    removed.push(format!("dropped event handler attribute {key}"));
                } else {
                    removed.push(format!("dropped attribute {key} on <{tag}>"));
                }
                false
            }
        };
        if keep {
            out.push(' ');
            out.push_str(&key);
            out.push_str("=\"");
            out.push_str(&escape_attr(&value));
            out.push('"');
        }
    }
}

/// Plain-text projection of sanitized inline HTML (selection badges, labels).
pub fn inline_plain_text(html: &str) -> String {
    let mut out = String::new();
    let mut in_tag = false;
    for ch in html.chars() {
        match ch {
            '<' => in_tag = true,
            '>' => in_tag = false,
            c if !in_tag => out.push(c),
            _ => {}
        }
    }
    out.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_allowed_inline_markup() {
        let result = sanitize_inline("Grow your <span class=\"text-primary\">practice</span> today");
        assert_eq!(
            result.html,
            "Grow your <span class=\"text-primary\">practice</span> today"
        );
        assert!(result.removed.is_empty());
    }

    #[test]
    fn unwraps_disallowed_tags_and_drops_handlers() {
        let result = sanitize_inline("<div onclick=\"x()\">Hi <strong>there</strong></div>");
        assert_eq!(result.html, "Hi <strong>there</strong>");
        assert!(!result.removed.is_empty());
    }

    #[test]
    fn drops_script_scheme_links() {
        let result = sanitize_inline("<a href=\"javascript:alert(1)\">x</a>");
        assert_eq!(result.html, "<a>x</a>");
        assert!(result
            .removed
            .iter()
            .any(|note| note.contains("disallowed scheme")));
    }

    #[test]
    fn keeps_good_links_and_br() {
        let result = sanitize_inline("See <a href=\"/pricing\" target=\"_blank\">pricing</a><br>now");
        assert_eq!(
            result.html,
            "See <a href=\"/pricing\" target=\"_blank\">pricing</a><br />now"
        );
    }

    #[test]
    fn survives_unparseable_input_as_plain_text() {
        let result = sanitize_inline("a < b & c");
        assert_eq!(result.html, "a &lt; b &amp; c");
    }

    #[test]
    fn plain_text_projection() {
        assert_eq!(
            inline_plain_text("Grow <span class=\"x\">fast</span> &amp; safe"),
            "Grow fast & safe"
        );
    }
}
