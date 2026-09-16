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
    line_height_px, normalize_content_mapped, transform_segments, Diagnostic, DiagnosticSubject,
    Phase, TextDirection as LumenTextDirection, TextLineBox, TextMeasureInput, TextMeasureOutput,
    TextMeasurer, TextRunBox, TextWrap,
};
use skia_safe::textlayout::{
    Paragraph, ParagraphBuilder, ParagraphStyle, RectHeightStyle, RectWidthStyle,
    TextAlign as SkTextAlign, TextDecoration, TextDirection as SkTextDirection, TextStyle,
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
    /// A6a D2: underline decoration. Decoration inherits the foreground paint
    /// (shader included) via `set_foreground_paint` — set inside
    /// `build_paragraph` so measure and render agree by construction.
    pub underline: bool,
    /// A6a D2: strikethrough decoration.
    pub strikethrough: bool,
    /// A7b D3: italic style. Unlike the decorations this changes the selected
    /// face (`Slant::Italic`) and therefore glyph advances — a measurement
    /// input, not paint-only. Ignored when `segments` are set (each segment
    /// carries its own resolved italic).
    pub italic: bool,
    /// A6a D3: request SkParagraph's native "…" ellipsis (max_lines cut or,
    /// when laid out at the box width, NoWrap single-line overflow).
    pub truncate: bool,
    /// A6b D6/D7: when `Some`, the paragraph is built from these per-run styled
    /// segments (`push_style`/`pop` per segment) instead of the single
    /// `content` + scalar-style path. `None` keeps the pre-A6b construction
    /// byte-identical. The scalar `content`/`font_weight`/`underline`/
    /// `strikethrough`/`foreground` fields are ignored when segments are set.
    pub segments: Option<Vec<ParagraphSegment>>,
}

/// A6b: one styled run for the segmented `build_paragraph` path. Family, size,
/// letter-spacing and line-height stay node-level (per-span variants are
/// deferred); only weight, decoration, and foreground differ per run.
pub(crate) struct ParagraphSegment {
    pub text: String,
    pub font_weight: u16,
    pub underline: bool,
    pub strikethrough: bool,
    /// A7b D3: per-run italic, resolved (`span.italic.unwrap_or(block)`) before
    /// the segment is built — a measured geometry channel, like `font_weight`.
    pub italic: bool,
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

/// The font-resolution diagnostics for one text run, shared by the measurer
/// and the raster renderer so measure and render agree on exactly what the
/// font set could and could not supply:
/// - `LUMS0100` — the whole requested family is not loaded and shaping fell
///   back to the default family (from `FamilyResolution::diagnostic`).
/// Glyph diagnostics are collected separately from the actual laid-out paragraph.
///
/// `subject` is stamped onto every returned diagnostic (the node under paint,
/// or `None` for a document-scoped measurement). Returns empty when the family
/// and requested face style resolve cleanly.
pub(crate) fn font_diagnostics(
    fonts: &FontManager,
    requested_family: &str,
    weight: i32,
    italic: bool,
    subject: Option<DiagnosticSubject>,
) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    let resolution = fonts.resolve_family(requested_family);
    if let Some(diagnostic) = resolution.diagnostic() {
        diagnostics.push(Diagnostic {
            subject: subject.clone(),
            ..diagnostic
        });
    } else {
        // A6a D6.2: the family loaded, but it has no face at the requested
        // weight, so the shaper snapped to the nearest one. Snapping is correct
        // behavior; the silence was the bug. Advisory, only when the family
        // itself resolved cleanly (a whole-family miss is already LUMS0100).
        if let Some(actual) = fonts.resolved_weight(&resolution.family, weight, italic) {
            diagnostics.push(
                Diagnostic::advice(
                    Phase::Layout,
                    "LUMS0104",
                    format!(
                        "font family \"{}\" has no weight {}; shaping used its nearest face (weight {})",
                        resolution.family, weight, actual
                    ),
                    subject.clone(),
                )
                .with_hint(
                    "Add a face at this weight to the fonts/ set for exact weight fidelity, or pick a weight the family ships.",
                ),
            );
        }
        // A7b D2: italic requested but the family has no italic face, so the
        // shaper snapped to the upright (no synthetic slant). Advisory mirror
        // of LUMS0104, gated on the family resolving cleanly so a whole-family
        // miss stays LUMS0100 only.
        if italic && fonts.resolved_slant(&resolution.family, weight, italic) == Some(false) {
            diagnostics.push(
                Diagnostic::advice(
                    Phase::Layout,
                    "LUMS0105",
                    format!(
                        "font family \"{}\" has no italic face; shaping used its upright face",
                        resolution.family
                    ),
                    subject.clone(),
                )
                .with_hint(
                    "Add an italic face for this family to the fonts/ set, or pick a family that ships italics (no synthetic slant is applied).",
                ),
            );
        }
    }

    diagnostics
}

/// Read glyph outcomes from the paragraph actually measured or painted, with
/// its effective span styles and direction. A base-style probe can both reject
/// a valid bold-only glyph and conceal one missing from a regular span.
pub(crate) fn glyph_diagnostics(
    fonts: &FontManager,
    request: &ParagraphRequest<'_>,
    paragraph: &mut Paragraph,
    subject: Option<DiagnosticSubject>,
) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let content = match &request.segments {
        Some(segments) => std::borrow::Cow::Owned(
            segments.iter().map(|segment| segment.text.as_str()).collect::<String>(),
        ),
        None => std::borrow::Cow::Borrowed(request.content),
    };
    // SkParagraph can report an empty unresolved-codepoint set on a repeated
    // shape with tofu. Glyph IDs and UTF-8 starts are the actual paint data.
    let mut unresolved = std::collections::BTreeSet::new();
    paragraph.visit(|_, info| {
        if let Some(info) = info {
            for (&glyph, &start) in info.glyphs().iter().zip(info.utf8_starts()) {
                if glyph == 0 {
                    if let Some(ch) = content.get(start as usize..).and_then(|text| text.chars().next()) {
                        if !ch.is_control() && !ch.is_whitespace() {
                            unresolved.insert(ch);
                        }
                    }
                }
            }
        }
    });
    let mut substituted = Vec::new();
    let mut collect_substitutions = |content: &str, weight: u16, italic: bool| {
        for ch in fonts.substituted_chars(request.font_family, weight as i32, italic, content) {
            if !unresolved.contains(&ch) && !substituted.contains(&ch) {
                substituted.push(ch);
            }
        }
    };
    match &request.segments {
        Some(segments) => {
            for segment in segments {
                collect_substitutions(&segment.text, segment.font_weight, segment.italic);
            }
        }
        None => collect_substitutions(request.content, request.font_weight, request.italic),
    }
    if !unresolved.is_empty() {
        diagnostics.push(
            Diagnostic::error(
                Phase::Layout,
                "LUMS0106",
                format!(
                    "font family \"{}\" and the loaded fallback chain cannot render {}",
                    request.font_family,
                    unresolved
                        .iter()
                        .map(|ch| format!("U+{:04X}", *ch as u32))
                        .collect::<Vec<_>>()
                        .join(", "),
                ),
                subject.clone(),
            )
            .with_hint("Load a font face that supplies these characters or revise the text; unresolved glyphs render as missing-glyph boxes."),
        );
    }
    if !substituted.is_empty() {
        let chars = substituted
            .iter()
            .map(|ch| format!("{ch:?}"))
            .collect::<Vec<_>>()
            .join(", ");
        diagnostics.push(
            Diagnostic::warning(
                Phase::Layout,
                "LUMS0103",
                format!(
                    "font family \"{}\" is missing glyphs for {}; they shape from a fallback loaded face",
                    request.font_family, chars
                ),
                subject,
            )
            .with_hint(
                "The face is a subset that lacks these characters; add a fuller face for this family to the fonts/ set, or the glyphs will render in the fallback family's design.",
            ),
        );
    }

    diagnostics
}

/// Build a laid-out paragraph. Single construction path for measurement
/// (A2) and painting (A3): same style mapping, same font collection.
pub(crate) fn build_paragraph(request: &ParagraphRequest<'_>, fonts: &FontManager) -> Paragraph {
    // A7b D2 gate (adversarial-gate finding, pixel-proven): SkParagraph does
    // NOT snap an unsatisfiable italic request to the upright — it applies a
    // SYNTHETIC oblique (sheared glyphs), which D2 forbids. Request the italic
    // slant only when the family actually has an italic face loaded; otherwise
    // shape upright (today's behavior), with LUMS0105 advising the gap. One
    // gate here covers every path — base, stacked, and A6b/A7b segments (spans
    // cannot change family, so one family-level answer is correct per request).
    let family_has_italic = fonts.has_italic_face(request.font_family);
    let families = fonts.fallback_families(request.font_family);
    fonts.with_collection(|collection| {
        // One style factory for the base style and every A6b segment style, so
        // family/size/letter-spacing/line-height are identical across runs and
        // only weight/decoration/foreground vary.
        let make_style = |font_weight: u16, italic: bool, underline: bool, strikethrough: bool, fg: &SkPaint| {
            let italic = italic && family_has_italic;
            let mut text_style = TextStyle::new();
            text_style.set_font_families(&families);
            text_style.set_font_size(request.font_size as f32);
            // A7b D2/D3: italic selects the italic face via the FontStyle slant
            // (the gate above guarantees a real face exists — no synthetic shear).
            text_style.set_font_style(FontStyle::new(
                (font_weight as i32).into(),
                skia_safe::font_style::Width::NORMAL,
                if italic {
                    skia_safe::font_style::Slant::Italic
                } else {
                    skia_safe::font_style::Slant::Upright
                },
            ));
            text_style.set_letter_spacing(request.letter_spacing as f32);
            if request.line_height > 0.0 {
                // Our line-height multiplier model: line box = multiplier * size.
                text_style.set_height(request.line_height as f32);
                text_style.set_height_override(true);
            }
            // A6a D2: decoration union of the two flags. Color/thickness/position
            // come from font metrics + the foreground paint, so gradient-filled
            // text decorates with the same shader natively.
            if underline || strikethrough {
                let mut decoration = TextDecoration::NO_DECORATION;
                if underline {
                    decoration |= TextDecoration::UNDERLINE;
                }
                if strikethrough {
                    decoration |= TextDecoration::LINE_THROUGH;
                }
                text_style.set_decoration_type(decoration);
            }
            text_style.set_foreground_paint(fg);
            text_style
        };

        let base_style = make_style(
            request.font_weight,
            request.italic,
            request.underline,
            request.strikethrough,
            &request.foreground,
        );

        let mut paragraph_style = ParagraphStyle::new();
        paragraph_style.set_text_style(&base_style);
        paragraph_style.set_text_align(request.align);
        paragraph_style.set_text_direction(match request.direction {
            LumenTextDirection::Rtl => SkTextDirection::RTL,
            // Auto is pinned to LTR for measurement determinism.
            LumenTextDirection::Ltr | LumenTextDirection::Auto => SkTextDirection::LTR,
        });
        if let Some(max_lines) = request.max_lines {
            paragraph_style.set_max_lines(max_lines as usize);
        }
        // A6a D3: opt-in ellipsis. With max_lines it truncates the last kept
        // line; with a bounded layout width and NoWrap it truncates the
        // overflowing single line. Without `truncate`, the pre-A6a
        // truncation-without-ellipsis contract holds byte-for-byte.
        if request.truncate {
            paragraph_style.set_ellipsis("…");
        }

        let mut builder = ParagraphBuilder::new(&paragraph_style, collection.clone());
        match &request.segments {
            // A6b: styled runs — push a per-segment style (weight/decoration/
            // foreground) around each segment's text.
            Some(segments) => {
                for segment in segments {
                    let style = make_style(
                        segment.font_weight,
                        segment.italic,
                        segment.underline,
                        segment.strikethrough,
                        &segment.foreground,
                    );
                    builder.push_style(&style);
                    builder.add_text(&segment.text);
                    builder.pop();
                }
            }
            None => {
                builder.add_text(request.content);
            }
        }
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

    /// A6a D4: measure `\n`-delimited paragraphs independently and stack them,
    /// inserting `paragraph_gap` px of extra vertical space at each break.
    /// `max_lines` counts TOTAL lines across paragraphs (cut mid-paragraph);
    /// with `truncate` the ellipsis lands on the last visible line. Only
    /// reached when the gap is positive AND the content actually breaks, so the
    /// single-paragraph fast path stays byte-identical for every existing scene.
    #[allow(clippy::too_many_arguments)]
    fn measure_stacked(
        &self,
        input: &TextMeasureInput,
        family: &str,
        content: &str,
        max_width: Option<f64>,
        line_height_px: f64,
        paragraph_gap: f64,
        mut diagnostics: Vec<Diagnostic>,
    ) -> TextMeasureOutput {
        let layout_width = wrap_layout_width(&input.wrap, max_width) as f32;
        let mut lines: Vec<TextLineBox> = Vec::new();
        let mut cursor_y = 0.0f64;
        for (index, paragraph_text) in content.split('\n').enumerate() {
            if index > 0 {
                cursor_y += paragraph_gap;
            }
            let request = ParagraphRequest {
                content: paragraph_text,
                font_family: family,
                font_size: input.font_size,
                font_weight: input.font_weight,
                line_height: input.line_height,
                letter_spacing: input.letter_spacing,
                // Per-paragraph shaping is unbounded on lines; total-line
                // truncation and the ellipsis are applied to the merged set.
                max_lines: None,
                direction: input.direction.clone(),
                align: SkTextAlign::Left,
                foreground: default_foreground(),
                underline: false,
                strikethrough: false,
                // A7b D3: stacked-paragraph measurement honors block italic
                // (it changes advances); spans don't reach this path.
                italic: input.italic,
                truncate: false,
                segments: None,
            };
            let mut paragraph = build_paragraph(&request, &self.fonts);
            paragraph.layout(layout_width);
            diagnostics.extend(glyph_diagnostics(&self.fonts, &request, &mut paragraph, None));
            let utf16_to_byte = utf16_byte_offsets(paragraph_text);
            let paragraph_top = cursor_y;
            for metrics in paragraph.get_line_metrics() {
                let text = line_text(
                    paragraph_text,
                    &utf16_to_byte,
                    metrics.start_index,
                    metrics.end_excluding_whitespaces,
                );
                lines.push(TextLineBox {
                    text,
                    x: metrics.left,
                    y: paragraph_top + (metrics.baseline - metrics.ascent),
                    width: metrics.width,
                    height: metrics.height,
                    baseline: paragraph_top + metrics.baseline,
                    runs: Vec::new(),
                });
            }
            cursor_y += f64::from(paragraph.height());
        }

        let total_lines = lines.len();
        let exceeds_max_lines = input
            .max_lines
            .is_some_and(|max_lines| total_lines > max_lines as usize);
        if let Some(max_lines) = input.max_lines {
            lines.truncate(max_lines as usize);
        }
        // A6a D3: elide the emitted line text exactly like the raster does.
        if input.truncate {
            self.apply_ellipsis(&mut lines, input, family, exceeds_max_lines, max_width);
        }

        let measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        // Height is the last visible line's bottom; the per-line y offsets
        // already fold in the paragraph gaps.
        let measured_height = lines
            .last()
            .map(|line| line.y + line.height)
            .unwrap_or(0.0);
        let width = max_width
            .filter(|_| matches!(input.wrap, TextWrap::Wrap))
            .map(|bound| measured_width.min(bound))
            .unwrap_or(measured_width);

        TextMeasureOutput {
            width,
            height: measured_height,
            line_height_px,
            line_count: lines.len() as u16,
            overflow_x: input
                .max_width
                .is_some_and(|bound| measured_width > bound + OVERFLOW_EPSILON),
            overflow_y: input
                .max_height
                .is_some_and(|bound| measured_height > bound + OVERFLOW_EPSILON),
            exceeds_max_lines,
            lines,
            diagnostics,
        }
    }

    /// A6a D3 (review contract): elide the emitted line text so SVG/PDF markup
    /// matches the raster's native "…". Wrap mode: a max_lines cut refits the
    /// last visible line into the width bound. NoWrap mode: every line wider
    /// than the bound is elided at the bound (SkParagraph's per-line elision),
    /// and a max_lines cut additionally marks the last visible line.
    fn apply_ellipsis(
        &self,
        lines: &mut [TextLineBox],
        input: &TextMeasureInput,
        family: &str,
        exceeds_max_lines: bool,
        bound: Option<f64>,
    ) {
        if matches!(input.wrap, TextWrap::Wrap) {
            if exceeds_max_lines {
                if let Some(last) = lines.last_mut() {
                    self.refit_with_ellipsis(last, input, family, bound);
                }
            }
            return;
        }
        if let Some(bound_px) = bound {
            for line in lines.iter_mut() {
                if line.width > bound_px + OVERFLOW_EPSILON {
                    self.refit_with_ellipsis(line, input, family, Some(bound_px));
                }
            }
        }
        if exceeds_max_lines {
            if let Some(last) = lines.last_mut() {
                if !last.text.ends_with('…') {
                    last.text.push('…');
                    last.width = self.line_width(family, input, &last.text);
                }
            }
        }
    }

    /// Drop trailing characters (and trailing whitespace) until `text + "…"`
    /// fits the bound, re-shaping through the real font set so the emitted
    /// width is glyph-accurate. No bound → plain append.
    fn refit_with_ellipsis(
        &self,
        line: &mut TextLineBox,
        input: &TextMeasureInput,
        family: &str,
        bound: Option<f64>,
    ) {
        if line.text.ends_with('…') {
            return;
        }
        let mut chars: Vec<char> = line.text.chars().collect();
        loop {
            while chars.last().is_some_and(|ch| ch.is_whitespace()) {
                chars.pop();
            }
            let mut candidate: String = chars.iter().collect();
            candidate.push('…');
            let width = self.line_width(family, input, &candidate);
            let fits = bound.is_none_or(|bound| width <= bound + OVERFLOW_EPSILON);
            if fits || chars.is_empty() {
                line.text = candidate;
                line.width = width;
                return;
            }
            // Proportional trim (at least one char) so long overflow lines
            // converge in a few shaping passes instead of one char at a time.
            let overshoot = bound
                .map(|bound| ((width - bound) / width * chars.len() as f64).ceil() as usize)
                .unwrap_or(1)
                .clamp(1, chars.len());
            chars.truncate(chars.len() - overshoot);
        }
    }

    /// The shaped width of a single already-cased line, used to re-account the
    /// stacked ellipsis line.
    fn line_width(&self, family: &str, input: &TextMeasureInput, text: &str) -> f64 {
        let mut paragraph = build_paragraph(
            &ParagraphRequest {
                content: text,
                font_family: family,
                font_size: input.font_size,
                font_weight: input.font_weight,
                line_height: input.line_height,
                letter_spacing: input.letter_spacing,
                max_lines: None,
                direction: input.direction.clone(),
                align: SkTextAlign::Left,
                foreground: default_foreground(),
                underline: false,
                strikethrough: false,
                // A7b D3: honor block italic so the re-accounted ellipsis line
                // width matches the italic face's advances.
                italic: input.italic,
                truncate: false,
                segments: None,
            },
            &self.fonts,
        );
        paragraph.layout(UNBOUNDED_LAYOUT_WIDTH as f32);
        f64::from(paragraph.longest_line())
    }

    /// A6b D6: measure spanned text as ONE segmented paragraph — weight-span
    /// overrides change shaping widths, so the styles must be in the measured
    /// paragraph. Per (line × segment) run boxes come from
    /// `get_rects_for_range`; a run's `x`/`width` are relative to the line's
    /// left edge (left-aligned layout), so the renderer can apply alignment to
    /// the whole line without re-shifting runs.
    fn measure_spanned(
        &self,
        input: &TextMeasureInput,
        family: &str,
        line_height_px: f64,
        mut diagnostics: Vec<Diagnostic>,
    ) -> TextMeasureOutput {
        let (normalized, map) = normalize_content_mapped(&input.content);
        let boundaries: Vec<(usize, usize)> = input
            .spans
            .iter()
            .map(|span| {
                let start = map.get(span.start).copied().unwrap_or(normalized.len());
                let end = map.get(span.end).copied().unwrap_or(normalized.len());
                (start.min(end), start.max(end))
            })
            .collect();
        let core_segments = transform_segments(&normalized, &boundaries, input.text_transform);

        // Concatenated transformed content + each segment's UTF-16 range in it
        // (SkParagraph indices are UTF-16 code units) + the styled ParagraphSegments.
        let mut concatenated = String::new();
        let mut segment_ranges: Vec<(usize, usize, Option<usize>)> = Vec::new();
        let mut para_segments: Vec<ParagraphSegment> = Vec::new();
        let mut u16_cursor = 0usize;
        for segment in &core_segments {
            let seg_u16 = segment.text.encode_utf16().count();
            segment_ranges.push((u16_cursor, u16_cursor + seg_u16, segment.span));
            u16_cursor += seg_u16;
            concatenated.push_str(&segment.text);
            let weight = segment
                .span
                .and_then(|index| input.spans.get(index))
                .and_then(|span| span.font_weight)
                .unwrap_or(input.font_weight);
            // A7b D3: italic resolves PER-RUN here — it is the SECOND channel
            // (with weight) that changes measured geometry, so it must be
            // resolved for the measured paragraph, not hardcoded. Override
            // merge (D1): `span.italic.unwrap_or(block)`, so an italic(false)
            // span de-italicizes its run inside an italic block.
            let italic = segment
                .span
                .and_then(|index| input.spans.get(index))
                .and_then(|span| span.italic)
                .unwrap_or(input.italic);
            para_segments.push(ParagraphSegment {
                text: segment.text.clone(),
                font_weight: weight,
                italic,
                // Decoration never changes measured geometry (only paint).
                underline: false,
                strikethrough: false,
                foreground: default_foreground(),
            });
        }

        let max_width = input.max_width.filter(|width| *width > 0.0);
        if concatenated.is_empty() {
            let line = TextLineBox {
                text: String::new(),
                x: 0.0,
                y: 0.0,
                width: 0.0,
                height: line_height_px,
                baseline: input.font_size,
                runs: Vec::new(),
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
                    .is_some_and(|bound| line_height_px > bound + OVERFLOW_EPSILON),
                exceeds_max_lines: false,
                diagnostics,
            };
        }

        let request = ParagraphRequest {
            content: &concatenated,
            font_family: family,
            font_size: input.font_size,
            font_weight: input.font_weight,
            line_height: input.line_height,
            letter_spacing: input.letter_spacing,
            max_lines: input.max_lines,
            direction: input.direction.clone(),
            align: SkTextAlign::Left,
            foreground: default_foreground(),
            underline: false,
            strikethrough: false,
            // Ignored when segments are set (each run carries its resolved
            // italic); mirror the block value for honesty.
            italic: input.italic,
            truncate: false,
            segments: Some(para_segments),
        };
        let mut paragraph = build_paragraph(&request, &self.fonts);
        paragraph.layout(wrap_layout_width(&input.wrap, max_width) as f32);
        diagnostics.extend(glyph_diagnostics(&self.fonts, &request, &mut paragraph, None));

        let utf16_to_byte = utf16_byte_offsets(&concatenated);
        let mut lines: Vec<TextLineBox> = Vec::new();
        for metrics in paragraph.get_line_metrics() {
            let line_start = metrics.start_index;
            let line_end = metrics.end_excluding_whitespaces;
            let text = line_text(&concatenated, &utf16_to_byte, line_start, line_end);
            let mut runs: Vec<TextRunBox> = Vec::new();
            for (seg_start, seg_end, span) in &segment_ranges {
                let run_start = (*seg_start).max(line_start);
                let run_end = (*seg_end).min(line_end);
                if run_start >= run_end {
                    continue;
                }
                let rects = paragraph.get_rects_for_range(
                    run_start..run_end,
                    RectHeightStyle::Tight,
                    RectWidthStyle::Tight,
                );
                if rects.is_empty() {
                    continue;
                }
                let mut left = f32::MAX;
                let mut right = f32::MIN;
                for text_box in &rects {
                    left = left.min(text_box.rect.left);
                    right = right.max(text_box.rect.right);
                }
                runs.push(TextRunBox {
                    text: line_text(&concatenated, &utf16_to_byte, run_start, run_end),
                    x: f64::from(left) - metrics.left,
                    width: f64::from(right - left),
                    span: *span,
                });
            }
            runs.sort_by(|a, b| a.x.partial_cmp(&b.x).unwrap_or(std::cmp::Ordering::Equal));
            lines.push(TextLineBox {
                text,
                x: metrics.left,
                y: metrics.baseline - metrics.ascent,
                width: metrics.width,
                height: metrics.height,
                baseline: metrics.baseline,
                runs,
            });
        }

        let exceeds_max_lines = paragraph.did_exceed_max_lines();
        let mut measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        let overflow_x = input
            .max_width
            .is_some_and(|bound| measured_width > bound + OVERFLOW_EPSILON);

        // A6b: land the ellipsis on the LAST run of the last visible line when
        // truncation cut content (max_lines cut, or NoWrap overflow).
        if input.truncate
            && (exceeds_max_lines || (matches!(input.wrap, TextWrap::NoWrap) && overflow_x))
        {
            if let Some(last) = lines.last_mut() {
                self.append_ellipsis_run(last, input, family);
            }
            measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        }

        let measured_height = f64::from(paragraph.height());
        let width = max_width
            .filter(|_| matches!(input.wrap, TextWrap::Wrap))
            .map(|bound| measured_width.min(bound))
            .unwrap_or(measured_width);

        TextMeasureOutput {
            width,
            height: measured_height,
            line_height_px,
            line_count: lines.len() as u16,
            overflow_x,
            overflow_y: input
                .max_height
                .is_some_and(|bound| measured_height > bound + OVERFLOW_EPSILON),
            exceeds_max_lines,
            lines,
            diagnostics,
        }
    }

    /// A6b: append U+2026 to the last run of a line and re-account its width
    /// (sanity-level; the accurate per-run refit is deferred with spans+truncate).
    fn append_ellipsis_run(&self, line: &mut TextLineBox, input: &TextMeasureInput, family: &str) {
        let ellipsis_width = self.line_width(family, input, "…");
        if let Some(last) = line.runs.last_mut() {
            if last.text.ends_with('…') {
                return;
            }
            last.text.push('…');
            last.width += ellipsis_width;
        } else {
            line.runs.push(TextRunBox {
                text: "…".to_owned(),
                x: 0.0,
                width: ellipsis_width,
                span: None,
            });
        }
        line.width += ellipsis_width;
        line.text.push('…');
    }
}

impl TextMeasurer for SkiaTextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput {
        let line_height_px = line_height_px(input.font_size, input.line_height);
        let resolution = self.fonts.resolve_family(&input.font_family);
        // A6a D1: transform AFTER normalization — normalize converts the DSL's
        // literal "\n" to a real newline (whitespace), so case-folding can
        // never corrupt the line delimiters, and every line box carries the
        // cased string the exporters emit.
        let content = input
            .text_transform
            .apply(&normalize_content(&input.content))
            .into_owned();
        let max_width = input.max_width.filter(|width| *width > 0.0);
        // Font-resolution diagnostics from the actual shaping font set —
        // document-scoped here; the layout engine re-subjects them to the node.
        let mut diagnostics = font_diagnostics(
            &self.fonts,
            &input.font_family,
            input.font_weight as i32,
            input.italic,
            None,
        );

        // A6b D6: rich-text spans take the segmented run path (weight-span
        // shaping changes widths, so styles must be in the measured paragraph).
        // Only reached when spans exist, so the spanless paths below stay
        // byte-identical to pre-A6b. (Paragraph stacking is not composed with
        // spans in v1 — the segmented path hard-breaks on `\n` natively.)
        if !input.spans.is_empty() {
            return self.measure_spanned(input, &resolution.family, line_height_px, diagnostics);
        }

        // A6a D4: paragraph stacking is ACTIVE only when a positive, finite
        // gap meets an actual `\n` break; otherwise the single-paragraph path
        // below stays byte-identical to pre-A6a.
        let paragraph_gap = input
            .paragraph_spacing
            .is_finite()
            .then_some(input.paragraph_spacing)
            .filter(|gap| *gap > 0.0)
            .unwrap_or(0.0);
        if paragraph_gap > 0.0 && content.contains('\n') {
            return self.measure_stacked(
                input,
                &resolution.family,
                &content,
                max_width,
                line_height_px,
                paragraph_gap,
                diagnostics,
            );
        }

        if content.is_empty() {
            // Mirror the heuristic: empty content still occupies one line.
            let line = TextLineBox {
                text: String::new(),
                x: 0.0,
                y: 0.0,
                width: 0.0,
                height: line_height_px,
                baseline: input.font_size,
                runs: Vec::new(),
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
                diagnostics,
            };
        }

        // Measurement reports HONEST geometry: no ellipsis injected here, so
        // overflow_x / exceeds_max_lines stay byte-identical to pre-A6a. The
        // renderer's raster path paints the native "…" via ParagraphRequest;
        // for the SVG/PDF markup that consume `lines[].text`, the ellipsis is
        // appended to the last visible line below (SkParagraph's line metrics
        // index the ORIGINAL source and never surface the injected glyph).
        let request = ParagraphRequest {
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
            // Decoration + ellipsis never change measured line geometry;
            // only the renderer paints them.
            underline: false,
            strikethrough: false,
            // A7b D3: italic DOES change geometry (italic face advances), so
            // the measured paragraph must carry it — unlike the decorations.
            italic: input.italic,
            truncate: false,
            segments: None,
        };
        let mut paragraph = build_paragraph(&request, &self.fonts);
        paragraph.layout(wrap_layout_width(&input.wrap, max_width) as f32);
        diagnostics.extend(glyph_diagnostics(&self.fonts, &request, &mut paragraph, None));

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
                runs: Vec::new(),
            });
        }

        let measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        let measured_height = f64::from(paragraph.height());
        let overflow_x = input
            .max_width
            .is_some_and(|max_width| measured_width > max_width + OVERFLOW_EPSILON);
        let exceeds_max_lines = paragraph.did_exceed_max_lines();

        // A6a D3: mirror the raster ellipsis into the emitted line text when
        // truncation actually cut content (a max_lines cut, or a NoWrap line
        // that overflows its box), refitted into the bound so SVG/PDF markup
        // matches the raster's native elision instead of overflowing it.
        if input.truncate {
            self.apply_ellipsis(
                &mut lines,
                input,
                &resolution.family,
                exceeds_max_lines,
                max_width,
            );
        }

        let measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        let width = max_width
            .filter(|_| matches!(input.wrap, TextWrap::Wrap))
            .map(|max_width| measured_width.min(max_width))
            .unwrap_or(measured_width);

        TextMeasureOutput {
            width,
            height: measured_height,
            line_height_px,
            line_count: lines.len() as u16,
            overflow_x,
            overflow_y: input
                .max_height
                .is_some_and(|max_height| measured_height > max_height + OVERFLOW_EPSILON),
            exceeds_max_lines,
            lines,
            diagnostics,
        }
    }

    /// SkParagraph is real font shaping over the loaded byte-backed faces.
    fn shaping(&self) -> bool {
        true
    }

    /// A7b D2: byte-driven truth from the loaded faces, post family-fallback —
    /// the same answer `build_paragraph`'s synthesis gate uses, so exporters
    /// and the raster agree on whether italic is renderable.
    fn has_italic_face(&self, family: &str) -> bool {
        let resolution = self.fonts.resolve_family(family);
        self.fonts.has_italic_face(&resolution.family)
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

#[cfg(test)]
mod glyph_fallback_tests {
    use super::*;
    use crate::fonts::FontManager;
    use std::sync::Arc;

    fn subset_manager() -> FontManager {
        let bytes = std::fs::read(
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("tests/fixtures/subset-face.ttf"),
        )
        .expect("subset-face fixture reads");
        let (fonts, errors) = FontManager::bundled_with(vec![(bytes, None)]);
        assert!(errors.is_empty(), "{errors:?}");
        fonts
    }

    fn input(content: &str, family: &str) -> TextMeasureInput {
        TextMeasureInput {
            node_id: None,
            font_size_override: None,
            content: content.to_owned(),
            font_family: family.to_owned(),
            font_size: 32.0,
            font_weight: 400,
            italic: false,
            line_height: 1.2,
            letter_spacing: 0.0,
            wrap: TextWrap::NoWrap,
            max_lines: None,
            direction: LumenTextDirection::Ltr,
            max_width: None,
            max_height: None,
            text_transform: lumen_core::TextTransform::None,
            truncate: false,
            paragraph_spacing: 0.0,
            spans: Vec::new(),
        }
    }

    fn paragraph(content: &str, family: &str, weight: u16, fonts: &FontManager) -> Paragraph {
        let mut paragraph = build_paragraph(
            &ParagraphRequest {
                content,
                font_family: family,
                font_size: 32.0,
                font_weight: weight,
                line_height: 1.2,
                letter_spacing: 0.0,
                max_lines: None,
                direction: LumenTextDirection::Ltr,
                align: SkTextAlign::Left,
                foreground: default_foreground(),
                underline: false,
                strikethrough: false,
                italic: false,
                truncate: false,
                segments: None,
            },
            fonts,
        );
        paragraph.layout(1000.0);
        paragraph
    }

    #[test]
    fn subset_arrow_shapes_with_loaded_fallback_without_replacing_primary_text() {
        let fonts = subset_manager();
        for weight in [400, 500] {
            let mut paragraph = paragraph("Get the guide →", "SubsetFace", weight, &fonts);
            assert_eq!(paragraph.unresolved_glyphs(), Some(0), "weight {weight}");
            let mut families = Vec::new();
            let mut arrow_found = false;
            paragraph.visit(|_, info| {
                if let Some(info) = info {
                    let face = info.font().typeface();
                    let family = face.family_name();
                    assert!(!info.glyphs().contains(&0), "tofu in {family}");
                    if family == "Inter" {
                        arrow_found |= info.glyphs().contains(&face.unichar_to_glyph('→' as i32));
                    }
                    families.push(family);
                }
            });
            assert!(
                arrow_found,
                "the arrow must shape from loaded Inter: {families:?}"
            );
            assert!(
                families.iter().any(|family| family == "SubsetFace"),
                "covered text must keep its primary face"
            );
        }
    }

    #[test]
    fn fallback_arrow_paints_the_same_pixels_as_its_loaded_supplier() {
        let fonts = subset_manager();
        let pixels = |family, weight| {
            let paragraph = paragraph("→", family, weight, &fonts);
            let mut surface = skia_safe::surfaces::raster_n32_premul((80, 60)).unwrap();
            surface.canvas().clear(SkColor::WHITE);
            paragraph.paint(surface.canvas(), (4.0, 4.0));
            let info = skia_safe::ImageInfo::new_n32_premul((80, 60), None);
            let mut pixels = vec![0; info.compute_min_byte_size()];
            assert!(surface.image_snapshot().read_pixels(
                &info,
                &mut pixels,
                info.min_row_bytes(),
                (0, 0),
                skia_safe::image::CachingHint::Disallow,
            ));
            assert!(pixels.chunks_exact(4).any(|p| p != [255, 255, 255, 255]));
            pixels
        };
        for weight in [400, 500] {
            assert_eq!(pixels("SubsetFace", weight), pixels("Inter", weight));
        }
    }

    #[test]
    fn unrelated_loaded_family_is_not_an_implicit_native_fallback() {
        let (fonts, errors) = FontManager::bundled_with(vec![(
            include_bytes!("../tests/fixtures/subset-face-bold.ttf").to_vec(),
            None,
        )]);
        assert!(errors.is_empty());
        // SVG's coverage query remains available without promising that native
        // shaping or the editor will select an unrelated loaded brand family.
        assert_eq!(fonts.substituted_chars("Inter", 400, false, "\u{e123}"), vec!['\u{e123}']);
        let mut paragraph = paragraph("guide \u{e123}", "Inter", 400, &fonts);
        assert_eq!(paragraph.unresolved_glyphs(), Some(1));
        let out = SkiaTextMeasurer::new(Arc::new(fonts)).measure(&input("guide \u{e123}", "Inter"));
        assert_eq!(
            out.diagnostics.iter().filter(|d| d.code == "LUMS0106").count(),
            1,
        );
        assert!(!out.diagnostics.iter().any(|d| d.code == "LUMS0103"));
    }

    #[test]
    fn uncovered_glyph_is_an_error_instead_of_silent_or_claimed_fallback() {
        let measurer = SkiaTextMeasurer::new(Arc::new(subset_manager()));
        let out = measurer.measure(&input("guide → \u{10fffd}", "SubsetFace"));
        let missing = out
            .diagnostics
            .iter()
            .find(|d| d.code == "LUMS0106")
            .unwrap_or_else(|| {
                panic!("missing unresolved-glyph diagnostic: {:?}", out.diagnostics)
            });
        assert_eq!(missing.severity, lumen_core::DiagnosticSeverity::Error);
        assert!(missing.message.contains("U+10FFFD"));
        let substituted = out
            .diagnostics
            .iter()
            .find(|d| d.code == "LUMS0103")
            .expect("the covered arrow still reports substitution");
        assert!(substituted.message.contains('→'));
        assert!(!substituted.message.contains('\u{10fffd}'));
    }

    fn span_coverage_measurement(base_weight: u16, span_weight: u16) -> TextMeasureOutput {
        let (fonts, errors) = FontManager::bundled_with(vec![
            (include_bytes!("../tests/fixtures/subset-face.ttf").to_vec(), None),
            (include_bytes!("../tests/fixtures/subset-face-bold.ttf").to_vec(), None),
        ]);
        assert!(errors.is_empty());
        assert_eq!(
            fonts.match_typeface("SubsetFace", 400, false).unwrap().unichar_to_glyph(0xE123),
            0,
        );
        assert_ne!(
            fonts.match_typeface("SubsetFace", 700, false).unwrap().unichar_to_glyph(0xE123),
            0,
        );
        let mut request = input("A\u{e123}", "SubsetFace");
        request.font_weight = base_weight;
        request.direction = LumenTextDirection::Rtl;
        request.spans = vec![lumen_core::TextSpan {
            start: 1,
            end: request.content.len(),
            font_weight: Some(span_weight),
            fill: None,
            underline: None,
            strikethrough: None,
            italic: None,
        }];
        SkiaTextMeasurer::new(Arc::new(fonts)).measure(&request)
    }

    #[test]
    fn rich_span_that_supplies_a_glyph_does_not_inherit_base_face_error() {
        let out = span_coverage_measurement(400, 700);
        assert!(
            !out.diagnostics.iter().any(|d| d.code == "LUMS0106"),
            "{:?}", out.diagnostics,
        );
    }

    #[test]
    fn rich_span_missing_a_glyph_is_not_hidden_by_base_face_coverage() {
        let out = span_coverage_measurement(700, 400);
        assert!(
            out.diagnostics.iter().any(|d| d.code == "LUMS0106" && d.message.contains("U+E123")),
            "{:?}", out.diagnostics,
        );
    }

    #[test]
    fn subset_gaps_have_loaded_coverage_for_svg_embedding() {
        let fonts = subset_manager();
        // Coverage evidence for the SVG embedder; the paragraph and raster
        // tests above separately verify actual shaping and painted fallback.
        let subset_face = fonts
            .match_typeface("SubsetFace", 400, false)
            .expect("subset face");
        let fallback_face = fonts.match_typeface("Inter", 400, false).expect("inter face");
        for ch in ['/', '×', '—'] {
            assert_eq!(
                subset_face.unichar_to_glyph(ch as i32),
                0,
                "subset face must lack {ch}"
            );
            assert_ne!(
                fallback_face.unichar_to_glyph(ch as i32),
                0,
                "the loaded fallback face must supply a real glyph for {ch}"
            );
        }
        // The SVG coverage query agrees on exactly these supplier gaps.
        assert_eq!(
            fonts.substituted_chars("SubsetFace", 400, false, &normalize_content("1/10 ×2 —")),
            vec!['/', '×', '—']
        );
    }

    #[test]
    fn measurer_reports_lums0103_for_subset_and_nothing_for_covered() {
        let measurer = SkiaTextMeasurer::new(Arc::new(subset_manager()));

        let out = measurer.measure(&input("1/10 ×2 —", "SubsetFace"));
        let codes: Vec<&str> = out.diagnostics.iter().map(|d| d.code.as_str()).collect();
        assert!(codes.contains(&"LUMS0103"), "{:?}", out.diagnostics);
        assert!(!codes.contains(&"LUMS0100"));
        let lums0103 = out
            .diagnostics
            .iter()
            .find(|d| d.code == "LUMS0103")
            .expect("LUMS0103");
        assert!(lums0103.message.contains("SubsetFace"));
        for ch in ['/', '×', '—'] {
            assert!(
                lums0103.message.contains(ch),
                "message must name {ch}: {}",
                lums0103.message
            );
        }

        // A fully-covered face (bundled Inter) emits nothing.
        let covered = measurer.measure(&input("1/10 ×2 —", "Inter"));
        assert!(covered.diagnostics.is_empty(), "{:?}", covered.diagnostics);
    }

    #[test]
    fn measurer_reports_lums0100_for_missing_family() {
        let measurer = SkiaTextMeasurer::bundled();
        let out = measurer.measure(&input("hello", "Comic Sans MS"));
        let codes: Vec<&str> = out.diagnostics.iter().map(|d| d.code.as_str()).collect();
        assert!(codes.contains(&"LUMS0100"), "{:?}", out.diagnostics);
    }

    #[test]
    fn shaping_flag_is_true_for_skia_measurer() {
        assert!(SkiaTextMeasurer::bundled().shaping());
    }

    #[test]
    fn weight_substitution_emits_lums0104_advisory() {
        // A6a D6.2: bundled Inter ships 400/600/700/800 — never 500. Requesting
        // 500 snaps to a neighbor, which must now advise (LUMS0104), not stay
        // silent. An exact weight the family ships (700) emits nothing.
        let measurer = SkiaTextMeasurer::bundled();
        let mut request = input("weight", "Inter");
        request.font_weight = 500;
        let out = measurer.measure(&request);
        let lums0104 = out
            .diagnostics
            .iter()
            .find(|d| d.code == "LUMS0104")
            .unwrap_or_else(|| panic!("expected LUMS0104: {:?}", out.diagnostics));
        assert!(lums0104.message.contains("Inter"));
        assert!(lums0104.message.contains("500"));

        request.font_weight = 700;
        let exact = measurer.measure(&request);
        assert!(
            !exact.diagnostics.iter().any(|d| d.code == "LUMS0104"),
            "exact weight must not advise: {:?}",
            exact.diagnostics
        );
    }

    #[test]
    fn skia_paragraph_spacing_stacks_and_zero_is_unchanged() {
        // A6a D4: a positive gap on multi-paragraph content adds height; the
        // 0.0 path is byte-identical to a single hard-broken paragraph.
        let measurer = SkiaTextMeasurer::bundled();
        let base = measurer.measure(&input("alpha\\nbeta", "Inter"));

        let mut spaced = input("alpha\\nbeta", "Inter");
        spaced.paragraph_spacing = 12.0;
        let out = measurer.measure(&spaced);
        assert_eq!(out.line_count, 2);
        assert!(
            out.height > base.height + 11.0,
            "stacked height {} must exceed base {} by ~gap",
            out.height,
            base.height
        );

        let mut zero = input("alpha\\nbeta", "Inter");
        zero.paragraph_spacing = 0.0;
        assert_eq!(measurer.measure(&zero), base);
    }
}
