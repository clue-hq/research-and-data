//! Slice A2 gates: SkParagraph measurement semantics, pinned BEFORE anything
//! depends on them (risk-register item: line-height multiplier mapping).

use lumen_core::{
    TextDirection, TextMeasureInput, TextMeasureOutput, TextMeasurer, TextSpan, TextTransform,
    TextWrap,
};
use lumen_skia::SkiaTextMeasurer;

/// A6b: a spanned input over the bundled font set.
fn spanned_input(content: &str, spans: Vec<TextSpan>) -> TextMeasureInput {
    let mut input = input(content);
    input.spans = spans;
    input
}

fn plain_span(start: usize, end: usize) -> TextSpan {
    TextSpan {
        start,
        end,
        fill: None,
        font_weight: None,
        underline: None,
        strikethrough: None,
        italic: None,
    }
}

#[test]
fn a6b_weight_span_changes_measured_width() {
    // Bundled Inter ships 400 and 800. The SAME text at weight 800 shapes wider
    // than at 400, so a weight-span must change the measured run/line width —
    // proving styles reach the shaper (not just the renderer).
    let measurer = SkiaTextMeasurer::bundled();
    let base = measurer.measure(&spanned_input("HEAVY", vec![plain_span(0, 5)]));
    let heavy = measurer.measure(&spanned_input(
        "HEAVY",
        vec![TextSpan {
            font_weight: Some(800),
            ..plain_span(0, 5)
        }],
    ));
    assert!(
        heavy.width > base.width,
        "weight-800 span must widen the line: {} !> {}",
        heavy.width,
        base.width
    );
    // The span run itself is wider than the same run at base weight.
    let base_run = base.lines[0].runs.last().unwrap();
    let heavy_run = heavy.lines[0].runs.last().unwrap();
    assert!(heavy_run.width > base_run.width);
}

#[test]
fn a6b_runs_partition_the_line_with_ordered_x() {
    let measurer = SkiaTextMeasurer::bundled();
    // "Every outage" with "outage" [6,12) as a run.
    let out = measurer.measure(&spanned_input("Every outage", vec![plain_span(6, 12)]));
    let line = &out.lines[0];
    assert!(line.runs.len() >= 2, "base + span runs: {:?}", line.runs);
    let mut last_right = -1.0;
    for run in &line.runs {
        assert!(run.width > 0.0, "run has width: {:?}", run);
        assert!(run.x >= last_right - 0.5, "runs ordered by x: {:?}", line.runs);
        last_right = run.x + run.width;
    }
    // Exactly one run carries the span.
    assert_eq!(line.runs.iter().filter(|r| r.span == Some(0)).count(), 1);
    let span_run = line.runs.iter().find(|r| r.span == Some(0)).unwrap();
    assert_eq!(span_run.text, "outage");
    // The span run starts to the right of the base run (x > 0).
    assert!(span_run.x > 0.0, "span run offset into the line: {:?}", span_run);
}

#[test]
fn a6b_spanned_ellipsis_lands_on_last_run() {
    let measurer = SkiaTextMeasurer::bundled();
    let mut input = spanned_input("one two three four five six", vec![plain_span(0, 3)]);
    input.wrap = TextWrap::NoWrap;
    input.truncate = true;
    input.max_width = Some(80.0);
    let out = measurer.measure(&input);
    let last_run = out.lines.last().unwrap().runs.last().expect("a run");
    assert!(
        last_run.text.ends_with('…'),
        "ellipsis on last run: {:?}",
        out.lines.last().unwrap().runs
    );
}

#[test]
fn a6b_spanless_measurement_emits_no_runs() {
    // Regression: the spanless fast path is untouched (empty runs).
    let measurer = SkiaTextMeasurer::bundled();
    let out = measurer.measure(&input("plain text"));
    assert!(out.lines.iter().all(|l| l.runs.is_empty()));
}

fn input(content: &str) -> TextMeasureInput {
    TextMeasureInput {
        node_id: None,
        font_size_override: None,
        content: content.to_owned(),
        font_family: "Inter".to_owned(),
        font_size: 20.0,
        font_weight: 400,
        italic: false,
        line_height: 1.5,
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
fn max_lines_truncates_without_ellipsis_by_default_and_with_ellipsis_when_truncate() {
    // A6a D3: the pinned truncation-without-ellipsis contract holds OFF by
    // default; setting `truncate` flips it to SkParagraph's native "…" on the
    // last kept line. `exceeds_max_lines` stays truthful either way (truncation
    // is still lossy and still diagnosed — it just looks intentional now).
    let measurer = SkiaTextMeasurer::bundled();
    let mut request = input("alpha\\nbeta\\ngamma");
    request.max_lines = Some(2);

    // Default: no ellipsis.
    let output = measurer.measure(&request);
    assert_eq!(output.line_count, 2);
    assert_eq!(line_texts(&output), vec!["alpha", "beta"]);
    assert!(output.exceeds_max_lines);
    assert!(
        !output.lines.iter().any(|line| line.text.contains('…')),
        "ellipsis is off by default"
    );

    // truncate on: the last kept line gains "…", still flagged as exceeding.
    request.truncate = true;
    let truncated = measurer.measure(&request);
    assert_eq!(truncated.line_count, 2);
    assert!(truncated.exceeds_max_lines);
    assert!(
        truncated.lines.iter().any(|line| line.text.contains('…')),
        "truncate must append the ellipsis: {:?}",
        line_texts(&truncated)
    );

    // Nothing to cut → no ellipsis even with truncate on.
    request.max_lines = Some(3);
    let uncut = measurer.measure(&request);
    assert!(!uncut.exceeds_max_lines);
    assert!(!uncut.lines.iter().any(|line| line.text.contains('…')));
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

// A6a review gate: the ellipsized line text the measurer emits (consumed by
// SVG/PDF markup) must fit the width bound — matching the raster's native
// elision — never the full overflowing text with a "…" tacked on.

#[test]
fn truncated_line_text_is_refitted_to_the_width_bound() {
    let measurer = SkiaTextMeasurer::bundled();

    // NoWrap single-line overflow elide.
    let mut nowrap = input("wide open spaces keep going");
    nowrap.truncate = true;
    nowrap.max_width = Some(100.0);
    let out = measurer.measure(&nowrap);
    let last = out.lines.last().expect("line");
    assert!(last.text.ends_with('…'), "elided line: {:?}", last.text);
    assert!(
        last.width <= 100.0 + 0.5,
        "emitted line width {} must fit the 100px bound (text {:?})",
        last.width,
        last.text
    );
    assert!(
        last.text.chars().count()
            < "wide open spaces keep going".chars().count() + 1,
        "characters must be dropped to make room for the ellipsis: {:?}",
        last.text
    );

    // Wrap + max_lines cut: the last kept line is full-width; adding "…"
    // must drop characters, not overflow the bound.
    let mut wrapped = input("wide open spaces keep going onward forever");
    wrapped.wrap = TextWrap::Wrap;
    wrapped.truncate = true;
    wrapped.max_lines = Some(1);
    wrapped.max_width = Some(120.0);
    let out = measurer.measure(&wrapped);
    let last = out.lines.last().expect("line");
    assert!(last.text.ends_with('…'), "cut line: {:?}", last.text);
    assert!(
        last.width <= 120.0 + 0.5,
        "emitted line width {} must fit the 120px bound (text {:?})",
        last.width,
        last.text
    );
}

// --- A7b: italic is a second measured-geometry channel (D3) ---------------

/// A measurer over the bundled set PLUS Instrument Serif upright + italic
/// (both weight 400, same family) so italic requests reach a real italic face.
fn instrument_measurer() -> SkiaTextMeasurer {
    use std::sync::Arc;
    let dir =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let upright = std::fs::read(dir.join("instrument-serif-regular.ttf"))
        .expect("instrument-serif-regular fixture reads");
    let italic = std::fs::read(dir.join("instrument-serif-italic.ttf"))
        .expect("instrument-serif-italic fixture reads");
    let (fonts, errors) = lumen_skia::FontManager::bundled_with(vec![
        (upright, None),
        (italic, None),
    ]);
    assert!(errors.is_empty(), "{errors:?}");
    SkiaTextMeasurer::new(Arc::new(fonts))
}

fn instrument_input(content: &str, italic: bool) -> TextMeasureInput {
    TextMeasureInput {
        font_family: "Instrument Serif".to_owned(),
        italic,
        ..input(content)
    }
}

#[test]
fn block_italic_changes_measured_width() {
    // With a real italic face loaded, the italic face's glyph advances differ
    // from the upright's, so the SAME content measures a different width — the
    // property that makes italic a measurement input (unlike the decorations).
    let measurer = instrument_measurer();
    let content = "The quick brown fox jumps over the lazy dog";
    let upright = measurer.measure(&instrument_input(content, false));
    let italic = measurer.measure(&instrument_input(content, true));
    assert!(
        (upright.width - italic.width).abs() > 0.5,
        "italic must change measured width: upright {} vs italic {}",
        upright.width,
        italic.width
    );
}

#[test]
fn measure_key_changes_when_block_italic_flips() {
    use lumen_core::measure_key;
    let upright = instrument_input("emphasis", false);
    let italic = instrument_input("emphasis", true);
    assert_ne!(
        measure_key(&upright),
        measure_key(&italic),
        "flipping block italic must re-key the measurement (stale-geometry guard)"
    );
}

#[test]
fn measure_key_spans_digest_includes_span_italic() {
    use lumen_core::measure_key;
    // Two inputs identical except a span's italic channel — the spans digest
    // (and thus measure_key) must differ, or an italic span would reuse a
    // stale upright measurement.
    let plain = spanned_input("word", vec![plain_span(0, 4)]);
    let italic_span = spanned_input(
        "word",
        vec![TextSpan {
            italic: Some(true),
            ..plain_span(0, 4)
        }],
    );
    assert_ne!(
        measure_key(&plain),
        measure_key(&italic_span),
        "span italic must enter spans_digest / measure_key"
    );
}

#[test]
fn italic_request_with_no_italic_face_emits_lums0105() {
    // Bundled Inter has no italic face. Requesting italic snaps to the upright
    // (no synthetic slant) and the measurer emits the LUMS0105 advisory.
    let measurer = SkiaTextMeasurer::bundled();
    let mut italic_input = input("no italics here");
    italic_input.italic = true;
    let out = measurer.measure(&italic_input);
    let advisory = out
        .diagnostics
        .iter()
        .find(|d| d.code == "LUMS0105")
        .unwrap_or_else(|| panic!("expected LUMS0105: {:?}", out.diagnostics));
    assert!(advisory.message.contains("Inter"));
    assert!(advisory.message.contains("italic"));

    // Upright request against the same family emits no italic advisory.
    let upright = measurer.measure(&input("no italics here"));
    assert!(!upright.diagnostics.iter().any(|d| d.code == "LUMS0105"));
}

#[test]
fn italic_request_with_italic_face_emits_no_lums0105() {
    // When the family DOES have an italic face, requesting italic is clean.
    let measurer = instrument_measurer();
    let out = measurer.measure(&instrument_input("clean italics", true));
    assert!(
        !out.diagnostics.iter().any(|d| d.code == "LUMS0105"),
        "no advisory when the italic face exists: {:?}",
        out.diagnostics
    );
}
