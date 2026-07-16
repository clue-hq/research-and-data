//! A6b D7/D8: SVG per-run tspans + token-resolved span fills. SVG export uses
//! the deterministic heuristic measurer, so run x/width are exact and pinnable.

use lumen_core::scene::TextNode;
use lumen_core::{
    estimate_text_width, Color, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Operation, Orientation, Page,
    PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Scene, SizeSpec, TextAlign, TextSpan,
    Unit, VerticalAlign,
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
        include_marks: false,
        imposition: None,
        proof: false,
        color: None,
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
        italic: None,
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
            italic: None,
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
fn block_italic_emits_font_style_on_the_text_element() {
    // A7b D6: block-level italic surfaces as font-style="italic" on <text>.
    let text = TextNode {
        content: "editorial".to_owned(),
        font_size: 20.0,
        italic: true,
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, 600.0, TextAlign::Left));
    assert!(
        svg.contains("font-style=\"italic\""),
        "block italic must emit font-style on <text>: {svg}"
    );
}

#[test]
fn italic_span_emits_font_style_only_on_the_run() {
    // A7b D6: an italic span in an upright block emits font-style="italic" on
    // its run (override merge). The block <text> carries no font-style.
    let text = TextNode {
        content: "plain fancy".to_owned(),
        font_size: 20.0,
        spans: vec![TextSpan {
            start: 6,
            end: 11,
            fill: None,
            font_weight: None,
            underline: None,
            strikethrough: None,
            italic: Some(true),
        }],
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, 600.0, TextAlign::Left));
    assert!(
        svg.contains("font-style=\"italic\""),
        "italic span must emit run font-style: {svg}"
    );
    // Exactly one font-style occurrence (the run), not the block <text>.
    assert_eq!(
        svg.matches("font-style=").count(),
        1,
        "only the italic run carries font-style, not the block: {svg}"
    );
}

#[test]
fn de_italicizing_span_in_italic_block_emits_font_style_normal() {
    // A7b D6: override merge — an italic(false) span inside an italic block
    // de-italicizes its run, emitting font-style="normal"; the block <text>
    // still carries font-style="italic".
    let text = TextNode {
        content: "all but one".to_owned(),
        font_size: 20.0,
        italic: true,
        spans: vec![TextSpan {
            start: 8,
            end: 11,
            fill: None,
            font_weight: None,
            underline: None,
            strikethrough: None,
            italic: Some(false),
        }],
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, 600.0, TextAlign::Left));
    assert!(
        svg.contains("font-style=\"italic\""),
        "block italic stays on <text>: {svg}"
    );
    assert!(
        svg.contains("font-style=\"normal\""),
        "de-italicized run emits font-style=normal: {svg}"
    );
}

#[test]
fn upright_text_emits_no_font_style_attr() {
    // Byte-identical guard: nothing italic ⇒ no font-style attr anywhere
    // (pre-A7b markup unchanged).
    let text = TextNode {
        content: "plain fancy".to_owned(),
        font_size: 20.0,
        spans: vec![accent(6, 11, None, Some(700))],
        ..TextNode::default()
    };
    let (svg, _) = render(text_node("t", text, 600.0, TextAlign::Left));
    assert!(
        !svg.contains("font-style"),
        "no italic anywhere ⇒ no font-style attr: {svg}"
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

/// Extract the `y` of the first `<tspan>` in the markup.
fn first_tspan_y(svg: &str) -> f64 {
    let tspan = svg.split("<tspan").nth(1).expect("a tspan");
    let after = tspan.split("y=\"").nth(1).expect("y attr");
    let value = after.split('"').next().expect("y value");
    value.parse().expect("y is numeric")
}

#[test]
fn valign_shifts_baseline_by_clamped_slack_on_a_fixed_height_box() {
    // A7a D3: the single-line node lives in a 60px-high Fixed box. `center`
    // shifts the baseline down by exactly half the vertical slack, `bottom` by
    // the full slack, and `top` leaves it unchanged. Deterministic heuristic
    // measurer ⇒ the ratio is exact.
    let node = |valign: VerticalAlign| {
        text_node(
            "t",
            TextNode {
                content: "one line".to_owned(),
                font_size: 20.0,
                valign,
                ..TextNode::default()
            },
            600.0,
            TextAlign::Left,
        )
    };
    let (top_svg, _) = render(node(VerticalAlign::Top));
    let (center_svg, _) = render(node(VerticalAlign::Center));
    let (bottom_svg, _) = render(node(VerticalAlign::Bottom));
    let top = first_tspan_y(&top_svg);
    let center = first_tspan_y(&center_svg);
    let bottom = first_tspan_y(&bottom_svg);

    assert!(center > top, "center baseline must sit below top: {top} vs {center}");
    assert!(bottom > center, "bottom baseline must sit below center: {center} vs {bottom}");
    // center offset is exactly half the bottom offset (both from the same slack).
    assert!(
        ((center - top) * 2.0 - (bottom - top)).abs() < 0.001,
        "center shift must be half the bottom shift: top={top} center={center} bottom={bottom}"
    );
}
