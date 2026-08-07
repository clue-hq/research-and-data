//! Effects Contract V0, slice X7: full-document golden SVG fixtures for
//! the effects surface. Any change to stack rendering, stroke attributes,
//! or filter markup shows up as a byte diff against these files.
//!
//! Regenerate intentionally with:
//! `UPDATE_EFFECTS_GOLDENS=1 cargo test -p lumen-export --test effects_golden`

use lumen_core::scene::ColorStop;
use lumen_core::{
    Color, DocumentId, Effect, EffectId, EffectKind, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Operation, Orientation, Page,
    PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Scene, SizeSpec, Stroke, StrokeCap,
    StrokeJoin, Transform, Unit,
};
use lumen_export::SvgExportAdapter;
use std::path::PathBuf;

fn solid(value: &str) -> Paint {
    Paint::Solid {
        color: Color::Hex {
            value: value.to_owned(),
        },
    }
}

fn fill(id: &str, value: &str) -> Fill {
    Fill {
        id: PaintId::from(id),
        paint: solid(value),
    }
}

fn shadow(id: &str, y: f64, blur: f64, spread: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::DropShadow {
            color: Color::Hex {
                value: "#000000".to_owned(),
            },
            opacity: 0.18,
            x: 0.0,
            y,
            blur,
            spread,
            color_token: None,
        },
    }
}

fn card(id: &str) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
    node.transform = Transform {
        x: 24.0,
        y: 24.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(200.0, 120.0);
    node.corner = lumen_core::CornerRadii {
        top_left: 8.0,
        top_right: 8.0,
        bottom_right: 8.0,
        bottom_left: 8.0,
        token: None,
    };
    node
}

fn scene_with(node: Node) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_effects_golden"), "Effects Golden");
    scene
        .apply_operations([
            Operation::AddPage {
                page: Page {
                    id: PageId::from("page_card"),
                    name: "Card".to_owned(),
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
                    background: vec![fill("paint_page_bg", "#faf7f0")],
                },
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_card")),
                index: 0,
                node,
            },
        ])
        .unwrap();
    scene
}

fn render_svg(scene: &Scene) -> String {
    let request = ExportRequest {
        profile: ExportProfile {
            name: "svg_golden".to_owned(),
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
        page_ids: vec![PageId::from("page_card")],
        purpose: ExportPurpose::UserDownload,
    };
    let result = SvgExportAdapter::new()
        .export(scene, &request)
        .expect("exports");
    String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8 svg")
}

fn assert_golden(name: &str, svg: &str) {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/goldens")
        .join(format!("{name}.svg"));
    if std::env::var("UPDATE_EFFECTS_GOLDENS").is_ok() {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, svg).unwrap();
        return;
    }
    let expected = std::fs::read_to_string(&path)
        .unwrap_or_else(|_| panic!("missing golden {path:?}; run with UPDATE_EFFECTS_GOLDENS=1"));
    assert_eq!(
        svg, expected,
        "golden {name} drifted; regenerate intentionally with UPDATE_EFFECTS_GOLDENS=1"
    );
}

#[test]
fn golden_multi_fill_card() {
    let mut node = card("card");
    node.fills = vec![fill("fill_base", "#ffffff"), fill("fill_tint", "#f5f1e9")];
    node.strokes = vec![
        Stroke::solid(PaintId::from("stroke_outer"), solid("#111827"), 2.0),
        Stroke::solid(PaintId::from("stroke_inner"), solid("#256c70"), 1.0),
    ];
    assert_golden("multi_fill_card", &render_svg(&scene_with(node)));
}

#[test]
fn golden_dashed_stroke() {
    let mut node = card("card");
    node.fills = vec![fill("fill_base", "#ffffff")];
    node.strokes = vec![Stroke {
        dash: Some(vec![6.0, 4.0]),
        cap: StrokeCap::Round,
        join: StrokeJoin::Round,
        ..Stroke::solid(PaintId::from("stroke_border"), solid("#111827"), 1.0)
    }];
    assert_golden("dashed_stroke", &render_svg(&scene_with(node)));
}

#[test]
fn golden_layered_shadows() {
    let mut node = card("card");
    node.fills = vec![fill("fill_base", "#ffffff")];
    node.effects = vec![
        shadow("shadow_crisp", 1.0, 2.0, 0.0),
        shadow("shadow_soft", 8.0, 24.0, 0.0),
        shadow("shadow_spread", 16.0, 32.0, 4.0),
    ];
    assert_golden("layered_shadows", &render_svg(&scene_with(node)));
}

#[test]
fn golden_gradient_with_shadow() {
    let mut node = card("card");
    node.fills = vec![Fill {
        id: PaintId::from("fill_gradient"),
        paint: Paint::LinearGradient {
            angle: 90.0,
            stops: vec![
                ColorStop {
                    color: Color::Hex {
                        value: "#ffffff".to_owned(),
                    },
                    position: 0.0,
                },
                ColorStop {
                    color: Color::Hex {
                        value: "#256c70".to_owned(),
                    },
                    position: 1.0,
                },
            ],
        },
    }];
    node.effects = vec![shadow("shadow_soft", 8.0, 24.0, 0.0)];
    assert_golden("gradient_with_shadow", &render_svg(&scene_with(node)));
}
