use crate::{Rect, TextDirection, TextNode, TextWrap};
use std::sync::Arc;

#[derive(Clone, Debug, PartialEq)]
pub struct TextMeasureInput {
    pub content: String,
    /// Requested font family. The heuristic measurer ignores it; shaping
    /// measurers resolve it against their loaded font set (missing families
    /// fall back to the measurer's default family policy).
    pub font_family: String,
    pub font_size: f64,
    /// Requested font weight (CSS-style 100..900).
    pub font_weight: u16,
    pub line_height: f64,
    pub letter_spacing: f64,
    pub wrap: TextWrap,
    pub max_lines: Option<u16>,
    pub direction: TextDirection,
    pub max_width: Option<f64>,
    pub max_height: Option<f64>,
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
}

#[derive(Clone, Debug, PartialEq)]
pub struct TextLineBox {
    pub text: String,
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub baseline: f64,
}

pub trait TextMeasurer: std::fmt::Debug {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput;
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
    [
        input.content.clone(),
        input.font_family.clone(),
        format!("{:.3}", input.font_size),
        input.font_weight.to_string(),
        format!("{:.3}", input.line_height),
        format!("{:.3}", input.letter_spacing),
        format!("{:?}", input.wrap),
        opt_u(input.max_lines),
        format!("{:?}", input.direction),
        opt_f(input.max_width),
        opt_f(input.max_height),
    ]
    .join("\u{1f}")
}

/// A measurer that overrides width/height for known inputs with editor-supplied
/// (SkParagraph) metrics, delegating everything else — including per-line boxes
/// — to the heuristic. Send+Sync because it holds only data (a JS-callback
/// measurer would be !Send), which is why measure-then-inject is the V0 path.
#[derive(Debug, Default)]
pub struct ProvidedTextMeasurer {
    overrides: std::collections::HashMap<String, (f64, f64)>,
    fallback: HeuristicTextMeasurer,
}

impl ProvidedTextMeasurer {
    pub fn new(overrides: std::collections::HashMap<String, (f64, f64)>) -> Self {
        Self {
            overrides,
            fallback: HeuristicTextMeasurer,
        }
    }

    pub fn is_empty(&self) -> bool {
        self.overrides.is_empty()
    }
}

impl TextMeasurer for ProvidedTextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput {
        let mut output = self.fallback.measure(input);
        if let Some(&(width, height)) = self.overrides.get(&measure_key(input)) {
            output.width = width;
            output.height = height;
        }
        output
    }
}

impl TextMeasureInput {
    pub fn from_text_node(text: &TextNode) -> Self {
        Self {
            content: text.content.clone(),
            font_family: text.font_family.clone(),
            font_size: text.font_size,
            font_weight: text.font_weight,
            line_height: text.line_height,
            letter_spacing: text.letter_spacing,
            wrap: text.wrap.clone(),
            max_lines: text.max_lines,
            direction: text.direction.clone(),
            max_width: None,
            max_height: None,
        }
    }

    pub fn with_bounds(mut self, bounds: &Rect) -> Self {
        self.max_width = Some(bounds.width.max(0.0));
        self.max_height = Some(bounds.height.max(0.0));
        self
    }
}

impl TextMeasurer for HeuristicTextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput {
        let line_height_px = line_height_px(input.font_size, input.line_height);
        let hard_lines = input.content.split("\\n").flat_map(str::lines);
        let mut lines = Vec::new();
        let max_width = input.max_width.filter(|width| *width > 0.0);

        for hard_line in hard_lines {
            if matches!(input.wrap, TextWrap::Wrap) {
                lines.extend(wrap_line(hard_line, input, max_width, line_height_px));
            } else {
                lines.push(line_box(
                    hard_line.to_owned(),
                    input,
                    lines.len(),
                    line_height_px,
                ));
            }
        }

        if lines.is_empty() {
            lines.push(line_box(String::new(), input, 0, line_height_px));
        }

        let original_line_count = lines.len();
        let exceeds_max_lines = input
            .max_lines
            .is_some_and(|max_lines| original_line_count > max_lines as usize);
        if let Some(max_lines) = input.max_lines {
            lines.truncate(max_lines as usize);
        }

        for (index, line) in lines.iter_mut().enumerate() {
            line.y = index as f64 * line_height_px;
            line.baseline = line.y + input.font_size;
        }

        let measured_width = lines.iter().map(|line| line.width).fold(0.0, f64::max);
        let measured_height = lines.len() as f64 * line_height_px;
        let width = max_width
            .filter(|_| matches!(input.wrap, TextWrap::Wrap))
            .map(|max_width| measured_width.min(max_width))
            .unwrap_or(measured_width);
        let overflow_x = input
            .max_width
            .is_some_and(|max_width| measured_width > max_width + f64::EPSILON);
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
        }
    }
}

pub fn measure_text(input: &TextMeasureInput) -> TextMeasureOutput {
    HeuristicTextMeasurer.measure(input)
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
    }
}

#[cfg(test)]
mod provided_measurer_tests {
    use super::*;

    fn input(content: &str) -> TextMeasureInput {
        TextMeasureInput {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 18.0,
            font_weight: 600,
            line_height: 1.2,
            letter_spacing: 0.0,
            wrap: TextWrap::NoWrap,
            max_lines: None,
            direction: TextDirection::Ltr,
            max_width: None,
            max_height: None,
        }
    }

    #[test]
    fn overrides_width_height_for_a_known_input_only() {
        let known = input("Hello");
        let mut overrides = std::collections::HashMap::new();
        overrides.insert(measure_key(&known), (321.0, 47.0));
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
