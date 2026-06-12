//! `SkiaTextMeasurer`: SkParagraph-backed implementation of
//! `lumen_core::TextMeasurer` (slice A2).
//!
//! The paragraph construction here is the single source of truth for text
//! line breaks: the A3 scene renderer paints text through the same
//! [`build_paragraph`] with the same normalization and family resolution, so
//! measured geometry and painted pixels can never disagree on breaks.
//!
//! Mapping contract (pinned by tests in `tests/measure.rs`):
//! - `line_height` is our multiplier model: SkParagraph's height override
//!   (`TextStyle::set_height(multiplier)` + `set_height_override(true)`)
//!   makes every line exactly `font_size * line_height` tall, so paragraph
//!   height == `line_count * font_size * line_height`.
//! - Hard breaks mirror the heuristic: literal `\n` sequences (two
//!   characters, as DSL strings carry them) and real newlines both break;
//!   a trailing newline does not produce a trailing empty line.
//! - `max_lines` truncates without ellipsis; `exceeds_max_lines` comes from
//!   `Paragraph::did_exceed_max_lines`.
//! - Long words: Skia breaks words that exceed the wrap width (the
//!   heuristic overflowed instead); Skia's behavior is the pinned one.
//! - `TextDirection::Auto` measures as LTR.

use crate::fonts::FontManager;
use lumen_core::{
    line_height_px, TextDirection as LumenTextDirection, TextLineBox, TextMeasureInput,
    TextMeasureOutput, TextMeasurer, TextWrap,
};
use skia_safe::textlayout::{
    Paragraph, ParagraphBuilder, ParagraphStyle, TextAlign as SkTextAlign,
    TextDirection as SkTextDirection, TextStyle,
};
use skia_safe::{Color as SkColor, FontStyle, Paint as SkPaint};

/// Default measurement foreground: opaque black, anti-aliased.
pub(crate) fn default_foreground() -> SkPaint {
    let mut paint = SkPaint::default();
    paint.set_color(SkColor::BLACK);
    paint.set_anti_alias(true);
    paint
}
use std::sync::Arc;

/// Layout width used when no wrap constraint applies. Large enough that no
/// realistic single line wraps; small enough to stay exact in f32.
pub(crate) const UNBOUNDED_LAYOUT_WIDTH: f64 = 1.0e7;

/// Comparison tolerance for overflow verdicts: absorbs f32 scalar noise from
/// Skia without masking real overflow.
const OVERFLOW_EPSILON: f64 = 0.01;

/// Everything needed to build one SkParagraph. Both the measurer and the A3
/// renderer construct paragraphs exclusively through this struct.
pub(crate) struct ParagraphRequest<'a> {
    /// Content already passed through [`normalize_content`].
    pub content: &'a str,
    /// Family already resolved through `FontManager::resolve_family`.
    pub font_family: &'a str,
    pub font_size: f64,
    pub font_weight: u16,
    pub line_height: f64,
    pub letter_spacing: f64,
    pub max_lines: Option<u16>,
    pub direction: LumenTextDirection,
    pub align: SkTextAlign,
    /// Foreground paint for the glyphs (solid color for measurement;
    /// the renderer may pass gradient shaders).
    pub foreground: SkPaint,
}

/// Mirror the heuristic's hard-break handling: literal `\n` sequences and
/// real newlines both become hard breaks; `\r\n` collapses to `\n`; trailing
/// newlines do not create a trailing empty line (`str::lines` semantics).
pub(crate) fn normalize_content(content: &str) -> String {
    let normalized = content.replace("\\n", "\n").replace("\r\n", "\n");
    normalized.trim_end_matches('\n').to_owned()
}

/// The layout width SkParagraph wraps against for a given input.
pub(crate) fn wrap_layout_width(wrap: &TextWrap, max_width: Option<f64>) -> f64 {
    match (wrap, max_width.filter(|width| *width > 0.0)) {
        (TextWrap::Wrap, Some(width)) => width,
        _ => UNBOUNDED_LAYOUT_WIDTH,
    }
}

/// Build a laid-out paragraph. Single construction path for measurement
/// (A2) and painting (A3): same style mapping, same font collection.
pub(crate) fn build_paragraph(request: &ParagraphRequest<'_>, fonts: &FontManager) -> Paragraph {
    fonts.with_collection(|collection| {
        let mut text_style = TextStyle::new();
        text_style.set_font_families(&[request.font_family]);
        text_style.set_font_size(request.font_size as f32);
        text_style.set_font_style(FontStyle::new(
            (request.font_weight as i32).into(),
            skia_safe::font_style::Width::NORMAL,
            skia_safe::font_style::Slant::Upright,
        ));
        text_style.set_letter_spacing(request.letter_spacing as f32);
        if request.line_height > 0.0 {
            // Our line-height multiplier model: line box = multiplier * size.
            text_style.set_height(request.line_height as f32);
            text_style.set_height_override(true);
        }
        text_style.set_foreground_paint(&request.foreground);

        let mut paragraph_style = ParagraphStyle::new();
        paragraph_style.set_text_style(&text_style);
        paragraph_style.set_text_align(request.align);
        paragraph_style.set_text_direction(match request.direction {
            LumenTextDirection::Rtl => SkTextDirection::RTL,
            // Auto is pinned to LTR for measurement determinism.
            LumenTextDirection::Ltr | LumenTextDirection::Auto => SkTextDirection::LTR,
        });
        if let Some(max_lines) = request.max_lines {
            // Truncation without ellipsis (Decision: max_lines + ellipsis
            // off); overflow surfaces as a diagnostic, never as silent "...".
            paragraph_style.set_max_lines(max_lines as usize);
        }

        let mut builder = ParagraphBuilder::new(&paragraph_style, collection.clone());
        builder.add_text(request.content);
        builder.build()
    })
}

/// SkParagraph-backed `TextMeasurer`. Shares its `FontManager` (and thus its
/// loaded bytes + per-thread font collection) with the A3 renderer.
#[derive(Clone, Debug)]
pub struct SkiaTextMeasurer {
    fonts: Arc<FontManager>,
}

impl SkiaTextMeasurer {
    pub fn new(fonts: Arc<FontManager>) -> Self {
        Self { fonts }
    }

    /// Measurer over the bundled deterministic font set.
    pub fn bundled() -> Self {
        Self::new(Arc::new(FontManager::bundled()))
    }

    pub fn fonts(&self) -> &Arc<FontManager> {
        &self.fonts
    }
}

impl TextMeasurer for SkiaTextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput {
        let line_height_px = line_height_px(input.font_size, input.line_height);
        let resolution = self.fonts.resolve_family(&input.font_family);
        let content = normalize_content(&input.content);
        let max_width = input.max_width.filter(|width| *width > 0.0);

        if content.is_empty() {
            // Mirror the heuristic: empty content still occupies one line.
            let line = TextLineBox {
                text: String::new(),
                x: 0.0,
                y: 0.0,
                width: 0.0,
                height: line_height_px,
                baseline: input.font_size,
            };
            return TextMeasureOutput {
                width: 0.0,
                height: line_height_px,
                line_height_px,
                line_count: 1,
                lines: vec![line],
                overflow_x: false,
                overflow_y: input
                    .max_height
                    .is_some_and(|max_height| line_height_px > max_height + OVERFLOW_EPSILON),
                exceeds_max_lines: false,
            };
        }

        let mut paragraph = build_paragraph(
            &ParagraphRequest {
                content: &content,
                font_family: &resolution.family,
                font_size: input.font_size,
                font_weight: input.font_weight,
                line_height: input.line_height,
                letter_spacing: input.letter_spacing,
                max_lines: input.max_lines,
                direction: input.direction.clone(),
                // Measurement always lays out left-aligned: alignment moves
                // lines inside the box but never changes break positions.
                align: SkTextAlign::Left,
                foreground: default_foreground(),
            },
            &self.fonts,
        );
        paragraph.layout(wrap_layout_width(&input.wrap, max_width) as f32);

        let utf16_to_byte = utf16_byte_offsets(&content);
        let mut lines = Vec::new();
        for metrics in paragraph.get_line_metrics() {
            let text = line_text(
                &content,
                &utf16_to_byte,
                metrics.start_index,
                metrics.end_excluding_whitespaces,
            );
            let baseline = metrics.baseline;
            lines.push(TextLineBox {
                text,
                x: metrics.left,
                y: baseline - metrics.ascent,
                width: metrics.width,
                height: metrics.height,
                baseline,
            });
        }

        let measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        let measured_height = f64::from(paragraph.height());
        let width = max_width
            .filter(|_| matches!(input.wrap, TextWrap::Wrap))
            .map(|max_width| measured_width.min(max_width))
            .unwrap_or(measured_width);

        TextMeasureOutput {
            width,
            height: measured_height,
            line_height_px,
            line_count: lines.len() as u16,
            overflow_x: input
                .max_width
                .is_some_and(|max_width| measured_width > max_width + OVERFLOW_EPSILON),
            overflow_y: input
                .max_height
                .is_some_and(|max_height| measured_height > max_height + OVERFLOW_EPSILON),
            exceeds_max_lines: paragraph.did_exceed_max_lines(),
            lines,
        }
    }
}

/// Byte offset for every UTF-16 code-unit offset of `content`, plus a final
/// entry for the end of the string. SkParagraph line-metrics indices are
/// UTF-16 code-unit offsets (verified empirically against multibyte text:
/// byte interpretation produced garbled line slices), so slicing the UTF-8
/// source requires this map.
fn utf16_byte_offsets(content: &str) -> Vec<usize> {
    let mut offsets = Vec::with_capacity(content.len() + 1);
    for (byte_index, ch) in content.char_indices() {
        for _ in 0..ch.len_utf16() {
            offsets.push(byte_index);
        }
    }
    offsets.push(content.len());
    offsets
}

/// Slice one line's text out of the source by SkParagraph line-metrics
/// indices (UTF-16 code-unit offsets). Out-of-range or inverted indices
/// produce an empty string instead of panicking inside measurement.
fn line_text(content: &str, utf16_to_byte: &[usize], start: usize, end: usize) -> String {
    if start >= end {
        return String::new();
    }
    let last = utf16_to_byte.len().saturating_sub(1);
    let start_byte = utf16_to_byte[start.min(last)];
    let end_byte = utf16_to_byte[end.min(last)];
    content
        .get(start_byte..end_byte)
        .map(str::to_owned)
        .unwrap_or_default()
}
