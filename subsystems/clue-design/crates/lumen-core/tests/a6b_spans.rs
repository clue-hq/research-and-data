//! A6b rich-text spans — engine slice (D1-D8).
//!
//! Covers the DSL `[[…]]` + `span()` grammar, D3 validation, D5 stateful
//! case transform across span boundaries, D6 heuristic run geometry, serde
//! defaults, and D7 render-contract detection. Skia measurement/rendering and
//! SVG/PDF markup are pinned in the lumen-skia / lumen-export suites.

use lumen_core::{
    compile_dsl_into_scene, effect_features_for_node, normalize_content_mapped,
    span_validation_errors, transform_segments, Color, DocumentId, EffectFeature,
    EffectSupportLevel, HeuristicTextMeasurer, NodeKind, Paint, RenderTarget,
    RendererEffectSupport, Scene, TextMeasureInput, TextMeasurer, TextNode, TextSpan,
    TextTransform,
};

fn compile(source: &str) -> (Scene, Vec<lumen_core::DslDiagnostic>) {
    let mut scene = Scene::new(DocumentId::from("doc_spans"), "spans");
    let output = compile_dsl_into_scene(source, &mut scene);
    (scene, output.compile_output.diagnostics)
}

fn only_text(scene: &Scene) -> &TextNode {
    scene
        .nodes
        .values()
        .find_map(|node| match &node.kind {
            NodeKind::Text(text) => Some(text),
            _ => None,
        })
        .expect("scene has a text node")
}

fn codes(diagnostics: &[lumen_core::DslDiagnostic]) -> Vec<String> {
    diagnostics
        .iter()
        .map(|d| d.diagnostic.code.clone())
        .collect()
}

// --- D2: markers + span() grammar ---

#[test]
fn dsl_markers_with_span_strip_and_bind() {
    let (scene, diagnostics) = compile(
        "page p preset(a4,portrait)\n  head t(\"Every [[outage]], mapped.\") span(fill(#ff0000))\n",
    );
    assert!(
        !diagnostics.iter().any(|d| d.diagnostic.code == "LUMD0272"),
        "{:?}",
        codes(&diagnostics)
    );
    let text = only_text(&scene);
    // Markers stripped from stored content.
    assert_eq!(text.content, "Every outage, mapped.");
    assert_eq!(text.spans.len(), 1);
    let span = &text.spans[0];
    // "Every " is 6 bytes; "outage" is 6 → [6,12).
    assert_eq!((span.start, span.end), (6, 12));
    assert_eq!(&text.content[span.start..span.end], "outage");
    assert!(matches!(
        span.fill,
        Some(Paint::Solid {
            color: Color::Hex { .. }
        })
    ));
}

#[test]
fn dsl_markers_without_span_are_literal() {
    // No span() property ⇒ [[ stays literal content (existing scenes safe).
    let (scene, _) = compile("page p preset(a4,portrait)\n  head t(\"Every [[outage]].\")\n");
    let text = only_text(&scene);
    assert_eq!(text.content, "Every [[outage]].");
    assert!(text.spans.is_empty());
}

#[test]
fn dsl_unclosed_marker_errors() {
    let (_, diagnostics) =
        compile("page p preset(a4,portrait)\n  head t(\"Every [[outage.\") span(weight(700))\n");
    assert!(codes(&diagnostics).contains(&"LUMD0272".to_owned()));
}

#[test]
fn dsl_nested_marker_errors() {
    let (_, diagnostics) = compile(
        "page p preset(a4,portrait)\n  head t(\"[[a [[b]] c]]\") span(weight(700)) span(weight(400))\n",
    );
    assert!(codes(&diagnostics).contains(&"LUMD0272".to_owned()));
}

#[test]
fn dsl_count_mismatch_warns_and_styles_available_runs() {
    // Two runs, one span() → LUMD0274 warning; the first run is styled, the
    // second renders base.
    let (scene, diagnostics) = compile(
        "page p preset(a4,portrait)\n  head t(\"[[one]] and [[two]]\") span(weight(700))\n",
    );
    assert!(codes(&diagnostics).contains(&"LUMD0274".to_owned()));
    let text = only_text(&scene);
    assert_eq!(text.content, "one and two");
    assert_eq!(text.spans.len(), 1);
    assert_eq!((text.spans[0].start, text.spans[0].end), (0, 3));
    assert_eq!(text.spans[0].font_weight, Some(700));
}

#[test]
fn dsl_empty_span_errors() {
    let (_, diagnostics) =
        compile("page p preset(a4,portrait)\n  head t(\"[[a]]\") span()\n");
    assert!(codes(&diagnostics).contains(&"LUMD0273".to_owned()));
}

#[test]
fn dsl_unknown_span_channel_errors() {
    // A7b: `italic` is now a real span channel, so the bogus-channel probe uses
    // a name with no parse arm (verified: no `oblique` arm exists).
    let (_, diagnostics) =
        compile("page p preset(a4,portrait)\n  head t(\"[[a]]\") span(oblique(true))\n");
    assert!(codes(&diagnostics).contains(&"LUMD0212".to_owned()));
}

#[test]
fn dsl_span_italic_channel_lowers_to_span_override() {
    // A7b positive twin: span(italic(true)) is a valid channel that lowers to
    // TextSpan.italic = Some(true) (override merge, resolved at measure/paint).
    let (scene, diagnostics) =
        compile("page p preset(a4,portrait)\n  head t(\"[[stressed]] plain\") span(italic(true))\n");
    assert!(
        !codes(&diagnostics).contains(&"LUMD0212".to_owned()),
        "italic is a valid span channel: {diagnostics:?}"
    );
    let text = only_text(&scene);
    assert_eq!(text.spans.len(), 1);
    assert_eq!(text.spans[0].italic, Some(true));

    // italic(false) de-italicizes a run (override, not union) — also valid.
    let (scene, _) =
        compile("page p preset(a4,portrait)\n  head t(\"[[plain]] rest\") span(italic(false))\n");
    assert_eq!(only_text(&scene).spans[0].italic, Some(false));
}

#[test]
fn dsl_span_token_fill_and_weight() {
    let (scene, _) = compile(
        "page p preset(a4,portrait)\n  head t(\"[[bold]] plain\") span(fill($color.accent))\n  head2 t(\"[[heavy]]\") span(weight(800))\n",
    );
    // First text node: token fill.
    let token_fill = scene
        .nodes
        .values()
        .filter_map(|n| match &n.kind {
            NodeKind::Text(t) if !t.spans.is_empty() => Some(t),
            _ => None,
        })
        .find(|t| matches!(t.spans[0].fill, Some(Paint::Token { .. })))
        .expect("a token-fill span exists");
    assert!(matches!(token_fill.spans[0].fill, Some(Paint::Token { .. })));
}

// --- D3: validation (ops can inject what the DSL cannot) ---

fn span(start: usize, end: usize) -> TextSpan {
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
fn d3_out_of_bounds_is_an_error() {
    let errors = span_validation_errors("hello", &[span(2, 99)]);
    assert!(!errors.is_empty());
    assert!(errors[0].reason.contains("out of bounds"));
}

#[test]
fn d3_start_not_before_end_is_an_error() {
    assert!(!span_validation_errors("hello", &[span(3, 3)]).is_empty());
    assert!(!span_validation_errors("hello", &[span(4, 2)]).is_empty());
}

#[test]
fn d3_overlap_or_unsorted_is_an_error() {
    // Overlapping.
    assert!(!span_validation_errors("hello world", &[span(0, 6), span(3, 9)]).is_empty());
    // Unsorted.
    assert!(!span_validation_errors("hello world", &[span(6, 9), span(0, 3)]).is_empty());
}

#[test]
fn d3_non_char_boundary_is_an_error() {
    // "café" — the 'é' is 2 bytes at [3,5); byte 4 is mid-char.
    let errors = span_validation_errors("café", &[span(0, 4)]);
    assert!(errors.iter().any(|e| e.reason.contains("char boundary")));
}

#[test]
fn d3_gradient_span_fill_is_rejected() {
    let gradient = TextSpan {
        start: 0,
        end: 3,
        fill: Some(Paint::LinearGradient {
            angle: 0.0,
            stops: Vec::new(),
        }),
        font_weight: None,
        underline: None,
        strikethrough: None,
        italic: None,
    };
    let errors = span_validation_errors("hello", &[gradient]);
    assert!(errors.iter().any(|e| e.reason.contains("gradient")));
}

#[test]
fn d3_valid_spans_pass_clean() {
    assert!(span_validation_errors("hello world", &[span(0, 5), span(6, 11)]).is_empty());
    assert!(span_validation_errors("hello", &[]).is_empty());
}

// --- D5: case transform across span boundaries ---

#[test]
fn d5_title_case_carries_word_start_across_span_boundary() {
    // "sunshine" with a span mid-word [3,8) ("shine"). Title-case must NOT
    // re-capitalize at the span boundary — the word started before it.
    let segments = transform_segments("sunshine", &[(3, 8)], TextTransform::Title);
    let joined: String = segments.iter().map(|s| s.text.clone()).collect();
    assert_eq!(joined, "Sunshine");
    // The span segment ("shine") is lowercase — no phantom capital.
    let span_seg = segments
        .iter()
        .find(|s| s.span == Some(0))
        .expect("span segment");
    assert_eq!(span_seg.text, "shine");
}

#[test]
fn d5_uppercase_and_lowercase_are_per_segment() {
    let upper = transform_segments("héllo world", &[(0, 6)], TextTransform::Uppercase);
    let joined: String = upper.iter().map(|s| s.text.clone()).collect();
    assert_eq!(joined, "HÉLLO WORLD");
}

#[test]
fn normalize_map_relocates_offsets_across_newline_and_trims() {
    // Literal "\n" (2 bytes) collapses to one; a trailing newline is trimmed.
    let (normalized, map) = normalize_content_mapped("a\\nbc\\n");
    assert_eq!(normalized, "a\nbc");
    // Raw offset of 'b' (after "a\n" = 3 raw bytes) maps to normalized 2.
    assert_eq!(map[3], 2);
}

// --- D6: heuristic run geometry (sanity) ---

fn spanned_node(content: &str, spans: Vec<TextSpan>) -> TextNode {
    TextNode {
        content: content.to_owned(),
        font_size: 20.0,
        spans,
        ..TextNode::default()
    }
}

#[test]
fn d6_heuristic_runs_are_ordered_and_cover_the_line() {
    let node = spanned_node("Every outage now", vec![span(6, 12)]);
    let out = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&node));
    let line = &out.lines[0];
    assert!(line.runs.len() >= 2, "expected base+span runs: {:?}", line.runs);
    // Runs laid left-to-right with non-negative widths.
    let mut last_x = -1.0;
    for run in &line.runs {
        assert!(run.x >= last_x, "runs must be ordered by x: {:?}", line.runs);
        assert!(run.width > 0.0);
        last_x = run.x;
    }
    // Exactly one run tagged with the span.
    assert_eq!(line.runs.iter().filter(|r| r.span == Some(0)).count(), 1);
    // Concatenated run text reproduces the line text.
    let joined: String = line.runs.iter().map(|r| r.text.clone()).collect();
    assert_eq!(joined, line.text);
}

#[test]
fn d6_heuristic_ellipsis_lands_on_last_run() {
    let mut node = spanned_node("[[a]]", vec![span(0, 1)]);
    node.content = "one two three".to_owned();
    node.spans = vec![span(0, 3)];
    node.max_lines = Some(1);
    node.truncate = true;
    // Force multi-line via hard breaks so max_lines cuts.
    node.content = "one\ntwo\nthree".to_owned();
    node.spans = vec![span(0, 3)];
    let out = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&node));
    assert_eq!(out.line_count, 1);
    let last_run = out.lines[0].runs.last().expect("a run");
    assert!(
        last_run.text.ends_with('…'),
        "ellipsis on last run: {:?}",
        out.lines[0].runs
    );
}

#[test]
fn d6_spanless_measurement_has_no_runs() {
    // The pre-A6b fast path emits empty runs, so it stays byte-identical.
    let node = TextNode {
        content: "plain".to_owned(),
        ..TextNode::default()
    };
    let out = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&node));
    assert!(out.lines.iter().all(|l| l.runs.is_empty()));
}

// --- D1 serde: default-empty, skip-if-empty ---

#[test]
fn spans_default_empty_and_are_skipped_when_serialized() {
    let value = serde_json::to_value(TextNode::default()).unwrap();
    assert!(!value.as_object().unwrap().contains_key("spans"));

    let json = r#"{"content":"x","font_family":"Inter","font_size":16.0,"font_weight":400,"align":"left"}"#;
    let node: TextNode = serde_json::from_str(json).unwrap();
    assert!(node.spans.is_empty());
}

#[test]
fn span_serde_roundtrips_and_skips_none_channels() {
    let node = spanned_node(
        "hello",
        vec![TextSpan {
            start: 0,
            end: 3,
            fill: None,
            font_weight: Some(700),
            underline: None,
            strikethrough: None,
            italic: None,
        }],
    );
    let value = serde_json::to_value(&node).unwrap();
    let span_json = &value["spans"][0];
    assert!(span_json.as_object().unwrap().contains_key("font_weight"));
    assert!(!span_json.as_object().unwrap().contains_key("fill"));
    assert!(!span_json.as_object().unwrap().contains_key("underline"));
    let round: TextNode = serde_json::from_value(value).unwrap();
    assert_eq!(round.spans, node.spans);
}

// --- D7: render-contract detection ---

#[test]
fn d7_contract_detects_rich_text_spans() {
    let mut node = lumen_core::Node::new(
        lumen_core::NodeId::from("t"),
        NodeKind::Text(spanned_node("hi there", vec![span(0, 2)])),
    );
    node.size = lumen_core::SizeSpec::fixed(100.0, 40.0);
    let features = effect_features_for_node(&node);
    assert!(features.contains(&EffectFeature::RichTextSpans));

    // SVG + PNG native; PDF + Konva unsupported.
    assert_eq!(
        RendererEffectSupport::level(&RenderTarget::Svg, EffectFeature::RichTextSpans),
        EffectSupportLevel::Native
    );
    assert_eq!(
        RendererEffectSupport::level(&RenderTarget::Png { scale: 1.0 }, EffectFeature::RichTextSpans),
        EffectSupportLevel::Native
    );
    assert_eq!(
        RendererEffectSupport::level(&RenderTarget::Pdf, EffectFeature::RichTextSpans),
        EffectSupportLevel::Unsupported
    );
    assert_eq!(
        RendererEffectSupport::level(&RenderTarget::KonvaScene, EffectFeature::RichTextSpans),
        EffectSupportLevel::Unsupported
    );
}

#[test]
fn d7_spanless_text_node_reports_no_span_feature() {
    let node = lumen_core::Node::new(
        lumen_core::NodeId::from("t"),
        NodeKind::Text(TextNode {
            content: "plain".to_owned(),
            ..TextNode::default()
        }),
    );
    assert!(!effect_features_for_node(&node).contains(&EffectFeature::RichTextSpans));
}
