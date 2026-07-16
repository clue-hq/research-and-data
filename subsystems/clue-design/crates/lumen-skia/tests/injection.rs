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
    text_scene_family(width, "Inter")
}

fn text_scene_family(width: f64, font_family: &str) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_injection"), "Injection");
    let mut text_node = Node::new(
        NodeId::from("node_text"),
        NodeKind::Text(TextNode {
            content: WIDE_TEXT.to_owned(),
            wrap: TextWrap::Wrap,
            font_size: 20.0,
            line_height: 1.5,
            font_family: font_family.to_owned(),
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
                        source: None,
                        output: None,
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
fn heuristic_layout_emits_lums0102_and_skia_does_not() {
    let scene = text_scene(BOX_WIDTH);

    // Non-shaping (heuristic) measurement is loud: LUMS0102 fires so the
    // approximate geometry is never silent.
    let heuristic = layout_scene(&scene, LayoutOptions::default());
    assert!(
        has_code(&heuristic.diagnostics, "LUMS0102"),
        "heuristic layout must warn LUMS0102: {:?}",
        heuristic.diagnostics
    );

    // The server injects a shaping measurer: ZERO LUMS0102 (the Task 2.4
    // regression invariant).
    let skia = layout_scene(
        &scene,
        LayoutOptions {
            measurer: Some(skia_measurer()),
            ..Default::default()
        },
    );
    assert!(
        !has_code(&skia.diagnostics, "LUMS0102"),
        "shaping layout must NOT warn LUMS0102: {:?}",
        skia.diagnostics
    );
}

#[test]
fn skia_measurement_surfaces_lums0100_from_layout() {
    // A missing font family must surface at layout/preflight (via measurement),
    // not only at export. The heuristic has no font set, so it cannot see it.
    let scene = text_scene_family(BOX_WIDTH, "Comic Sans MS");

    let heuristic = layout_scene(&scene, LayoutOptions::default());
    assert!(
        !has_code(&heuristic.diagnostics, "LUMS0100"),
        "heuristic cannot detect a missing font: {:?}",
        heuristic.diagnostics
    );

    let skia = layout_scene(
        &scene,
        LayoutOptions {
            measurer: Some(skia_measurer()),
            ..Default::default()
        },
    );
    assert!(
        has_code(&skia.diagnostics, "LUMS0100"),
        "Skia measurement must surface the whole-family fallback: {:?}",
        skia.diagnostics
    );
}

#[test]
fn svg_export_emits_lums0102_only_without_a_shaping_measurer() {
    let scene = text_scene(BOX_WIDTH);
    let request = ExportRequest {
        profile: ExportProfile {
            name: "svg_lums0102".to_owned(),
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
        page_ids: vec![PageId::from("page_main")],
        purpose: ExportPurpose::AgentCritique,
    };

    let heuristic = SvgExportAdapter::new()
        .export(&scene, &request)
        .expect("heuristic export");
    assert!(
        has_code(&heuristic.diagnostics, "LUMS0102"),
        "heuristic SVG export must warn LUMS0102: {:?}",
        heuristic.diagnostics
    );

    let skia = SvgExportAdapter::new()
        .with_measurer(skia_measurer())
        .export(&scene, &request)
        .expect("skia export");
    assert!(
        !has_code(&skia.diagnostics, "LUMS0102"),
        "shaping SVG export must NOT warn LUMS0102: {:?}",
        skia.diagnostics
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
        include_marks: false,
        imposition: None,
        proof: false,
        color: None,
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

// A6a gate (K-A6 protocol finding): a hug-height text box with
// paragraph_spacing must RESERVE the paragraph gaps — hug sizing and the
// overflow_y check must count the same stacked height, else every hugged
// multi-stanza body trips a false LUMV0903.
#[test]
fn hug_height_reserves_paragraph_spacing_gaps() {
    let mut scene = Scene::new(DocumentId::from("doc_hug_para"), "Hug Para");
    let mut text_node = Node::new(
        NodeId::from("node_text"),
        NodeKind::Text(TextNode {
            content: "A.\\nB.\\nC.".to_owned(),
            wrap: TextWrap::Wrap,
            font_size: 20.0,
            line_height: 1.35,
            paragraph_spacing: 16.0,
            max_lines: Some(6),
            ..TextNode::default()
        }),
    );
    text_node.size = SizeSpec {
        width: lumen_core::Dimension::Fixed(400.0),
        height: lumen_core::Dimension::Hug,
    };
    scene
        .apply_operations([
            Operation::AddPage {
                page: Page {
                    id: PageId::from("page_main"),
                    name: "Main".to_owned(),
                    size: PageSize {
                        width: 800.0,
                        height: 600.0,
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
                },
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_main")),
                index: 0,
                node: text_node,
            },
        ])
        .expect("scene builds");

    for (label, options) in [
        ("heuristic", LayoutOptions::default()),
        (
            "skia",
            LayoutOptions {
                measurer: Some(skia_measurer()),
                ..Default::default()
            },
        ),
    ] {
        let result = layout_scene(&scene, options);
        assert!(
            !has_code(&result.diagnostics, "LUMV0903"),
            "{label}: hug height must include the paragraph gaps, got: {:?}",
            result
                .diagnostics
                .iter()
                .filter(|d| d.code.starts_with("LUMV09"))
                .collect::<Vec<_>>()
        );
    }
}

// K-A6 evidence repro, verbatim DSL: hugged para_spacing body inside an
// auto-layout stack must not trip a false LUMV0903.
#[test]
fn hugged_para_spacing_body_inside_autolayout_preflights_clean() {
    let dsl = r#"page linkedin_square size(1080,1080,px)
  artboard al(v,x(s),y(s),g(24),pad(96)) p(0,0) s(fill,fill) fill(#f4f1ea) clip(true)
    body text "Northwind watches ten thousand substations.\nCrews reach the fault in seconds, not hours.\nThe grid stays up." p(0,0) s(760,hug) font("Inter",22,400,left) fill(#374151) lh(1.35) para_spacing(16) wrap_text(true) max_lines(6)
"#;
    let mut scene = Scene::new(DocumentId::from("doc_k_repro"), "K Repro");
    let compile = lumen_core::compile_dsl_into_scene(dsl, &mut scene);
    assert!(
        compile
            .compile_output
            .diagnostics
            .iter()
            .all(|d| d.diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "compiles: {:?}",
        compile.compile_output.diagnostics
    );
    let mut options = PreflightOptions::default();
    options.layout.measurer = Some(skia_measurer());
    let result = preflight_scene(scene, None, options);
    let errors: Vec<_> = result
        .diagnostics
        .iter()
        .filter(|d| d.code.starts_with("LUMV09"))
        .collect();
    assert!(
        !has_code(&result.diagnostics, "LUMV0903"),
        "hug must reserve paragraph gaps: {errors:?}"
    );
}

