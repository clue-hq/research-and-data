use crate::scene::{normalize_content_mapped, transform_segments};
use crate::{Diagnostic, Phase, Rect, TextDirection, TextNode, TextSpan, TextTransform, TextWrap};
use std::collections::HashSet;
use std::sync::{Arc, Mutex};

/// The LUMS0102 warning: text was measured with a non-shaping (heuristic)
/// measurer, so glyph geometry — box sizes, wrap points, overflow verdicts — is
/// approximate. Emitted by the layout engine (folded into preflight) and by the
/// SVG/PDF export markup paths whenever they fall back to the static heuristic;
/// server paths inject a shaping measurer and never emit it. One shared
/// constructor so every emission site is byte-identical (and dedupes cleanly).
/// Modeled on LUMS0101's "degraded but never silent" pattern.
pub fn heuristic_measurement_diagnostic() -> Diagnostic {
    Diagnostic::warning(
        Phase::Layout,
        "LUMS0102",
        "text measured heuristically — no font shaping; geometry is approximate".to_owned(),
        None,
    )
    .with_hint(
        "Inject a shaping text measurer (the server's SkiaTextMeasurer) for glyph-accurate line breaks, widths, and overflow verdicts; heuristic geometry can disagree with the rendered export.",
    )
}

#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct TextMeasureInput {
    /// Browser measurement scope, so equal literals with different kit tokens do
    /// not share overrides. Native shapers do not use this to select typography.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_id: Option<String>,
    /// Slot shrink probe size takes precedence over the browser's kit size.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub font_size_override: Option<f64>,
    pub content: String,
    /// Requested font family. The heuristic measurer ignores it; shaping
    /// measurers resolve it against their loaded font set (missing families
    /// fall back to the measurer's default family policy).
    pub font_family: String,
    pub font_size: f64,
    /// Requested font weight (CSS-style 100..900).
    pub font_weight: u16,
    /// Italic style (A7b D3). Unlike the decoration channels, italic selects a
    /// different face (`Slant::Italic`) whose glyphs have different advances, so
    /// it is a genuine measurement input — it joins `measure_key` and both
    /// measurers (the heuristic one carries it but models no width delta, its
    /// existing approximation honesty).
    pub italic: bool,
    pub line_height: f64,
    pub letter_spacing: f64,
    pub wrap: TextWrap,
    pub max_lines: Option<u16>,
    pub direction: TextDirection,
    pub max_width: Option<f64>,
    pub max_height: Option<f64>,
    /// Display-time case transform (A6a D1). Applied by the measurer to each
    /// hard line so the literal `\n` delimiters are never case-folded, and so
    /// line boxes carry the cased strings the exporters emit.
    pub text_transform: TextTransform,
    /// Ellipsis truncation (A6a D3): the last visible cut line ends with "…".
    pub truncate: bool,
    /// Extra vertical gap (px) inserted at each `\n` paragraph break (A6a D4).
    pub paragraph_spacing: f64,
    /// Rich-text spans (A6b D6). Empty ⇒ every measurer keeps its pre-A6b fast
    /// path byte-for-byte; non-empty activates the segmented run path.
    pub spans: Vec<TextSpan>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TextMeasureOutput {
    pub width: f64,
    pub height: f64,
    pub line_height_px: f64,
    pub line_count: u16,
    pub lines: Vec<TextLineBox>,
    pub overflow_x: bool,
    pub overflow_y: bool,
    pub exceeds_max_lines: bool,
    /// Diagnostics produced *by measurement itself* — font-resolution
    /// warnings a shaping measurer discovers while laying the text out
    /// (LUMS0100 whole-family fallback, LUMS0103 per-glyph substitution).
    /// The heuristic measurer has no font set, so it never populates this;
    /// only `SkiaTextMeasurer` does. Callers (the layout engine) fold these
    /// into their own diagnostics so missing fonts surface at preflight, not
    /// only at export. Excluded from `measure_key` semantics: it is derived
    /// output, not an input.
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TextLineBox {
    pub text: String,
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub baseline: f64,
    /// Rich-text runs (A6b D6): the styled sub-segments of this line, in visual
    /// order, each with an `x`/`width` RELATIVE to the line's left edge and the
    /// span it belongs to (`None` = base). EMPTY on the pre-A6b path (no spans),
    /// where renderers emit the single-run `text` exactly as before — so a
    /// spanless measurement is byte-identical to A6a. Internal only (never
    /// serialized to the editor bridge).
    pub runs: Vec<TextRunBox>,
}

/// One styled run within a [`TextLineBox`] (A6b D6). `x`/`width` are relative to
/// the line's left edge (measurement lays out left-aligned; the renderer applies
/// alignment to the whole line). `span` indexes the node's `spans`, or `None`
/// for the base run.
#[derive(Clone, Debug, PartialEq)]
pub struct TextRunBox {
    pub text: String,
    pub x: f64,
    pub width: f64,
    pub span: Option<usize>,
}

pub trait TextMeasurer: std::fmt::Debug {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput;

    /// Whether this measurer performs real font shaping — glyph-accurate line
    /// breaking and metrics from loaded faces. `false` means the geometry is a
    /// heuristic approximation (no font shaping), which the layout engine
    /// surfaces as the LUMS0102 "measured heuristically" warning so degraded
    /// geometry is never silent. Default `false`: a new measurer is treated as
    /// non-shaping until it explicitly proves otherwise.
    fn shaping(&self) -> bool {
        false
    }

    /// A7b D2: whether the family (post-fallback-resolution) has a REAL italic
    /// face loaded. Exporters gate `font-style="italic"` emission on this so an
    /// artifact never asks its viewer to synthesize a fake oblique the raster
    /// deliberately refuses to draw (the shaper renders such text upright +
    /// LUMS0105). Default `true` for non-shaping measurers: with no face
    /// knowledge, scene truth stands (those contexts render no pixels).
    fn has_italic_face(&self, _family: &str) -> bool {
        true
    }
}

/// Shared handle for injected measurers (Decision 5, Wave 1 Track A).
/// `None` at the injection points means the heuristic fallback, which keeps
/// wasm builds and pre-injection tests bit-identical.
pub type SharedTextMeasurer = Arc<dyn TextMeasurer + Send + Sync>;

#[derive(Clone, Debug, Default)]
pub struct HeuristicTextMeasurer;

/// A stable key for a measurement input, shared by the editor's
/// measure-then-inject convergence (Wave 3 C4). The editor supplies SkParagraph
/// width/height keyed by the same input fields the engine lays out with, so
/// editor `computed` geometry becomes Skia-faithful (closing the E3 caveat)
/// without a wasm→JS callback during layout. The key logic lives only here;
/// the editor sends raw inputs and the engine computes the key.
pub fn measure_key(input: &TextMeasureInput) -> String {
    fn opt_f(value: Option<f64>) -> String {
        value
            .map(|v| format!("{v:.3}"))
            .unwrap_or_else(|| "_".to_owned())
    }
    fn opt_u(value: Option<u16>) -> String {
        value
            .map(|v| v.to_string())
            .unwrap_or_else(|| "_".to_owned())
    }
    // Unit-separator delimited; covers every field that affects measurement.
    let key = [
        input.content.clone(),
        input.font_family.clone(),
        format!("{:.3}", input.font_size),
        input.font_weight.to_string(),
        input.italic.to_string(),
        format!("{:.3}", input.line_height),
        format!("{:.3}", input.letter_spacing),
        format!("{:?}", input.wrap),
        opt_u(input.max_lines),
        format!("{:?}", input.direction),
        opt_f(input.max_width),
        opt_f(input.max_height),
        format!("{:?}", input.text_transform),
        input.truncate.to_string(),
        format!("{:.3}", input.paragraph_spacing),
        spans_digest(&input.spans),
    ]
    .join("\u{1f}");
    let key = input
        .font_size_override
        .map(|size| format!("shrink:{size:.3}:{key}"))
        .unwrap_or(key);
    match &input.node_id {
        Some(node_id) => format!("{}:{}{}", node_id.len(), node_id, key),
        None => key,
    }
}

/// A stable digest of the spans (A6b D6) for `measure_key`: identical spans
/// produce identical keys, and any channel change re-keys the measurement.
/// Empty spans digest to the empty string, so the pre-A6b key is unchanged
/// for every existing (spanless) input.
fn spans_digest(spans: &[TextSpan]) -> String {
    if spans.is_empty() {
        return String::new();
    }
    spans
        .iter()
        .map(|span| {
            format!(
                "{}:{}:{:?}:{:?}:{:?}:{:?}:{:?}",
                span.start,
                span.end,
                span.fill,
                span.font_weight,
                span.underline,
                span.strikethrough,
                span.italic
            )
        })
        .collect::<Vec<_>>()
        .join("\u{1e}")
}

/// One editor-measured (SkParagraph) line box, paragraph-relative and laid out
/// LEFT-aligned — exactly what `SkiaTextMeasurer` reports (`TextLineBox`),
/// so the layout engine places it by `align`/`valign` the same way.
#[derive(Clone, Debug, PartialEq)]
pub struct ProvidedLine {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub baseline: f64,
}

/// One editor-supplied measurement: the overall extent, and (Plan 4 item F)
/// optionally the painted line boxes. `None` keeps the pre-Plan-4 behaviour —
/// heuristic per-line detail under a Skia-faithful extent.
#[derive(Clone, Debug, PartialEq)]
pub struct ProvidedMetrics {
    pub width: f64,
    pub height: f64,
    pub lines: Option<Vec<ProvidedLine>>,
}

/// A measurer that overrides width/height for known inputs with editor-supplied
/// (SkParagraph) metrics, delegating everything else — including per-line boxes
/// — to the heuristic, unless the record carries lines (Plan 4 item F), in
/// which case those replace the heuristic ones outright. Send+Sync because it
/// holds only data (a JS-callback measurer would be !Send), which is why
/// measure-then-inject is the V0 path.
#[derive(Debug, Default)]
pub struct ProvidedTextMeasurer {
    overrides: std::collections::HashMap<String, ProvidedMetrics>,
    fallback: HeuristicTextMeasurer,
    missing: Mutex<std::collections::BTreeMap<String, TextMeasureInput>>,
}

impl ProvidedTextMeasurer {
    pub fn new(overrides: std::collections::HashMap<String, ProvidedMetrics>) -> Self {
        Self {
            overrides,
            fallback: HeuristicTextMeasurer,
            missing: Mutex::default(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.overrides.is_empty()
    }

    /// Exact requests made during this layout which still used the heuristic.
    pub fn missing_inputs(&self) -> Vec<TextMeasureInput> {
        self.missing
            .lock()
            .expect("measurement requests lock")
            .values()
            .cloned()
            .collect()
    }
}

impl TextMeasurer for ProvidedTextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput {
        let mut output = self.fallback.measure(input);
        let key = measure_key(input);
        // Older editor callers supplied unscoped metrics. Prefer the scoped
        // record; retain their fallback without conflating new scoped nodes.
        let metrics = self.overrides.get(&key).or_else(|| {
            let mut unscoped = input.clone();
            unscoped.node_id = None;
            self.overrides.get(&measure_key(&unscoped))
        });
        if let Some(metrics) = metrics {
            output.width = metrics.width;
            output.height = metrics.height;
            // Plan 4 item F: a record that carries the editor's line boxes
            // replaces the heuristic lines outright — those are what the
            // canvas paints, so they are what hit-testing and the selection
            // outline must see. Runs stay empty (never serialized; only the
            // exporters read them, and they run under the shaping measurer).
            if let Some(lines) = &metrics.lines {
                output.lines = lines
                    .iter()
                    .map(|line| TextLineBox {
                        text: String::new(),
                        x: line.x,
                        y: line.y,
                        width: line.width,
                        height: line.height,
                        baseline: line.baseline,
                        runs: Vec::new(),
                    })
                    .collect();
                output.line_count = output.lines.len() as u16;
            }
        } else {
            self.missing
                .lock()
                .expect("measurement requests lock")
                .entry(key)
                .or_insert_with(|| input.clone());
        }
        output
    }

    /// Non-shaping. It patches the overall width/height of *known* inputs with
    /// editor-supplied CanvasKit metrics, but performs no shaping itself: per-
    /// line boxes stay heuristic unless the record carries the editor's own,
    /// and any input without a stored override is pure heuristic. Reporting
    /// `true` would suppress the LUMS0102 warning
    /// while the geometry is still approximate, so it is honestly `false`.
    /// (Only used inside the wasm engine, where LUMS0102 is deduped against the
    /// editor's own client-side EDITOR_HEURISTIC_MEASUREMENT signal anyway.)
    fn shaping(&self) -> bool {
        false
    }
}

impl TextMeasureInput {
    pub fn from_text_node(text: &TextNode) -> Self {
        Self {
            node_id: None,
            font_size_override: None,
            content: text.content.clone(),
            font_family: text.font_family.clone(),
            font_size: text.font_size,
            font_weight: text.font_weight,
            italic: text.italic,
            line_height: text.line_height,
            letter_spacing: text.letter_spacing,
            wrap: text.wrap.clone(),
            max_lines: text.max_lines,
            direction: text.direction.clone(),
            max_width: None,
            max_height: None,
            text_transform: text.text_transform,
            truncate: text.truncate,
            paragraph_spacing: text.paragraph_spacing,
            spans: text.spans.clone(),
        }
    }

    pub fn for_node(mut self, node_id: &crate::NodeId) -> Self {
        self.node_id = Some(node_id.to_string());
        self
    }

    pub fn with_bounds(mut self, bounds: &Rect) -> Self {
        self.max_width = Some(bounds.width.max(0.0));
        self.max_height = Some(bounds.height.max(0.0));
        self
    }
}

impl TextMeasurer for HeuristicTextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput {
        // A6b D6: the segmented run path activates ONLY when spans exist, so
        // every spanless measurement stays byte-identical to A6a below.
        if !input.spans.is_empty() {
            return measure_heuristic_spanned(input);
        }
        let line_height_px = line_height_px(input.font_size, input.line_height);
        let mut lines = Vec::new();
        let max_width = input.max_width.filter(|width| *width > 0.0);
        // A6a D4: a positive, finite paragraph_spacing inserts extra vertical
        // gap at each `\n` break. Zero (or non-finite) keeps the pre-A6a
        // uniform stack byte-for-byte identical.
        let paragraph_gap = input
            .paragraph_spacing
            .is_finite()
            .then_some(input.paragraph_spacing)
            .filter(|gap| *gap > 0.0)
            .unwrap_or(0.0);
        // Line index where each `\n`-delimited paragraph begins, so the stack
        // loop knows where to inject the gap.
        let mut paragraph_starts: HashSet<usize> = HashSet::new();

        for hard_line in input.content.split("\\n").flat_map(str::lines) {
            paragraph_starts.insert(lines.len());
            // A6a D1: transform per hard line — the literal "\n" delimiters are
            // already consumed by the split, so case-folding can never corrupt
            // them, and title-case restarts word boundaries at each line.
            let transformed = input.text_transform.apply(hard_line);
            if matches!(input.wrap, TextWrap::Wrap) {
                lines.extend(wrap_line(
                    transformed.as_ref(),
                    input,
                    max_width,
                    line_height_px,
                ));
            } else {
                lines.push(line_box(
                    transformed.into_owned(),
                    input,
                    lines.len(),
                    line_height_px,
                ));
            }
        }

        if lines.is_empty() {
            paragraph_starts.insert(0);
            lines.push(line_box(String::new(), input, 0, line_height_px));
        }

        let original_line_count = lines.len();
        let exceeds_max_lines = input
            .max_lines
            .is_some_and(|max_lines| original_line_count > max_lines as usize);
        if let Some(max_lines) = input.max_lines {
            lines.truncate(max_lines as usize);
        }

        // Overflow reports the HONEST pre-elision geometry: the loss stays
        // diagnosed even after the ellipsis makes it look intentional.
        let pre_elide_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);

        // A6a D3 (review contract, mirrors the shaping measurer): Wrap mode —
        // a max_lines cut elides the last visible line into the width bound.
        // NoWrap mode — every line wider than the bound is elided at the
        // bound, and a max_lines cut additionally marks the last visible line.
        if input.truncate {
            if matches!(input.wrap, TextWrap::Wrap) {
                if exceeds_max_lines {
                    if let Some(last) = lines.last_mut() {
                        append_ellipsis(last, input, max_width);
                    }
                }
            } else {
                if let Some(bound) = max_width {
                    for line in lines.iter_mut() {
                        if line.width > bound {
                            append_ellipsis(line, input, Some(bound));
                        }
                    }
                }
                if exceeds_max_lines {
                    if let Some(last) = lines.last_mut() {
                        if !last.text.ends_with('…') {
                            append_ellipsis(last, input, None);
                        }
                    }
                }
            }
        }

        // Stack line boxes, adding the paragraph gap at each paragraph start
        // after the first (gap == 0 reproduces `index * line_height_px`).
        let mut cursor_y = 0.0;
        for (index, line) in lines.iter_mut().enumerate() {
            if index > 0 && paragraph_gap > 0.0 && paragraph_starts.contains(&index) {
                cursor_y += paragraph_gap;
            }
            line.y = cursor_y;
            line.baseline = cursor_y + input.font_size;
            cursor_y += line_height_px;
        }

        let measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        let measured_height = cursor_y;
        let width = max_width
            .filter(|_| matches!(input.wrap, TextWrap::Wrap))
            .map(|max_width| measured_width.min(max_width))
            .unwrap_or(measured_width);
        let overflow_x = input
            .max_width
            .is_some_and(|max_width| pre_elide_width > max_width + f64::EPSILON);
        let overflow_y = input
            .max_height
            .is_some_and(|max_height| measured_height > max_height + f64::EPSILON);

        TextMeasureOutput {
            width,
            height: measured_height,
            line_height_px,
            line_count: lines.len() as u16,
            lines,
            overflow_x,
            overflow_y,
            exceeds_max_lines,
            // The heuristic has no font set; font-resolution diagnostics are a
            // shaping-measurer concern only.
            diagnostics: Vec::new(),
        }
    }
}

pub fn measure_text(input: &TextMeasureInput) -> TextMeasureOutput {
    HeuristicTextMeasurer.measure(input)
}

/// A6b D6: the heuristic measurer's spanned path. Normalizes content, remaps
/// span offsets onto the normalized string, transforms segments (D5), and lays
/// runs left-to-right per hard (`\n`) line. Weight is ignored (the heuristic
/// already ignores family/weight); each run carries its `estimate_text_width`.
///
/// KNOWN APPROXIMATION (heuristic only, on the record): spanned text is not soft-
/// wrapped here — each hard line becomes one measured line even in `Wrap` mode.
/// The heuristic is already "geometry approximate" (LUMS0102); the server's Skia
/// measurer performs true wrapping of spanned runs. Paragraph spacing is also not
/// composed with spans (single-stack). These are v1 scope limits, reported.
fn measure_heuristic_spanned(input: &TextMeasureInput) -> TextMeasureOutput {
    let line_height_px = line_height_px(input.font_size, input.line_height);
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
    let segments = transform_segments(&normalized, &boundaries, input.text_transform);

    // Split into logical lines on `\n`, tagging each run with its span.
    let mut logical: Vec<Vec<(String, Option<usize>)>> = vec![Vec::new()];
    for segment in &segments {
        for (index, part) in segment.text.split('\n').enumerate() {
            if index > 0 {
                logical.push(Vec::new());
            }
            if !part.is_empty() {
                logical
                    .last_mut()
                    .expect("current line")
                    .push((part.to_owned(), segment.span));
            }
        }
    }

    let mut lines: Vec<TextLineBox> = logical
        .iter()
        .map(|runs_data| {
            let mut x = 0.0;
            let mut runs = Vec::with_capacity(runs_data.len());
            let mut text = String::new();
            for (run_text, span) in runs_data {
                let width = estimate_text_width(run_text, input.font_size, input.letter_spacing);
                runs.push(TextRunBox {
                    text: run_text.clone(),
                    x,
                    width,
                    span: *span,
                });
                x += width;
                text.push_str(run_text);
            }
            TextLineBox {
                text,
                x: 0.0,
                y: 0.0,
                width: x,
                height: line_height_px,
                baseline: 0.0,
                runs,
            }
        })
        .collect();

    let original_line_count = lines.len();
    let exceeds_max_lines = input
        .max_lines
        .is_some_and(|max_lines| original_line_count > max_lines as usize);
    if let Some(max_lines) = input.max_lines {
        lines.truncate(max_lines as usize);
    }
    let pre_elide_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);

    // A6b + A6a D3: a max_lines cut lands the ellipsis on the LAST run of the
    // last visible line (NoWrap per-line width elision of spanned runs is a
    // documented heuristic gap; the Skia path handles it).
    if input.truncate && exceeds_max_lines {
        if let Some(last) = lines.last_mut() {
            append_ellipsis_to_last_run(last, input);
        }
    }

    let mut cursor_y = 0.0;
    for line in lines.iter_mut() {
        line.y = cursor_y;
        line.baseline = cursor_y + input.font_size;
        cursor_y += line_height_px;
    }

    let measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
    let measured_height = cursor_y;
    let max_width = input.max_width.filter(|width| *width > 0.0);
    let width = max_width
        .filter(|_| matches!(input.wrap, TextWrap::Wrap))
        .map(|bound| measured_width.min(bound))
        .unwrap_or(measured_width);

    TextMeasureOutput {
        width,
        height: measured_height,
        line_height_px,
        line_count: lines.len() as u16,
        lines,
        overflow_x: input
            .max_width
            .is_some_and(|bound| pre_elide_width > bound + f64::EPSILON),
        overflow_y: input
            .max_height
            .is_some_and(|bound| measured_height > bound + f64::EPSILON),
        exceeds_max_lines,
        diagnostics: Vec::new(),
    }
}

/// Append U+2026 to the last run of a line (A6b heuristic ellipsis) and
/// re-account both the run width and the line width.
fn append_ellipsis_to_last_run(line: &mut TextLineBox, input: &TextMeasureInput) {
    if let Some(last) = line.runs.last_mut() {
        if last.text.ends_with('…') {
            return;
        }
        last.text.push('…');
        let new_width = estimate_text_width(&last.text, input.font_size, input.letter_spacing);
        let delta = new_width - last.width;
        last.width = new_width;
        line.width += delta;
        line.text.push('…');
    } else {
        line.text.push('…');
        line.runs.push(TextRunBox {
            text: "…".to_owned(),
            x: 0.0,
            width: estimate_text_width("…", input.font_size, input.letter_spacing),
            span: None,
        });
        line.width = line.runs[0].width;
    }
}

pub fn line_height_px(font_size: f64, line_height: f64) -> f64 {
    font_size * line_height.max(0.1)
}

pub fn estimate_text_width(content: &str, font_size: f64, letter_spacing: f64) -> f64 {
    let mut char_count = 0usize;
    let weighted_chars = content.chars().fold(0.0, |acc, ch| {
        char_count += 1;
        acc + if ch.is_whitespace() {
            0.33
        } else if ch.is_ascii_uppercase() {
            0.62
        } else {
            0.52
        }
    });
    let tracking = char_count.saturating_sub(1) as f64 * letter_spacing;
    (weighted_chars * font_size + tracking).max(0.0)
}

fn wrap_line(
    source: &str,
    input: &TextMeasureInput,
    max_width: Option<f64>,
    line_height_px: f64,
) -> Vec<TextLineBox> {
    let Some(max_width) = max_width else {
        return vec![line_box(source.to_owned(), input, 0, line_height_px)];
    };

    let mut lines = Vec::new();
    let mut current = String::new();
    for word in source.split_whitespace() {
        let candidate = if current.is_empty() {
            word.to_owned()
        } else {
            format!("{current} {word}")
        };
        if !current.is_empty()
            && estimate_text_width(&candidate, input.font_size, input.letter_spacing) > max_width
        {
            lines.push(line_box(current, input, lines.len(), line_height_px));
            current = word.to_owned();
        } else {
            current = candidate;
        }
    }

    if !current.is_empty() || source.is_empty() {
        lines.push(line_box(current, input, lines.len(), line_height_px));
    }
    lines
}

/// Append U+2026 to a cut line and re-account its estimated width, dropping
/// trailing characters (before the ellipsis) until it fits the width bound.
/// Heuristic precision is sufficient here — the shaping measurer uses
/// SkParagraph's native ellipsis instead.
fn append_ellipsis(line: &mut TextLineBox, input: &TextMeasureInput, max_width: Option<f64>) {
    let mut chars: Vec<char> = line.text.chars().collect();
    loop {
        // Never leave trailing whitespace before the ellipsis ("word …").
        while chars.last().is_some_and(|ch| ch.is_whitespace()) {
            chars.pop();
        }
        let mut candidate: String = chars.iter().collect();
        candidate.push('…');
        let width = estimate_text_width(&candidate, input.font_size, input.letter_spacing);
        let fits = max_width.is_none_or(|bound| width <= bound);
        if fits || chars.is_empty() {
            line.text = candidate;
            line.width = width;
            return;
        }
        chars.pop();
    }
}

fn line_box(
    text: String,
    input: &TextMeasureInput,
    index: usize,
    line_height_px: f64,
) -> TextLineBox {
    let y = index as f64 * line_height_px;
    TextLineBox {
        width: estimate_text_width(&text, input.font_size, input.letter_spacing),
        text,
        x: 0.0,
        y,
        height: line_height_px,
        baseline: y + input.font_size,
        runs: Vec::new(),
    }
}

#[cfg(test)]
mod provided_measurer_tests {
    use super::*;

    fn input(content: &str) -> TextMeasureInput {
        TextMeasureInput {
            node_id: None,
            font_size_override: None,
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 18.0,
            font_weight: 600,
            italic: false,
            line_height: 1.2,
            letter_spacing: 0.0,
            wrap: TextWrap::NoWrap,
            max_lines: None,
            direction: TextDirection::Ltr,
            max_width: None,
            max_height: None,
            text_transform: TextTransform::None,
            truncate: false,
            paragraph_spacing: 0.0,
            spans: Vec::new(),
        }
    }

    #[test]
    fn overrides_width_height_for_a_known_input_only() {
        let known = input("Hello");
        let mut overrides = std::collections::HashMap::new();
        overrides.insert(
            measure_key(&known),
            ProvidedMetrics {
                width: 321.0,
                height: 47.0,
                lines: None,
            },
        );
        let measurer = ProvidedTextMeasurer::new(overrides);

        // Known input → the editor's Skia-faithful override.
        let out = measurer.measure(&known);
        assert_eq!(out.width, 321.0);
        assert_eq!(out.height, 47.0);
        // Per-line detail still comes from the heuristic (not overridden).
        assert_eq!(
            out.line_count,
            HeuristicTextMeasurer.measure(&known).line_count
        );

        // Unknown input → heuristic fallback, unchanged.
        let other = input("Different");
        let fallback = HeuristicTextMeasurer.measure(&other);
        let provided = measurer.measure(&other);
        assert_eq!(provided.width, fallback.width);
        assert_eq!(provided.height, fallback.height);
    }

    #[test]
    fn provided_lines_replace_the_heuristic_lines() {
        let known = input("Hello there");
        let mut overrides = std::collections::HashMap::new();
        overrides.insert(
            measure_key(&known),
            ProvidedMetrics {
                width: 120.0,
                height: 43.2,
                lines: Some(vec![
                    ProvidedLine {
                        x: 0.0,
                        y: 0.0,
                        width: 120.0,
                        height: 21.6,
                        baseline: 17.0,
                    },
                    ProvidedLine {
                        x: 0.0,
                        y: 21.6,
                        width: 60.0,
                        height: 21.6,
                        baseline: 38.6,
                    },
                ]),
            },
        );
        let measurer = ProvidedTextMeasurer::new(overrides);
        let out = measurer.measure(&known);
        assert_eq!(out.line_count, 2);
        assert_eq!(out.lines.len(), 2);
        assert_eq!(out.lines[1].y, 21.6);
        assert_eq!(out.lines[1].width, 60.0);
        assert_eq!(out.lines[1].baseline, 38.6);
        assert!(out.lines[1].runs.is_empty());
    }

    #[test]
    fn key_distinguishes_inputs_that_change_measurement() {
        let base = input("Hello");
        assert_eq!(measure_key(&base), measure_key(&input("Hello")));

        let mut bigger = input("Hello");
        bigger.font_size = 24.0;
        assert_ne!(measure_key(&base), measure_key(&bigger));

        let mut bounded = input("Hello");
        bounded.max_width = Some(120.0);
        assert_ne!(measure_key(&base), measure_key(&bounded));
    }
}

#[cfg(test)]
mod a6_heuristic_tests {
    use super::*;
    use crate::{TextNode, TextTransform};

    fn node(content: &str) -> TextNode {
        TextNode {
            content: content.to_owned(),
            font_size: 20.0,
            ..TextNode::default()
        }
    }

    #[test]
    fn uppercase_transform_widens_the_estimate_and_cases_line_text() {
        let plain = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&node("data")));
        let upper_node = TextNode {
            text_transform: TextTransform::Uppercase,
            ..node("data")
        };
        let upper = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&upper_node));
        assert_eq!(upper.lines[0].text, "DATA");
        // Uppercase glyphs weigh more in the heuristic → strictly wider.
        assert!(
            upper.width > plain.width,
            "{} !> {}",
            upper.width,
            plain.width
        );
    }

    #[test]
    fn paragraph_spacing_zero_is_byte_identical_to_no_spacing() {
        let mut spaced = TextMeasureInput::from_text_node(&node("alpha\\nbeta"));
        let base = spaced.clone();
        spaced.paragraph_spacing = 0.0;
        assert_eq!(
            HeuristicTextMeasurer.measure(&base),
            HeuristicTextMeasurer.measure(&spaced)
        );
    }

    #[test]
    fn paragraph_spacing_adds_gap_between_paragraphs_only() {
        let base =
            HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&node("alpha\\nbeta")));
        let spaced_node = TextNode {
            paragraph_spacing: 10.0,
            ..node("alpha\\nbeta")
        };
        let spaced = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&spaced_node));
        // First line unchanged; the second paragraph shifts down by the gap.
        assert_eq!(spaced.lines[0].y, base.lines[0].y);
        assert!((spaced.lines[1].y - base.lines[1].y - 10.0).abs() < 1e-9);
        assert!((spaced.height - base.height - 10.0).abs() < 1e-9);
    }

    #[test]
    fn truncate_appends_ellipsis_to_the_cut_line() {
        let mut node = node("one\\ntwo\\nthree");
        node.max_lines = Some(2);
        node.truncate = true;
        let out = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&node));
        assert_eq!(out.line_count, 2);
        assert!(out.exceeds_max_lines);
        assert!(out.lines[1].text.ends_with('…'), "{:?}", out.lines[1].text);

        // Without truncate, no ellipsis.
        node.truncate = false;
        let plain = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&node));
        assert!(!plain.lines[1].text.contains('…'));
    }
}
