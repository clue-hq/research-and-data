//! MIME sniffing from magic bytes.
//!
//! Ingest never trusts a declared content type: the stored MIME is the
//! sniffed one, and a declared type that contradicts the sniff is rejected
//! (LUMA0600 at the ingest layer).

use lumen_core::AssetKind;

pub const MIME_PNG: &str = "image/png";
pub const MIME_JPEG: &str = "image/jpeg";
pub const MIME_GIF: &str = "image/gif";
pub const MIME_WEBP: &str = "image/webp";
pub const MIME_SVG: &str = "image/svg+xml";
pub const MIME_PDF: &str = "application/pdf";
pub const MIME_TTF: &str = "font/ttf";
pub const MIME_OTF: &str = "font/otf";
pub const MIME_WOFF: &str = "font/woff";
pub const MIME_WOFF2: &str = "font/woff2";

/// Sniff a MIME type from leading magic bytes. Returns `None` for content
/// that matches no supported signature.
pub fn sniff_mime(bytes: &[u8]) -> Option<&'static str> {
    if bytes.starts_with(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]) {
        return Some(MIME_PNG);
    }
    if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        return Some(MIME_JPEG);
    }
    if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        return Some(MIME_GIF);
    }
    if bytes.len() >= 12 && bytes.starts_with(b"RIFF") && &bytes[8..12] == b"WEBP" {
        return Some(MIME_WEBP);
    }
    if bytes.starts_with(b"%PDF-") {
        return Some(MIME_PDF);
    }
    // Fonts previously sniffed as nothing and ingested as `Other` with a
    // spurious LUMA0602 on every kit webfont; the library track made honest
    // font records load-bearing.
    if bytes.starts_with(&[0x00, 0x01, 0x00, 0x00]) || bytes.starts_with(b"true") {
        return Some(MIME_TTF);
    }
    if bytes.starts_with(b"OTTO") {
        return Some(MIME_OTF);
    }
    if bytes.starts_with(b"wOFF") {
        return Some(MIME_WOFF);
    }
    if bytes.starts_with(b"wOF2") {
        return Some(MIME_WOFF2);
    }
    if looks_like_svg(bytes) {
        return Some(MIME_SVG);
    }
    None
}

/// Text-head heuristic for SVG: skip an optional UTF-8 BOM, whitespace, the
/// XML declaration, comments, and a DOCTYPE; the first element must be
/// `<svg`.
fn looks_like_svg(bytes: &[u8]) -> bool {
    let head_len = bytes.len().min(1024);
    let Ok(head) = std::str::from_utf8(&bytes[..head_len]) else {
        return false;
    };
    let mut rest = head.strip_prefix('\u{feff}').unwrap_or(head).trim_start();
    loop {
        if let Some(after) = rest.strip_prefix("<?") {
            match after.find("?>") {
                Some(end) => rest = after[end + 2..].trim_start(),
                None => return false,
            }
        } else if let Some(after) = rest.strip_prefix("<!--") {
            match after.find("-->") {
                Some(end) => rest = after[end + 3..].trim_start(),
                None => return false,
            }
        } else if let Some(after) = rest.strip_prefix("<!") {
            match after.find('>') {
                Some(end) => rest = after[end + 1..].trim_start(),
                None => return false,
            }
        } else {
            break;
        }
    }
    rest.len() >= 4
        && rest[..4].eq_ignore_ascii_case("<svg")
        && rest[4..]
            .chars()
            .next()
            .is_none_or(|next| next.is_whitespace() || next == '>' || next == '/')
}

/// Whether a declared MIME type is compatible with the sniffed one.
/// Comparison normalizes case and parameters; common XML aliases are
/// accepted for SVG because browsers and tools disagree about them.
pub fn mime_compatible(declared: &str, sniffed: &str) -> bool {
    let declared = normalize_mime(declared);
    if declared.is_empty() || declared == "application/octet-stream" {
        return true;
    }
    if declared == sniffed {
        return true;
    }
    match sniffed {
        MIME_SVG => matches!(
            declared.as_str(),
            "image/svg" | "text/xml" | "application/xml"
        ),
        MIME_JPEG => declared == "image/jpg",
        MIME_TTF => matches!(
            declared.as_str(),
            "application/x-font-ttf" | "application/font-sfnt" | "font/sfnt"
        ),
        MIME_OTF => matches!(
            declared.as_str(),
            "application/x-font-otf" | "application/font-sfnt" | "font/sfnt"
        ),
        MIME_WOFF => declared == "application/font-woff",
        MIME_WOFF2 => declared == "application/font-woff2",
        _ => false,
    }
}

fn normalize_mime(value: &str) -> String {
    value
        .split(';')
        .next()
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase()
}

/// Default asset kind for a sniffed MIME type. Uploads may narrow this
/// (e.g. a PNG that is a logo), never widen it.
pub fn default_kind_for_mime(mime: &str) -> AssetKind {
    match mime {
        MIME_PNG | MIME_JPEG | MIME_GIF | MIME_WEBP => AssetKind::RasterImage,
        MIME_SVG => AssetKind::Vector,
        MIME_PDF => AssetKind::Document,
        MIME_TTF | MIME_OTF | MIME_WOFF | MIME_WOFF2 => AssetKind::Font,
        _ => AssetKind::Other,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sniffs_supported_signatures() {
        assert_eq!(
            sniff_mime(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A, 0x00]),
            Some(MIME_PNG)
        );
        assert_eq!(sniff_mime(&[0xFF, 0xD8, 0xFF, 0xE0]), Some(MIME_JPEG));
        assert_eq!(sniff_mime(b"GIF89a..."), Some(MIME_GIF));
        assert_eq!(sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 "), Some(MIME_WEBP));
        assert_eq!(sniff_mime(b"%PDF-1.7\n"), Some(MIME_PDF));
        assert_eq!(sniff_mime(b"<svg xmlns=\"x\"></svg>"), Some(MIME_SVG));
        assert_eq!(
            sniff_mime(b"<?xml version=\"1.0\"?>\n<!-- c -->\n<!DOCTYPE svg>\n<svg/>"),
            Some(MIME_SVG)
        );
        assert_eq!(sniff_mime(b"<html><body>nope</body></html>"), None);
        assert_eq!(sniff_mime(b"<svgnot an svg>"), None);
        assert_eq!(sniff_mime(b"plain text"), None);
    }

    #[test]
    fn sniffs_font_signatures() {
        assert_eq!(sniff_mime(&[0x00, 0x01, 0x00, 0x00, 0x00, 0x12]), Some(MIME_TTF));
        assert_eq!(sniff_mime(b"true\x00\x12rest"), Some(MIME_TTF));
        assert_eq!(sniff_mime(b"OTTO\x00\x0Erest"), Some(MIME_OTF));
        assert_eq!(sniff_mime(b"wOFFrest"), Some(MIME_WOFF));
        assert_eq!(sniff_mime(b"wOF2rest"), Some(MIME_WOFF2));
        assert_eq!(default_kind_for_mime(MIME_TTF), AssetKind::Font);
        assert_eq!(default_kind_for_mime(MIME_WOFF2), AssetKind::Font);
        assert!(mime_compatible("font/ttf", MIME_TTF));
        assert!(mime_compatible("application/x-font-ttf", MIME_TTF));
        assert!(!mime_compatible("font/ttf", MIME_OTF));
    }

    #[test]
    fn compatibility_normalizes_and_allows_aliases() {
        assert!(mime_compatible("image/png", MIME_PNG));
        assert!(mime_compatible("IMAGE/PNG; charset=binary", MIME_PNG));
        assert!(mime_compatible("", MIME_PNG));
        assert!(mime_compatible("application/octet-stream", MIME_PNG));
        assert!(mime_compatible("image/jpg", MIME_JPEG));
        assert!(mime_compatible("image/svg", MIME_SVG));
        assert!(!mime_compatible("image/jpeg", MIME_PNG));
        assert!(!mime_compatible("image/png", MIME_SVG));
    }
}
