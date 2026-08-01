//! Font-face embedding contract for SVG export.
//!
//! The SVG exporter emits `font-family` by CSS name; without embedded bytes,
//! any viewer missing those fonts silently substitutes its own default and
//! the file no longer looks like the design (and, because line breaks and
//! span run positions are baked as absolute coordinates, substitution also
//! corrupts spacing rather than reflowing). This trait is the injection seam
//! that closes the gap: a resolver supplies, for every (family, weight,
//! italic) the text actually used, the exact face bytes the raster path
//! shaped and painted with — subset to the used characters — and the SVG
//! exporter embeds them as `@font-face` data URIs.
//!
//! Failure policy is fail-loud by contract: a face that should embed but
//! cannot (restricted embedding license, subsetting failure, missing bytes
//! for a loaded family) is an [`FontEmbedError`] and the export dies, never
//! a silent name-only file. The only name-only outputs are the two declared
//! states — `embed_fonts=false` on the profile, or a portable consumer with
//! no resolver injected — and both carry the loud LUME0216 diagnostic
//! listing exactly which fonts the viewer must have installed.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

/// One (family, weight, italic) the exported text used, with the characters
/// it rendered. Collected per text node and span run by the SVG exporter;
/// the resolver receives the complete list for a page in one call so it can
/// union character sets that land on the same physical face (two nodes both
/// per-glyph-falling-back to the same fallback face must produce ONE subset,
/// not two competing rules).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FontUsage {
    pub family: String,
    pub weight: i32,
    pub italic: bool,
    pub chars: BTreeSet<char>,
}

/// One face to embed: the CSS identity the `@font-face` rule declares plus
/// the sfnt bytes behind it.
///
/// `css_family` is the family name the rule declares — the REQUESTED scene
/// family for a primary face (even when the byte source is the deterministic
/// fallback family, so the SVG renders exactly what the raster painted), and
/// the fallback family's own name for faces that supplied per-glyph fallback.
#[derive(Clone, PartialEq, Eq)]
pub struct EmbeddedFontFace {
    pub css_family: String,
    /// The face's actual weight — the `font-weight` descriptor. Browsers'
    /// CSS matching over the declared descriptors mirrors the snap the
    /// server's `find_typefaces` performed at shape time.
    pub weight: i32,
    pub italic: bool,
    /// Complete sfnt bytes (TTF/OTF), subset to the requested characters
    /// unless the face's fsType forbids subsetting (then the full face).
    pub bytes: Vec<u8>,
    /// MIME type for the data URI: `font/ttf` or `font/otf`.
    pub mime_type: String,
    /// Pre-formatted CSS `unicode-range` value (e.g. `U+2192, U+00D7`) for
    /// per-glyph fallback faces: it scopes the rule to exactly the
    /// characters this face supplied at paint time, so browser composite
    /// font matching reproduces the paint path's per-glyph supplier choice.
    /// `None` for primary faces (they cover their whole usage).
    pub unicode_range: Option<String>,
}

impl fmt::Debug for EmbeddedFontFace {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EmbeddedFontFace")
            .field("css_family", &self.css_family)
            .field("weight", &self.weight)
            .field("italic", &self.italic)
            .field("mime_type", &self.mime_type)
            .field("unicode_range", &self.unicode_range)
            .field("byte_len", &self.bytes.len())
            .finish()
    }
}

/// A face that should embed but cannot. Always fatal to the export.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FontEmbedError {
    /// Stable machine code, used verbatim as the `ExportError` code
    /// (e.g. `export.font_embed_restricted_license`,
    /// `export.font_embed_subset_failed`, `export.font_embed_face_missing`).
    pub code: &'static str,
    pub message: String,
}

impl FontEmbedError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for FontEmbedError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for FontEmbedError {}

/// Resolves the font faces that painted a run of text, as embeddable bytes.
///
/// Implementations mirror the paint path's resolution exactly: requested
/// family → loaded family or the deterministic fallback; requested
/// weight/slant → the same CSS3 face match the shaper performed; characters
/// the primary face lacks → the loaded faces that supplied them per-glyph.
/// The SVG exporter embeds every returned face, so "what the raster painted"
/// and "what the SVG viewer renders" are the same bytes by construction.
pub trait FontFaceResolver: fmt::Debug + Send + Sync {
    /// The deterministic per-glyph fallback family of the paint path
    /// (e.g. "Inter"). Appended to every emitted `font-family` chain so
    /// viewers route missing glyphs to the same embedded faces the raster
    /// used.
    fn fallback_family(&self) -> String;

    /// Resolve every face a page's text used, as embeddable subsets: for
    /// each usage, the primary face the shaper matched, plus any faces that
    /// supplied per-glyph fallback for its characters. The resolver owns
    /// deduplication — usages landing on the same physical face come back as
    /// ONE `EmbeddedFontFace` whose subset covers the union of their
    /// characters, and the returned list is deterministic for a given input.
    /// Any face that should embed but cannot is an error, fatal to the
    /// export.
    fn resolve_embeds(&self, usages: &[FontUsage]) -> Result<Vec<EmbeddedFontFace>, FontEmbedError>;
}
