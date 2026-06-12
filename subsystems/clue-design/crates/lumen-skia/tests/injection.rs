//! Slice A2 gate: measurement injection is live end to end — layout engine,
//! preflight, and SVG export consume the Skia measurer through
//! `LayoutOptions`/`PreflightOptions`/adapter builders, while `None` keeps
//! the heuristic fallback bit-identical.

use lumen_core::{
    layout_scene, preflight_scene, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, LayoutOptions, Node, NodeId, NodeKind, Operation, Orientation,
    Page, PageId, PagePreset, PageSize, ParentRef, PreflightOptions, Scene, SharedTextMeasurer,
    SizeSpec, TextNode, TextWrap, Unit,
};
use lumen_export::SvgExportAdapter;
use lumen_skia::SkiaTextMeasurer;
use std::sync::Arc;

// Heuristic width estimate ~254.6px (fits 260px); real Inter shaping is
// ~375px wide, so the Skia measurer wraps it to a second 30px line that
// overflows the 40px box. The divergence makes injection observable.
const WIDE_TEXT: &str = "WWWWWWWWWW WWWWWWWWWW";
const BOX_WIDTH: f64 = 260.0;

fn has_code(diagnostics: &[lumen_core::Diagnostic], code: &str) -> bool {
    diagnostics.iter().any(|diagnostic| diagnostic.code == code)
}

fn skia_measurer() -> SharedTextMeasurer {
    Arc::new(SkiaTextMeasurer::bundled())
}

fn text_scene(width: f64) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_injection"), "Injection");
    let mut text_node = Node::new(
        NodeId::from("node_text"),
        NodeKind::Text(TextNode {
            content: WIDE_TEXT.to_owned(),
            wrap: TextWrap::Wrap,
            font_size: 20.0,
            line_height: 1.5,
            ..TextNode::default()
        }),
    );
    text_node.size = SizeSpec::fixed(width, 40.0);
    scene
        .apply_operations([
            Operation::AddPage {
                page: Page {
                    id: PageId::from("page_main"),
                    name: "Main".to_owned(),
                    size: PageSize {
                        width: 400.0,
                        height: 300.0,
                        unit: Unit::Px,
                        preset: Some(PagePreset::Custom),
                        orientation: Orientation::Landscape,
                    },
                    children: Vec::new(),
                    bleed: None,
                    safe_area: None,
                    background: Vec::new(),
                },
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_main")),
                index: 0,
                node: text_node,
            },
        ])
        .expect("scene builds");
    scene
}

#[test]
fn layout_scene_uses_injected_measurer_for_text_validation() {
    let scene = text_scene(BOX_WIDTH);

    let heuristic_result = layout_scene(&scene, LayoutOptions::default());
    let skia_result = layout_scene(
        &scene,
        LayoutOptions {
            measurer: Some(skia_measurer()),
            ..Default::default()
        },
    );

    // The heuristic believes the wide-glyph text fits one 30px line in the
    // 260x40 box; real shaping wraps to two lines (60px) and must surface
    // the height-overflow error LUMV0903.
    assert!(
        !has_code(&heuristic_result.diagnostics, "LUMV0903"),
        "heuristic baseline sees no overflow: {:?}",
        heuristic_result.diagnostics
    );
    assert!(
        has_code(&skia_result.diagnostics, "LUMV0903"),
        "Skia measurement must catch the wrap-induced overflow: {:?}",
        skia_result.diagnostics
    );
}

#[test]
fn default_options_preserve_heuristic_behavior() {
    let scene = text_scene(BOX_WIDTH);
    let first = layout_scene(&scene, LayoutOptions::default());
    let second = layout_scene(&scene, LayoutOptions::default());
    assert_eq!(first, second);
    assert_eq!(
        first.geometry[&NodeId::from("node_text")]
            .layout_bounds
            .height,
        40.0,
        "fixed box geometry under heuristic fallback is unchanged"
    );
    assert!(!has_code(&first.diagnostics, "LUMV0903"));
}

#[test]
fn preflight_threads_the_measurer_through_layout() {
    let scene = text_scene(BOX_WIDTH);

    let heuristic = preflight_scene(scene.clone(), None, PreflightOptions::default());
    assert!(
        !has_code(&heuristic.diagnostics, "LUMV0903"),
        "heuristic preflight baseline: {:?}",
        heuristic.diagnostics
    );

    let mut options = PreflightOptions::default();
    options.layout.measurer = Some(skia_measurer());
    let result = preflight_scene(scene, None, options);
    assert!(
        has_code(&result.diagnostics, "LUMV0903"),
        "preflight with the Skia measurer must catch the overflow: {:?}",
        result.diagnostics
    );

    // Geometry still lands on the scene for repair/preview flows.
    let node = result
        .scene
        .nodes
        .get(&NodeId::from("node_text"))
        .expect("node");
    assert!(node.computed.is_some());
}

#[test]
fn svg_export_line_breaks_follow_injected_measurer() {
    let scene = text_scene(BOX_WIDTH);
    let request = ExportRequest {
        profile: ExportProfile {
            name: "svg_injection".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        },
        page_ids: vec![PageId::from("page_main")],
        purpose: ExportPurpose::AgentCritique,
    };

    let heuristic_svg = SvgExportAdapter::new()
        .export(&scene, &request)
        .expect("heuristic export");
    let heuristic_markup =
        String::from_utf8(heuristic_svg.artifacts[0].bytes.clone()).expect("utf8");
    assert_eq!(
        heuristic_markup.matches("<tspan").count(),
        1,
        "heuristic renders the wide text as a single line"
    );

    let skia_svg = SvgExportAdapter::new()
        .with_measurer(skia_measurer())
        .export(&scene, &request)
        .expect("skia export");
    let skia_markup = String::from_utf8(skia_svg.artifacts[0].bytes.clone()).expect("utf8");
    assert!(
        skia_markup.matches("<tspan").count() >= 2,
        "shaped export must wrap the wide text into multiple tspans"
    );
}
