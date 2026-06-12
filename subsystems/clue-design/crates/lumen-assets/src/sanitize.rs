//! SVG sanitization.
//!
//! Hostile constructs are stripped before bytes are stored or embedded
//! (hard rule): `script` and `foreignObject` subtrees, every `on*` event
//! handler attribute, and `href`/`xlink:href` values with a script-bearing
//! scheme. The rewrite is event-based (quick-xml) and idempotent; an SVG
//! that cannot be parsed is rejected rather than stored unsanitized.

use quick_xml::events::attributes::Attribute;
use quick_xml::events::{BytesStart, Event};
use quick_xml::{Reader, Writer};
use std::error::Error;
use std::fmt;

#[derive(Clone, Debug)]
pub struct SanitizeOutput {
    pub bytes: Vec<u8>,
    /// Human-readable notes for each removed construct.
    pub removed: Vec<String>,
    /// Root `<svg>` dimensions captured during the rewrite.
    pub width: Option<f64>,
    pub height: Option<f64>,
    pub view_box: Option<[f64; 4]>,
}

#[derive(Clone, Debug)]
pub struct SanitizeError {
    pub code: &'static str,
    pub message: String,
}

impl SanitizeError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            code: "sanitize.invalid_svg",
            message: message.into(),
        }
    }
}

impl fmt::Display for SanitizeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for SanitizeError {}

const BANNED_ELEMENTS: &[&str] = &["script", "foreignobject"];

pub fn sanitize_svg(bytes: &[u8]) -> Result<SanitizeOutput, SanitizeError> {
    let mut reader = Reader::from_reader(bytes);
    let mut writer = Writer::new(Vec::new());
    let mut buffer = Vec::new();
    let mut removed = Vec::new();
    let mut skip_depth: usize = 0;
    let mut root_seen = false;
    let mut width = None;
    let mut height = None;
    let mut view_box = None;

    loop {
        let event = reader
            .read_event_into(&mut buffer)
            .map_err(|error| SanitizeError::new(format!("svg did not parse: {error}")))?;
        match event {
            Event::Eof => break,
            Event::Start(start) => {
                if skip_depth > 0 {
                    skip_depth += 1;
                    continue;
                }
                if is_banned_element(start.name().as_ref()) {
                    removed.push(format!(
                        "{} element",
                        String::from_utf8_lossy(local_name(start.name().as_ref()))
                    ));
                    skip_depth = 1;
                    continue;
                }
                let rebuilt = filter_attributes(&start, &mut removed)?;
                if !root_seen && local_name(start.name().as_ref()).eq_ignore_ascii_case(b"svg") {
                    root_seen = true;
                    capture_svg_dimensions(&start, &mut width, &mut height, &mut view_box);
                }
                writer
                    .write_event(Event::Start(rebuilt))
                    .map_err(write_error)?;
            }
            Event::Empty(start) => {
                if skip_depth > 0 {
                    continue;
                }
                if is_banned_element(start.name().as_ref()) {
                    removed.push(format!(
                        "{} element",
                        String::from_utf8_lossy(local_name(start.name().as_ref()))
                    ));
                    continue;
                }
                let rebuilt = filter_attributes(&start, &mut removed)?;
                if !root_seen && local_name(start.name().as_ref()).eq_ignore_ascii_case(b"svg") {
                    root_seen = true;
                    capture_svg_dimensions(&start, &mut width, &mut height, &mut view_box);
                }
                writer
                    .write_event(Event::Empty(rebuilt))
                    .map_err(write_error)?;
            }
            Event::End(end) => {
                if skip_depth > 0 {
                    skip_depth -= 1;
                    continue;
                }
                writer.write_event(Event::End(end)).map_err(write_error)?;
            }
            other => {
                if skip_depth > 0 {
                    continue;
                }
                writer.write_event(other).map_err(write_error)?;
            }
        }
        buffer.clear();
    }

    if !root_seen {
        return Err(SanitizeError::new("no <svg> root element found"));
    }

    Ok(SanitizeOutput {
        bytes: writer.into_inner(),
        removed,
        width,
        height,
        view_box,
    })
}

fn write_error(error: std::io::Error) -> SanitizeError {
    SanitizeError::new(format!("sanitized svg could not be rewritten: {error}"))
}

fn is_banned_element(name: &[u8]) -> bool {
    let local = local_name(name);
    BANNED_ELEMENTS
        .iter()
        .any(|banned| local.eq_ignore_ascii_case(banned.as_bytes()))
}

fn local_name(name: &[u8]) -> &[u8] {
    match name.iter().rposition(|byte| *byte == b':') {
        Some(position) => &name[position + 1..],
        None => name,
    }
}

fn filter_attributes(
    start: &BytesStart<'_>,
    removed: &mut Vec<String>,
) -> Result<BytesStart<'static>, SanitizeError> {
    let name = String::from_utf8_lossy(start.name().as_ref()).into_owned();
    let mut rebuilt = BytesStart::new(name);
    for attribute in start.attributes().with_checks(false) {
        let attribute = attribute
            .map_err(|error| SanitizeError::new(format!("svg attribute did not parse: {error}")))?;
        let key = attribute.key.as_ref().to_vec();
        let local = local_name(&key).to_ascii_lowercase();
        let key_text = String::from_utf8_lossy(&key).into_owned();
        // Compare against the unescaped value so entity-encoded schemes
        // (`java&#115;cript:`) cannot evade the filter; re-escaping happens
        // on write through push_attribute.
        let value = attribute
            .unescape_value()
            .map_err(|error| SanitizeError::new(format!("svg attribute did not parse: {error}")))?;

        if local.starts_with(b"on") && local.len() > 2 {
            removed.push(format!("{key_text} attribute"));
            continue;
        }

        if local == b"href" && has_script_scheme(value.as_bytes()) {
            removed.push(format!("script-scheme {key_text} attribute"));
            continue;
        }

        rebuilt.push_attribute(Attribute::from((key_text.as_str(), value.as_ref())));
    }
    Ok(rebuilt.into_owned())
}

/// Detect `javascript:`/`vbscript:`/`data:text/html` schemes with
/// whitespace and control characters stripped, the way HTML parsers
/// tolerate them.
fn has_script_scheme(value: &[u8]) -> bool {
    let compact: Vec<u8> = value
        .iter()
        .copied()
        .filter(|byte| *byte > 0x20)
        .map(|byte| byte.to_ascii_lowercase())
        .collect();
    compact.starts_with(b"javascript:")
        || compact.starts_with(b"vbscript:")
        || compact.starts_with(b"data:text/html")
}

fn capture_svg_dimensions(
    start: &BytesStart,
    width: &mut Option<f64>,
    height: &mut Option<f64>,
    view_box: &mut Option<[f64; 4]>,
) {
    for attribute in start.attributes().with_checks(false).flatten() {
        let local = local_name(attribute.key.as_ref()).to_ascii_lowercase();
        let value = String::from_utf8_lossy(&attribute.value);
        match local.as_slice() {
            b"width" => *width = parse_length(&value),
            b"height" => *height = parse_length(&value),
            b"viewbox" => {
                let parts: Vec<f64> = value
                    .split([' ', ','])
                    .filter(|part| !part.is_empty())
                    .filter_map(|part| part.parse::<f64>().ok())
                    .collect();
                if parts.len() == 4 {
                    *view_box = Some([parts[0], parts[1], parts[2], parts[3]]);
                }
            }
            _ => {}
        }
    }
}

/// Parse the numeric prefix of an SVG length (`120`, `120px`, `120.5mm`).
fn parse_length(value: &str) -> Option<f64> {
    let trimmed = value.trim();
    let numeric_end = trimmed
        .find(|character: char| {
            !character.is_ascii_digit() && character != '.' && character != '-' && character != '+'
        })
        .unwrap_or(trimmed.len());
    trimmed[..numeric_end].parse::<f64>().ok()
}
