use lumen_core::{measure_text, TextDirection, TextMeasureInput, TextNode, TextWrap};

fn input(content: &str) -> TextMeasureInput {
    TextMeasureInput::from_text_node(&TextNode {
        content: content.to_owned(),
        font_family: "Inter".to_owned(),
        font_size: 20.0,
        font_weight: 500,
        align: lumen_core::TextAlign::Left,
        ..TextNode::default()
    })
}

#[test]
fn text_measurement_line_height_changes_height() {
    let mut normal = input("Line one");
    normal.line_height = 1.0;
    let mut loose = normal.clone();
    loose.line_height = 1.5;

    assert!(measure_text(&loose).height > measure_text(&normal).height);
}

#[test]
fn text_measurement_letter_spacing_changes_width() {
    let normal = input("Tracking");
    let mut tracked = normal.clone();
    tracked.letter_spacing = 2.0;

    assert!(measure_text(&tracked).width > measure_text(&normal).width);
}

#[test]
fn text_measurement_wraps_to_available_width() {
    let mut wrapped = input("AI phone agents help neurosurgeons focus on surgery");
    wrapped.wrap = TextWrap::Wrap;
    wrapped.max_width = Some(160.0);

    let output = measure_text(&wrapped);

    assert!(output.line_count > 1);
    assert!(!output.overflow_x);
}

#[test]
fn text_measurement_reports_max_line_overflow() {
    let mut wrapped = input("AI phone agents help neurosurgeons focus on surgery");
    wrapped.wrap = TextWrap::Wrap;
    wrapped.max_width = Some(120.0);
    wrapped.max_lines = Some(1);
    wrapped.direction = TextDirection::Ltr;

    let output = measure_text(&wrapped);

    assert!(output.exceeds_max_lines);
    assert_eq!(output.line_count, 1);
}
