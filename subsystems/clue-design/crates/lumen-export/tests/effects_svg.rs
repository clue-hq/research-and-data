//! Effects Contract V0, slice X4: SVG export of paint stacks, advanced
//! strokes, and drop shadows. These are golden-substring tests: the exact
//! markup shape (layer order, attribute names, deterministic filter ids) is
//! the contract that Konva parity (X5) and PNG raster output inherit.

use lumen_core::scene::ColorStop;
use lumen_core::{
    Color, DiagnosticSeverity, DocumentId, Effect, EffectId, EffectKind, ExportAdapter,
    ExportFormat, ExportProfile, ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind,
    Operation, Orientation, Page, PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Rect,
    Scene, SizeSpec, Stroke, StrokeAlign, StrokeCap, StrokeJoin, Transform, Unit,
};
use lumen_export::SvgExportAdapter;

fn page(id: &str, children: Vec<NodeId>) -> Page {
    Page {
        id: PageId::from(id),
        name: "Card".to_owned(),
        size: PageSize {
            width: 400.0,
            height: 300.0,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Landscape,
        },
        children,
        bleed: None,
        safe_area: Some(Rect {
            x: 12.0,
            y: 12.0,
            width: 376.0,
            height: 276.0,
        }),
        background: Vec::new(),
    }
}

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

fn card_node(id: &str) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
    node.transform = Transform {
        x: 24.0,
        y: 24.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(200.0, 120.0);
    node
}

fn scene_with(node: Node) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_effects_svg"), "Effects SVG");
    let node_id = node.id.clone();
    scene
        .apply_operations([
            Operation::AddPage {
                page: page("page_card", Vec::new()),
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_card")),
                index: 0,
                node,
            },
        ])
        .unwrap();
    assert!(scene.nodes.contains_key(&node_id));
    scene
}

fn render(scene: &Scene) -> (String, Vec<lumen_core::Diagnostic>) {
    let request = ExportRequest {
        profile: ExportProfile {
            name: "svg_preview".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        },
        page_ids: vec![PageId::from("page_card")],
        purpose: ExportPurpose::UserDownload,
    };
    let result = SvgExportAdapter::new()
        .export(scene, &request)
        .expect("exports");
    let svg = String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8 svg");
    (svg, result.diagnostics)
}

#[test]
fn multi_fill_and_stroke_stacks_render_in_order() {
    let mut node = card_node("card");
    node.fills = vec![fill("fill_base", "#ffffff"), fill("fill_tint", "#f5f1e9")];
    node.strokes = vec![
        Stroke::solid(PaintId::from("stroke_outer"), solid("#111827"), 2.0),
        Stroke::solid(PaintId::from("stroke_inner"), solid("#256c70"), 1.0),
    ];
    let scene = scene_with(node);

    let (svg, diagnostics) = render(&scene);

    // One geometry copy per stack entry, inside a node-attributed group.
    assert!(svg.contains("data-lumen-node-id=\"card\""), "{svg}");
    let base = svg.find("data-lumen-fill-id=\"fill_base\"").unwrap();
    let tint = svg.find("data-lumen-fill-id=\"fill_tint\"").unwrap();
    let outer = svg.find("data-lumen-stroke-id=\"stroke_outer\"").unwrap();
    let inner = svg.find("data-lumen-stroke-id=\"stroke_inner\"").unwrap();
    assert!(
        base < tint && tint < outer && outer < inner,
        "stack order must be fills bottom-to-top then strokes: {svg}"
    );
    assert!(
        svg.contains("fill=\"none\" stroke=\"#111827\""),
        "stroke layers paint no fill: {svg}"
    );
    assert!(
        !diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUME0204"),
        "the first-paint-only limitation is gone: {diagnostics:#?}"
    );
}

#[test]
fn dashed_stroke_renders_dasharray_cap_and_join() {
    let mut node = card_node("card");
    node.strokes = vec![Stroke {
        dash: Some(vec![6.0, 4.0]),
        cap: StrokeCap::Round,
        join: StrokeJoin::Round,
        ..Stroke::solid(PaintId::from("stroke_border"), solid("#111827"), 1.0)
    }];
    let scene = scene_with(node);

    let (svg, _) = render(&scene);
    assert!(svg.contains("stroke-dasharray=\"6 4\""), "{svg}");
    assert!(svg.contains("stroke-linecap=\"round\""), "{svg}");
    assert!(svg.contains("stroke-linejoin=\"round\""), "{svg}");
}

#[test]
fn default_cap_and_join_emit_no_attributes() {
    let mut node = card_node("card");
    node.strokes = vec![Stroke::solid(
        PaintId::from("stroke_border"),
        solid("#111827"),
        1.0,
    )];
    let scene = scene_with(node);

    let (svg, _) = render(&scene);
    assert!(!svg.contains("stroke-dasharray"), "{svg}");
    assert!(!svg.contains("stroke-linecap"), "{svg}");
    assert!(!svg.contains("stroke-linejoin"), "{svg}");
}

#[test]
fn non_center_stroke_alignment_degrades_with_advice() {
    let mut node = card_node("card");
    node.strokes = vec![Stroke {
        align: StrokeAlign::Inside,
        ..Stroke::solid(PaintId::from("stroke_border"), solid("#111827"), 1.0)
    }];
    let scene = scene_with(node);

    let (svg, diagnostics) = render(&scene);
    assert!(svg.contains("stroke=\"#111827\""), "{svg}");
    let advice = diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == "LUME0210")
        .expect("alignment advice emitted");
    assert_eq!(advice.severity, DiagnosticSeverity::Advice);
}

#[test]
fn drop_shadow_renders_deterministic_fe_drop_shadow_filter() {
    let mut node = card_node("card");
    node.fills = vec![fill("fill_base", "#ffffff")];
    node.effects = vec![shadow("shadow_soft", 8.0, 24.0, 0.0)];
    let scene = scene_with(node);

    let (svg, _) = render(&scene);
    assert!(svg.contains("<filter id=\"lumen-effect-card\""), "{svg}");
    assert!(
        svg.contains(
            "<feDropShadow dx=\"0\" dy=\"8\" stdDeviation=\"12\" flood-color=\"#000000\" flood-opacity=\"0.18\" />"
        ),
        "{svg}"
    );
    assert!(svg.contains("filter=\"url(#lumen-effect-card)\""), "{svg}");

    // Deterministic output: rendering twice yields identical markup.
    let (second, _) = render(&scene);
    assert_eq!(svg, second);
}

#[test]
fn layered_shadows_chain_in_stack_order() {
    let mut node = card_node("card");
    node.effects = vec![
        shadow("shadow_crisp", 1.0, 2.0, 0.0),
        shadow("shadow_soft", 8.0, 24.0, 0.0),
    ];
    let scene = scene_with(node);

    let (svg, _) = render(&scene);
    assert_eq!(svg.matches("<feDropShadow").count(), 2, "{svg}");
    let crisp = svg.find("dy=\"1\"").unwrap();
    let soft = svg.find("dy=\"8\"").unwrap();
    assert!(
        crisp < soft,
        "first stack entry chains first (topmost shadow): {svg}"
    );
}

#[test]
fn spread_shadow_uses_morphology_composite() {
    let mut node = card_node("card");
    node.effects = vec![shadow("shadow_spread", 8.0, 24.0, 4.0)];
    let scene = scene_with(node);

    let (svg, _) = render(&scene);
    assert!(
        svg.contains("<feMorphology in=\"SourceAlpha\" operator=\"dilate\" radius=\"4\""),
        "{svg}"
    );
    assert!(svg.contains("<feGaussianBlur"), "{svg}");
    assert!(svg.contains("<feMerge>"), "{svg}");
    assert!(
        svg.contains("<feMergeNode in=\"SourceGraphic\" />"),
        "{svg}"
    );
}

#[test]
fn gradient_fill_combines_with_shadow_filter() {
    let mut node = card_node("card");
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
    let scene = scene_with(node);

    let (svg, _) = render(&scene);
    assert!(
        svg.contains("<linearGradient id=\"lumen-gradient-fill_gradient\""),
        "{svg}"
    );
    assert!(
        svg.contains("fill=\"url(#lumen-gradient-fill_gradient)\""),
        "{svg}"
    );
    assert!(svg.contains("filter=\"url(#lumen-effect-card)\""), "{svg}");
}

#[test]
fn token_shadow_color_is_skipped_with_unresolved_token_diagnostic() {
    let mut node = card_node("card");
    node.effects = vec![Effect {
        id: EffectId::from("shadow_brand"),
        kind: EffectKind::DropShadow {
            color: Color::Token {
                token: "shadow.soft".to_owned(),
            },
            opacity: 0.18,
            x: 0.0,
            y: 8.0,
            blur: 24.0,
            spread: 0.0,
            color_token: Some("shadow.soft".to_owned()),
        },
    }];
    let scene = scene_with(node);

    let (svg, diagnostics) = render(&scene);
    assert!(
        !svg.contains("lumen-effect-card"),
        "token-colored shadows must not render silently wrong: {svg}"
    );
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUME0206"),
        "{diagnostics:#?}"
    );
}

#[test]
fn frame_shadow_wraps_children_via_group_filter() {
    let mut frame = Node::new(NodeId::from("card"), NodeKind::Frame);
    frame.transform = Transform {
        x: 24.0,
        y: 24.0,
        ..Transform::default()
    };
    frame.size = SizeSpec::fixed(200.0, 120.0);
    frame.fills = vec![fill("fill_base", "#ffffff")];
    frame.effects = vec![shadow("shadow_soft", 8.0, 24.0, 0.0)];
    let scene = scene_with(frame);

    let (svg, _) = render(&scene);
    assert!(
        svg.contains("<g id=\"lumen-node-card\" data-lumen-node-id=\"card\" filter=\"url(#lumen-effect-card)\"")
            || svg.contains("filter=\"url(#lumen-effect-card)\">"),
        "frame filter applies on the group: {svg}"
    );
}
