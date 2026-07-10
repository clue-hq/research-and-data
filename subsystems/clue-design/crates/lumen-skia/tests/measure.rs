//! Slice A2 gates: SkParagraph measurement semantics, pinned BEFORE anything
//! depends on them (risk-register item: line-height multiplier mapping).

use lumen_core::{TextDirection, TextMeasureInput, TextMeasureOutput, TextMeasurer, TextWrap};
use lumen_skia::SkiaTextMeasurer;

fn input(content: &str) -> TextMeasureInput {
    TextMeasureInput {
        content: content.to_owned(),
        font_family: "Inter".to_owned(),
        font_size: 20.0,
        font_weight: 400,
        line_height: 1.5,
        letter_spacing: 0.0,
        wrap: TextWrap::NoWrap,
        max_lines: None,
        direction: TextDirection::Ltr,
        max_width: None,
        max_height: None,
    }
}

fn wrapped(content: &str, max_width: f64) -> TextMeasureInput {
    TextMeasureInput {
        wrap: TextWrap::Wrap,
        max_width: Some(max_width),
        ..input(content)
    }
}

fn line_texts(output: &lumen_core::TextMeasureOutput) -> Vec<String> {
    output.lines.iter().map(|line| line.text.clone()).collect()
}

#[test]
fn measurement_is_deterministic() {
    let measurer = SkiaTextMeasurer::bundled();
    let request = wrapped("Determinism is the whole point of this exercise", 140.0);
    let first = measurer.measure(&request);
    let second = measurer.measure(&request);
    assert_eq!(first, second);

    // A separately constructed measurer (fresh FontManager, fresh
    // collection) must also agree bit-for-bit.
    let other = SkiaTextMeasurer::bundled();
    assert_eq!(first, other.measure(&request));
}

// Risk-register pin: SkParagraph's height override maps our line-height
// multiplier model exactly — every line is font_size * line_height tall and
// the paragraph is line_count times that.
#[test]
fn line_height_multiplier_model_is_exact() {
    let measurer = SkiaTextMeasurer::bundled();
    let output = measurer.measure(&input("alpha\\nbeta\\ngamma"));

    assert_eq!(output.line_count, 3);
    assert_eq!(output.line_height_px, 30.0);
    assert!(
        (output.height - 90.0).abs() < 0.01,
        "height {}",
        output.height
    );
    for (index, line) in output.lines.iter().enumerate() {
        assert!(
            (line.height - 30.0).abs() < 0.01,
            "line {index} height {}",
            line.height
        );
        assert!(
            (line.y - index as f64 * 30.0).abs() < 0.01,
            "line {index} y {}",
            line.y
        );
    }
    let baseline_gap = output.lines[1].baseline - output.lines[0].baseline;
    assert!(
        (baseline_gap - 30.0).abs() < 0.01,
        "baseline gap {baseline_gap}"
    );

    let mut tight = input("alpha\\nbeta");
    tight.line_height = 1.0;
    let tight_output = measurer.measure(&tight);
    assert!((tight_output.height - 40.0).abs() < 0.01);
}

#[test]
fn trivially_short_text_matches_heuristic_line_count() {
    let skia = SkiaTextMeasurer::bundled();
    let heuristic = lumen_core::HeuristicTextMeasurer;
    let request = wrapped("Hello", 400.0);
    assert_eq!(skia.measure(&request).line_count, 1);
    assert_eq!(heuristic.measure(&request).line_count, 1);
}

#[test]
fn wrap_breaks_at_word_boundaries() {
    let measurer = SkiaTextMeasurer::bundled();
    let output = measurer.measure(&wrapped("Hello brave new world", 130.0));
    assert_eq!(line_texts(&output), vec!["Hello brave", "new world"]);
    assert!(!output.overflow_x);
    for line in &output.lines {
        assert!(line.width <= 130.0 + 0.01);
    }
}

#[test]
fn hard_breaks_mirror_heuristic_semantics() {
    let measurer = SkiaTextMeasurer::bundled();
    // Literal backslash-n (as DSL strings carry), real newline, and a
    // trailing newline that must not create a trailing empty line.
    let output = measurer.measure(&input("alpha\\nbeta\ngamma\n"));
    assert_eq!(line_texts(&output), vec!["alpha", "beta", "gamma"]);

    let blank = measurer.measure(&input("a\\n\\nb"));
    assert_eq!(line_texts(&blank), vec!["a", "", "b"]);
    assert_eq!(blank.line_count, 3);
}

#[test]
fn nowrap_overflow_x_flags_against_max_width() {
    let measurer = SkiaTextMeasurer::bundled();
    let mut request = input("this line is clearly wider than fifty pixels");
    request.max_width = Some(50.0);
    let output = measurer.measure(&request);
    assert!(output.overflow_x);
    assert_eq!(output.line_count, 1);
}

#[test]
fn overflow_y_flags_against_max_height() {
    let measurer = SkiaTextMeasurer::bundled();
    let mut request = input("alpha\\nbeta\\ngamma");
    request.max_height = Some(40.0);
    let output = measurer.measure(&request);
    assert!(output.overflow_y, "three 30px lines must overflow 40px");

    request.max_height = Some(95.0);
    assert!(!measurer.measure(&request).overflow_y);
}

#[test]
fn max_lines_truncates_without_ellipsis_and_flags() {
    let measurer = SkiaTextMeasurer::bundled();
    let mut request = input("alpha\\nbeta\\ngamma");
    request.max_lines = Some(2);
    let output = measurer.measure(&request);
    assert_eq!(output.line_count, 2);
    assert_eq!(line_texts(&output), vec!["alpha", "beta"]);
    assert!(output.exceeds_max_lines);
    assert!(
        !output.lines.iter().any(|line| line.text.contains('…')),
        "ellipsis is off by contract"
    );

    request.max_lines = Some(3);
    assert!(!measurer.measure(&request).exceeds_max_lines);
}

// Pinned divergence from the heuristic: Skia breaks words longer than the
// wrap width across lines instead of overflowing. Skia's behavior is the
// contract from A2 on.
#[test]
fn long_words_break_instead_of_overflowing() {
    let measurer = SkiaTextMeasurer::bundled();
    let output = measurer.measure(&wrapped("Antidisestablishmentarianism", 80.0));
    assert!(output.line_count > 1, "long word must break across lines");
    assert!(!output.overflow_x);
    for line in &output.lines {
        assert!(line.width <= 80.0 + 0.01);
    }

    let heuristic =
        lumen_core::HeuristicTextMeasurer.measure(&wrapped("Antidisestablishmentarianism", 80.0));
    assert_eq!(heuristic.line_count, 1, "heuristic baseline for contrast");
    assert!(heuristic.overflow_x);
}

#[test]
fn rtl_direction_smoke() {
    let measurer = SkiaTextMeasurer::bundled();
    let mut request = wrapped("one two three four five", 100.0);
    request.direction = TextDirection::Rtl;
    let first = measurer.measure(&request);
    let second = measurer.measure(&request);
    assert_eq!(first, second, "RTL measurement is deterministic");
    assert!(first.line_count >= 2);
    assert!(first.width > 0.0 && first.height > 0.0);

    // Auto is pinned to LTR.
    let mut auto = wrapped("one two three four five", 100.0);
    auto.direction = TextDirection::Auto;
    let mut ltr = wrapped("one two three four five", 100.0);
    ltr.direction = TextDirection::Ltr;
    assert_eq!(measurer.measure(&auto), measurer.measure(&ltr));
}

// SkParagraph line-metrics indices are UTF-16 code units; pinned here with
// multibyte (2-byte UTF-8 / 1 UTF-16 unit) and astral (4-byte UTF-8 /
// 2 UTF-16 units) characters.
#[test]
fn line_slicing_handles_multibyte_and_astral_text() {
    let measurer = SkiaTextMeasurer::bundled();
    let multibyte = measurer.measure(&wrapped("Türkçe ölçüm metni deneme", 120.0));
    assert_eq!(
        line_texts(&multibyte),
        vec!["Türkçe", "ölçüm metni", "deneme"]
    );

    let astral = measurer.measure(&wrapped("crab 🦀 emoji astral test words", 110.0));
    assert_eq!(
        line_texts(&astral),
        vec!["crab 🦀", "emoji astral", "test words"]
    );
}

#[test]
fn missing_family_measures_identically_to_default_family() {
    let measurer = SkiaTextMeasurer::bundled();
    let mut unknown = wrapped("fallback families shape deterministically", 150.0);
    unknown.font_family = "Comic Sans MS".to_owned();
    let known = wrapped("fallback families shape deterministically", 150.0);

    let unknown_out = measurer.measure(&unknown);
    let known_out = measurer.measure(&known);

    // GEOMETRY is identical — the missing family shapes as the default family.
    // Only the diagnostics channel differs (that is the point of surfacing the
    // fallback), so compare everything except diagnostics.
    assert_eq!(
        TextMeasureOutput {
            diagnostics: Vec::new(),
            ..unknown_out.clone()
        },
        TextMeasureOutput {
            diagnostics: Vec::new(),
            ..known_out.clone()
        }
    );
    // The missing family now reports its whole-family fallback (LUMS0100);
    // the loaded family reports nothing.
    assert!(unknown_out
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMS0100"));
    assert!(known_out.diagnostics.is_empty());
}

#[test]
fn empty_content_occupies_one_line() {
    let measurer = SkiaTextMeasurer::bundled();
    let output = measurer.measure(&input(""));
    assert_eq!(output.line_count, 1);
    assert_eq!(output.height, 30.0);
    assert_eq!(output.width, 0.0);
    assert_eq!(output.lines[0].text, "");
}

#[test]
fn heavier_weight_measures_wider() {
    let measurer = SkiaTextMeasurer::bundled();
    let regular = input("Weight changes advance widths");
    let mut extra_bold = regular.clone();
    extra_bold.font_weight = 800;
    assert!(measurer.measure(&extra_bold).width > measurer.measure(&regular).width);
}

#[test]
fn letter_spacing_increases_width() {
    let measurer = SkiaTextMeasurer::bundled();
    let normal = input("Tracking");
    let mut tracked = normal.clone();
    tracked.letter_spacing = 2.0;
    assert!(measurer.measure(&tracked).width > measurer.measure(&normal).width);
}

// Real shaping diverges from the heuristic where character-width guesses are
// wrong: wide glyphs ('W') wrap under Skia where the heuristic claims a fit.
// This is exactly the class of error that invalidated heuristic-based fit
// verdicts for Phase G.
#[test]
fn shaping_catches_wraps_the_heuristic_misses() {
    // Heuristic estimate: 'W' weighs 0.62 * font_size, so this two-word
    // line "measures" ~254.6px and claims to fit 260px. Real Inter 'W'
    // advances are far wider (~375px total), so shaping wraps it.
    let request = wrapped("WWWWWWWWWW WWWWWWWWWW", 260.0);
    let heuristic = lumen_core::HeuristicTextMeasurer.measure(&request);
    let skia = SkiaTextMeasurer::bundled().measure(&request);
    assert_eq!(
        heuristic.line_count, 1,
        "heuristic believes this fits one line"
    );
    assert!(skia.line_count > 1, "real shaping knows it wraps");
}
