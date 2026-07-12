//! Print W6 gates: the print-ready-v1 ruleset (chain link L4).

use lumen_core::{
    Color, ComputedGeometry, DocumentId, ExportFormat, ExportProfile, ExportPurpose, ExportRequest,
    Fill, Node, NodeId, NodeKind, Orientation, Page, PageId, PagePreset, PageSize, Paint, PaintId,
    PdfIntent, Rect, Scene, SizeSpec, TextAlign, TextNode, Transform, Unit,
};
use lumen_export::print_ready_report;

fn solid_fill(id: &str, value: &str) -> Fill {
    Fill {
        id: PaintId::from(id),
        paint: Paint::Solid {
            color: Color::Hex {
                value: value.to_owned(),
            },
        },
    }
}

fn print_request(include_bleed: bool) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "print_pdf".to_owned(),
            format: ExportFormat::Pdf,
            pdf_intent: Some(PdfIntent::Print),
            raster: None,
            include_bleed,
            embed_fonts: true,
            include_marks: false,
        imposition: None,
        },
        page_ids: vec![PageId::from("page_print")],
        purpose: ExportPurpose::UserDownload,
    }
}

fn rect_node(id: &str, x: f64, y: f64, width: f64, height: f64) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
    node.transform = Transform {
        x,
        y,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(width, height);
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x,
            y,
            width,
            height,
        },
        render_bounds: Rect {
            x,
            y,
            width,
            height,
        },
    });
    node.fills = vec![solid_fill(&format!("paint_{id}"), "#12355b")];
    node
}

fn text_node(id: &str, x: f64, y: f64, width: f64, height: f64) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Text(TextNode {
            content: "safe area probe".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 16.0,
            font_weight: 400,
            align: TextAlign::Left,
            ..TextNode::default()
        }),
    );
    node.transform = Transform {
        x,
        y,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(width, height);
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x,
            y,
            width,
            height,
        },
        render_bounds: Rect {
            x,
            y,
            width,
            height,
        },
    });
    node.fills = vec![solid_fill(&format!("paint_{id}"), "#111827")];
    node
}

/// 200×150pt page with optional bleed/safe rects and the given children.
fn print_scene(
    bleed: Option<Rect>,
    safe_area: Option<Rect>,
    nodes: Vec<Node>,
) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_print_ready"), "Print ready");
    scene.pages.insert(
        PageId::from("page_print"),
        Page {
            id: PageId::from("page_print"),
            name: "Print".to_owned(),
            size: PageSize {
                width: 200.0,
                height: 150.0,
                unit: Unit::Pt,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Landscape,
                source: None,
                output: None,
            },
            children: nodes.iter().map(|node| node.id.clone()).collect(),
            bleed,
            safe_area,
            background: vec![solid_fill("paint_page_bg", "#ffffff")],
        },
    );
    for node in nodes {
        scene.nodes.insert(node.id.clone(), node);
    }
    scene
}

fn bleed_rect() -> Rect {
    Rect {
        x: -9.0,
        y: -9.0,
        width: 218.0,
        height: 168.0,
    }
}

fn safe_rect() -> Rect {
    Rect {
        x: 14.0,
        y: 14.0,
        width: 172.0,
        height: 122.0,
    }
}

fn rule_status<'a>(report: &'a lumen_core::PrintReadyReport, id: &str) -> &'a str {
    &report
        .rules
        .iter()
        .find(|rule| rule.id == id)
        .unwrap_or_else(|| panic!("missing rule {id}"))
        .status
}

#[test]
fn missing_bleed_fails_when_requested_and_warns_otherwise() {
    let scene = print_scene(None, Some(safe_rect()), vec![]);
    let pages = vec![PageId::from("page_print")];

    let report = print_ready_report(&scene, &pages, &print_request(true), &[]);
    assert_eq!(rule_status(&report, "bleed_present"), "fail");
    assert!(report.failed());

    let report = print_ready_report(&scene, &pages, &print_request(false), &[]);
    assert_eq!(rule_status(&report, "bleed_present"), "warn");
    assert!(!report.failed());
}

#[test]
fn edge_touching_art_short_of_bleed_fails() {
    // Background wash covers exactly the trim — touches all four edges,
    // reaches the bleed line on none of them.
    let scene = print_scene(
        Some(bleed_rect()),
        Some(safe_rect()),
        vec![rect_node("node_wash", 0.0, 0.0, 200.0, 150.0)],
    );
    let pages = vec![PageId::from("page_print")];
    let report = print_ready_report(&scene, &pages, &print_request(true), &[]);
    assert_eq!(rule_status(&report, "edge_art_reaches_bleed"), "fail");
    assert!(report.failed());
    let detail = &report
        .rules
        .iter()
        .find(|rule| rule.id == "edge_art_reaches_bleed")
        .unwrap()
        .detail;
    assert!(detail.contains("node_wash"), "{detail}");
}

#[test]
fn full_bleed_wash_and_interior_art_pass() {
    let scene = print_scene(
        Some(bleed_rect()),
        Some(safe_rect()),
        vec![
            // Wash extends to the bleed line on every side.
            rect_node("node_wash", -9.0, -9.0, 218.0, 168.0),
            // Interior card nowhere near trim.
            rect_node("node_card", 40.0, 40.0, 80.0, 50.0),
            // Text inside the safe area.
            text_node("node_copy", 20.0, 20.0, 100.0, 30.0),
        ],
    );
    let pages = vec![PageId::from("page_print")];
    let report = print_ready_report(&scene, &pages, &print_request(true), &[]);
    assert_eq!(rule_status(&report, "edge_art_reaches_bleed"), "pass");
    assert_eq!(rule_status(&report, "text_in_safe_area"), "pass");
    assert_eq!(rule_status(&report, "bleed_present"), "pass");
    assert_eq!(report.status, "pass", "{report:#?}");
}

#[test]
fn text_outside_safe_area_warns() {
    let scene = print_scene(
        Some(bleed_rect()),
        Some(safe_rect()),
        vec![
            rect_node("node_wash", -9.0, -9.0, 218.0, 168.0),
            // Text at the very trim edge, outside the 14pt safe inset.
            text_node("node_edge_copy", 2.0, 2.0, 100.0, 30.0),
        ],
    );
    let pages = vec![PageId::from("page_print")];
    let report = print_ready_report(&scene, &pages, &print_request(true), &[]);
    assert_eq!(rule_status(&report, "text_in_safe_area"), "warn");
    assert_eq!(report.status, "warn");
}

#[test]
fn collected_diagnostics_fold_into_rules() {
    use lumen_core::{Diagnostic, Phase};
    let scene = print_scene(
        Some(bleed_rect()),
        Some(safe_rect()),
        vec![rect_node("node_wash", -9.0, -9.0, 218.0, 168.0)],
    );
    let pages = vec![PageId::from("page_print")];
    let collected = vec![
        Diagnostic::warning(Phase::Export, "LUMS0101", "font face unavailable", None),
        Diagnostic::warning(Phase::Export, "LUMX0002", "feature dropped", None),
        Diagnostic::warning(Phase::Export, "LUME0220", "low effective dpi", None),
    ];
    let report = print_ready_report(&scene, &pages, &print_request(true), &collected);
    assert_eq!(rule_status(&report, "fonts_resolved"), "warn");
    assert_eq!(rule_status(&report, "image_resolution"), "warn");
    assert_eq!(rule_status(&report, "no_feature_drops"), "fail");
    assert!(report.failed());
    // Fail rules sort first for readable reports.
    assert_eq!(report.rules[0].status, "fail");
}
