//! A6b D7/D8: SVG per-run tspans + token-resolved span fills. SVG export uses
//! the deterministic heuristic measurer, so run x/width are exact and pinnable.

use lumen_core::scene::TextNode;
use lumen_core::{
    estimate_text_width, Color, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Operation, Orientation, Page,
    PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Scene, SizeSpec, TextAlign, TextSpan,
    Unit,
};
use lumen_export::SvgExportAdapter;

/// Local copy of the exporter's number formatter so expected coordinates match
/// the emitted markup byte-for-byte.
fn fmt_num(value: f64) -> String {
    if value == 0.0 {
        return "0".to_owned();
    }
    let mut text = format!("{value:.4}");
    while text.contains('.') && text.ends_with('0') {
        text.pop();
    }
    if text.ends_with('.') {
        text.pop();
    }
    text
}

fn page() -> Page {
    Page {
        id: PageId::from("page_spans"),
        name: "Spans".to_owned(),
        size: PageSize {
            width: 600.0,
            height: 200.0,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Landscape,
            source: None,
            output: None,
        },
        children: Vec::new(),
        bleed: None,
        safe_area: None,
        background: Vec::new(),
    }
}

fn text_node(id: &str, mut text: TextNode, width: f64, align: TextAlign) -> Node {
    text.align = align;
    let mut node = Node::new(NodeId::from(id), NodeKind::Text(text));
    node.size = SizeSpec::fixed(width, 60.0);
    node.fills = vec![Fill {
        id: PaintId::from("text_fill"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#111111".to_owned(),
            },
        },
    }];
    node
}

fn render(node: Node) -> (String, Vec<lumen_core::Diagnostic>) {
    let mut scene = Scene::new(DocumentId::from("doc_spans_svg"), "Spans SVG");
    scene
        .apply_operations([
            Operation::AddPage { page: page() },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_spans")),
                index: 0,
                node,
            },
        ])
        .unwrap();
    let request = ExportRequest {
        profile: ExportProfile {
            name: "svg".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        },
        page_ids: vec![PageId::from("page_spans")],
        purpose: ExportPurpose::UserDownload,
    };
    let result = SvgExportAdapter::new().export(&scene, &request).expect("svg");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).unwrap();
    (svg, result.diagnostics)
}

fn accent(start: usize, end: usize, fill: Option<Paint>, weight: Option<u16>) -> TextSpan {
    TextSpan {
        start,
        end,
        fill,
        font_weight: weight,
        underline: None,
        strikethrough: None,
    }
}

#[test]
fn per_run_tspans_carry_fill_and_weight_and_start_anchor() {
    // "one two": accent "two" [4,7) in red + weight 800.
    let text = TextNode {
        content: "one two".to_owned(),
        font_size: 20.0,
        letter_spacing: 0.0,
        spans: vec![accent(
            4,
            7,
            Some(Paint::Solid {
                color: Color::Hex {
                    value: "#ff0000".to_owned(),
                },
            }),
            Some(800),
        )],
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, 600.0, TextAlign::Left));

    // A spanned node anchors at start (runs are absolutely positioned).
    assert!(svg.contains("text-anchor=\"start\""), "{svg}");
    // Two tspans; the accent run carries fill + weight, the base run does not.
    let tspan_count = svg.matches("<tspan").count();
    assert_eq!(tspan_count, 2, "one tspan per run: {svg}");
    assert!(svg.contains("fill=\"#ff0000\""), "accent fill: {svg}");
    assert!(svg.contains("font-weight=\"800\""), "accent weight: {svg}");
}

#[test]
fn center_alignment_places_runs_at_absolute_x_with_letter_spacing() {
    let font_size = 20.0;
    let letter_spacing = 3.0;
    let box_width = 600.0;
    let text = TextNode {
        content: "one two".to_owned(),
        font_size,
        letter_spacing,
        spans: vec![accent(4, 7, None, Some(700))],
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, box_width, TextAlign::Center));

    // Heuristic run widths (base "one ", accent "two").
    let base_w = estimate_text_width("one ", font_size, letter_spacing);
    let accent_w = estimate_text_width("two", font_size, letter_spacing);
    let line_width = base_w + accent_w;
    let line_left = (box_width - line_width) / 2.0;

    // Base run at line_left; accent run at line_left + base width.
    let base_x = fmt_num(line_left);
    let accent_x = fmt_num(line_left + base_w);
    assert!(
        svg.contains(&format!("<tspan x=\"{base_x}\"")),
        "base run x={base_x}: {svg}"
    );
    assert!(
        svg.contains(&format!("<tspan x=\"{accent_x}\"")),
        "accent run x={accent_x}: {svg}"
    );
}

#[test]
fn underline_span_emits_text_decoration_only_on_the_run() {
    let text = TextNode {
        content: "plain fancy".to_owned(),
        font_size: 20.0,
        spans: vec![TextSpan {
            start: 6,
            end: 11,
            fill: None,
            font_weight: None,
            underline: Some(true),
            strikethrough: None,
        }],
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, 600.0, TextAlign::Left));
    assert!(
        svg.contains("text-decoration=\"underline\""),
        "run decoration: {svg}"
    );
}

#[test]
fn spanless_text_keeps_single_tspan_and_alignment_anchor() {
    // Regression guard: no spans ⇒ pre-A6b markup (middle anchor, one tspan).
    let text = TextNode {
        content: "hello world".to_owned(),
        font_size: 20.0,
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, 600.0, TextAlign::Center));
    assert!(svg.contains("text-anchor=\"middle\""), "{svg}");
    assert_eq!(svg.matches("<tspan").count(), 1, "{svg}");
}
