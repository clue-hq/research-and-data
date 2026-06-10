use crate::{Rect, TextDirection, TextNode, TextWrap};

#[derive(Clone, Debug, PartialEq)]
pub struct TextMeasureInput {
    pub content: String,
    pub font_size: f64,
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

pub trait TextMeasurer {
    fn measure(&self, input: &TextMeasureInput) -> TextMeasureOutput;
}

#[derive(Clone, Debug, Default)]
pub struct HeuristicTextMeasurer;

impl TextMeasureInput {
    pub fn from_text_node(text: &TextNode) -> Self {
        Self {
            content: text.content.clone(),
            font_size: text.font_size,
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
