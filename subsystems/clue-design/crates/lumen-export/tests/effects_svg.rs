//! Effects Contract V0, slice X4: SVG export of paint stacks, advanced
//! strokes, and drop shadows. These are golden-substring tests: the exact
//! markup shape (layer order, attribute names, deterministic filter ids) is
//! the contract that Konva parity (X5) and PNG raster output inherit.

use lumen_core::scene::{ColorStop, CornerRadii, TextNode};
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
            source: None,
            output: None,
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

// ---------------------------------------------------------------------------
// A4 effects: glow / layer blur / inner shadow, per-corner radius, stop-opacity
// ---------------------------------------------------------------------------

fn glow(id: &str, color: &str, blur: f64, spread: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::Glow {
            color: Color::Hex {
                value: color.to_owned(),
            },
            opacity: 0.8,
            blur,
            spread,
            color_token: None,
        },
    }
}

fn layer_blur(id: &str, radius: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::LayerBlur { radius },
    }
}

fn inner_shadow(id: &str, y: f64, blur: f64, spread: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::InnerShadow {
            color: Color::Hex {
                value: "#101828".to_owned(),
            },
            opacity: 0.6,
            x: 0.0,
            y,
            blur,
            spread,
            color_token: None,
        },
    }
}

#[test]
fn a4_effect_stack_emits_d1_stacking_order() {
    // One node exercising layer blur + glow + drop shadow + inner shadow.
    // The general pipeline must emit: layer-blur results, then outer
    // (shadow/glow) results, then inner results, and merge bottom-up as
    // outers (reversed) → blurred base → inners (reversed).
    let mut node = card_node("card");
    node.fills = vec![fill("fill_base", "#6d8bff")];
    node.effects = vec![
        glow("g", "#a855f7", 20.0, 4.0),
        layer_blur("lb", 6.0),
        shadow("ds", 8.0, 24.0, 0.0),
        inner_shadow("is", 6.0, 10.0, 2.0),
    ];
    let scene = scene_with(node);
    let (svg, _diagnostics) = render(&scene);

    // Layer blur applies to the source and its alpha before shadows compute.
    let lb = svg.find("result=\"lumen-lb-0\"").expect("layer blur present");
    let lba = svg
        .find("result=\"lumen-lba-0\"")
        .expect("layer blur alpha present");
    // Outer (glow + drop shadow) composited from the blurred alpha.
    let outer0 = svg
        .find("result=\"lumen-outer-0\"")
        .expect("outer effect 0 present");
    let outer1 = svg
        .find("result=\"lumen-outer-1\"")
        .expect("outer effect 1 present");
    // Inner shadow computed from the blurred alpha.
    let inner = svg
        .find("result=\"lumen-inner-0\"")
        .expect("inner shadow present");
    let merge = svg.find("<feMerge>").expect("feMerge present");

    // Definition order: blurred base → outers → inners → merge.
    assert!(lb < lba || lba < outer0, "{svg}");
    assert!(lba < outer0, "blurred alpha before outer effects: {svg}");
    assert!(outer1 < inner, "outer effects before inner effects: {svg}");
    assert!(inner < merge, "effects defined before the merge: {svg}");

    // Merge order (bottom-up): outers reversed, then the blurred base, then
    // inners reversed. First effect of each class is topmost of its class.
    let merge_body = &svg[merge..];
    let m_outer1 = merge_body
        .find("<feMergeNode in=\"lumen-outer-1\"")
        .expect("outer1 merged");
    let m_outer0 = merge_body
        .find("<feMergeNode in=\"lumen-outer-0\"")
        .expect("outer0 merged");
    let m_base = merge_body
        .find("<feMergeNode in=\"lumen-lb-0\"")
        .expect("blurred base merged");
    let m_inner = merge_body
        .find("<feMergeNode in=\"lumen-inner-0\"")
        .expect("inner merged");
    assert!(
        m_outer1 < m_outer0 && m_outer0 < m_base && m_base < m_inner,
        "merge is outers(reversed) → base → inners(reversed): {svg}"
    );
}

#[test]
fn pure_drop_shadow_keeps_pre_a4_fedropshadow_markup() {
    // Regression guard: a stack with only drop shadows must still emit the
    // exact pre-A4 feDropShadow fast path (no general pipeline result names).
    let mut node = card_node("card");
    node.fills = vec![fill("fill_base", "#ffffff")];
    node.effects = vec![shadow("ds", 8.0, 24.0, 0.0)];
    let scene = scene_with(node);
    let (svg, _d) = render(&scene);
    assert!(svg.contains("<feDropShadow"), "{svg}");
    assert!(!svg.contains("lumen-lb-"), "no general pipeline: {svg}");
    assert!(!svg.contains("lumen-outer-"), "no general pipeline: {svg}");
}

#[test]
fn per_corner_radius_emits_path_mixed_and_rx_uniform() {
    // Mixed corners → per-corner <path>; uniform corners keep <rect rx>.
    let mut mixed = card_node("card");
    mixed.corner = CornerRadii {
        top_left: 40.0,
        top_right: 4.0,
        bottom_right: 40.0,
        bottom_left: 4.0,
        token: None,
    };
    mixed.fills = vec![fill("fill_base", "#ffffff")];
    let (svg, _d) = render(&scene_with(mixed));
    assert!(
        svg.contains("data-lumen-node-id=\"card\"") && svg.contains("<path"),
        "mixed corners emit a path: {svg}"
    );

    let mut uniform = card_node("card2");
    uniform.corner = CornerRadii {
        top_left: 12.0,
        top_right: 12.0,
        bottom_right: 12.0,
        bottom_left: 12.0,
        token: None,
    };
    uniform.fills = vec![fill("fill_base", "#ffffff")];
    let (svg2, _d) = render(&scene_with(uniform));
    assert!(svg2.contains("rx=\"12\""), "uniform keeps rx: {svg2}");
    assert!(!svg2.contains("<path"), "uniform has no path body: {svg2}");
}

#[test]
fn gradient_stop_alpha_emits_stop_opacity() {
    let mut node = card_node("card");
    node.fills = vec![Fill {
        id: PaintId::from("grad"),
        paint: Paint::LinearGradient {
            angle: 90.0,
            stops: vec![
                ColorStop {
                    color: Color::Hex {
                        value: "#ffffffff".to_owned(),
                    },
                    position: 0.0,
                },
                ColorStop {
                    color: Color::Hex {
                        value: "#00000080".to_owned(),
                    },
                    position: 1.0,
                },
            ],
        },
    }];
    let (svg, _d) = render(&scene_with(node));
    // Opaque stop stays 6-digit + opacity 1; the 0x80 stop is ~0.5 opacity.
    assert!(
        svg.contains("stop-color=\"#ffffff\" stop-opacity=\"1\""),
        "{svg}"
    );
    assert!(
        svg.contains("stop-color=\"#000000\" stop-opacity=\"0.5"),
        "{svg}"
    );
    // No raw 8-digit hex leaked into a stop-color.
    assert!(!svg.contains("stop-color=\"#00000080\""), "{svg}");
}

#[test]
fn single_solid_text_stroke_renders_behind_the_fill() {
    // A6a D5: LUME0214 RETIRED — a single solid text stroke now renders (behind
    // the fill via paint-order), never dropped-with-advisory.
    let mut node = Node::new(NodeId::from("label"), NodeKind::Text(TextNode {
        content: "Bleed".to_owned(),
        ..TextNode::default()
    }));
    node.transform = Transform {
        x: 24.0,
        y: 24.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(200.0, 40.0);
    node.fills = vec![fill("text_fill", "#111827")];
    node.strokes = vec![Stroke::solid(PaintId::from("text_stroke"), solid("#ffffff"), 2.0)];
    let (svg, diagnostics) = render(&scene_with(node));
    assert!(
        !diagnostics.iter().any(|d| d.code == "LUME0214"),
        "LUME0214 is retired and must not fire: {diagnostics:#?}"
    );
    assert!(svg.contains("stroke=\"#ffffff\""), "{svg}");
    assert!(svg.contains("stroke-width=\"2\""), "{svg}");
    assert!(svg.contains("paint-order=\"stroke fill\""), "{svg}");
}

#[test]
fn multi_and_dashed_text_strokes_advise_and_render_first_solid() {
    // A6a D5: extras (>1 stroke, gradient, dash) reduce to LUME0215; the first
    // solid stroke still renders.
    let mut node = Node::new(NodeId::from("label"), NodeKind::Text(TextNode {
        content: "Outline".to_owned(),
        ..TextNode::default()
    }));
    node.transform = Transform { x: 8.0, y: 8.0, ..Transform::default() };
    node.size = SizeSpec::fixed(200.0, 40.0);
    node.fills = vec![fill("text_fill", "#111827")];
    let mut dashed = Stroke::solid(PaintId::from("s1"), solid("#ff0000"), 3.0);
    dashed.dash = Some(vec![4.0, 2.0]);
    node.strokes = vec![
        dashed,
        Stroke::solid(PaintId::from("s2"), solid("#00ff00"), 1.0),
    ];
    let (svg, diagnostics) = render(&scene_with(node));
    assert!(
        diagnostics.iter().any(|d| d.code == "LUME0215"),
        "multi/dash text stroke advisory: {diagnostics:#?}"
    );
    assert!(svg.contains("stroke=\"#ff0000\""), "first solid stroke renders: {svg}");
}

#[test]
fn blur_only_stack_outputs_the_blurred_graphic_not_its_alpha() {
    // Review-gate regression (A4): the filter's output is the LAST
    // primitive's result. A blur-only stack must end on the graphic blur —
    // an alpha-blur chain here would replace the node with a black
    // silhouette. The alpha chain exists only to feed shadow/glow/inner
    // geometry, so it must be absent entirely on a blur-only stack.
    let mut node = card_node("card");
    node.fills = vec![fill("fill_base", "#6d8bff")];
    node.effects = vec![layer_blur("lb", 6.0)];
    let (svg, _d) = render(&scene_with(node));
    assert!(svg.contains("result=\"lumen-lb-0\""), "{svg}");
    assert!(!svg.contains("lumen-lba-"), "no alpha chain on blur-only: {svg}");
    let filter_start = svg.find("<filter id=\"lumen-effect-card\"").expect("filter");
    let filter_end = svg[filter_start..].find("</filter>").expect("filter close") + filter_start;
    let body = &svg[filter_start..filter_end];
    let last_primitive = body.rfind("<fe").expect("primitive");
    assert!(
        body[last_primitive..].contains("result=\"lumen-lb-0\""),
        "graphic blur is the final primitive (the filter output): {body}"
    );
}

#[test]
fn per_corner_path_geometry_is_a_valid_clockwise_outline() {
    // Review-gate regression (A4): the left edge must rise to (0, tl) before
    // the top-left arc — the original emission went to (0, height-tl),
    // producing an impossible arc. 200x120 rect, corners tl=40,tr=4,br=40,bl=4.
    let mut mixed = card_node("card");
    mixed.corner = CornerRadii {
        top_left: 40.0,
        top_right: 4.0,
        bottom_right: 40.0,
        bottom_left: 4.0,
        token: None,
    };
    mixed.fills = vec![fill("fill_base", "#ffffff")];
    let (svg, _d) = render(&scene_with(mixed));
    assert!(
        svg.contains("M 40 0 L 196 0 A 4 4 0 0 1 200 4 L 200 80 A 40 40 0 0 1 160 120 L 4 120 A 4 4 0 0 1 0 116 L 0 40 A 40 40 0 0 1 40 0 Z"),
        "full clockwise outline with correct left edge: {svg}"
    );
}

fn a6_text_node(id: &str, kind: TextNode) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Text(kind));
    node.transform = Transform { x: 16.0, y: 16.0, ..Transform::default() };
    node.size = SizeSpec::fixed(240.0, 40.0);
    node.fills = vec![fill("tf", "#111827")];
    node
}

#[test]
fn svg_emits_transformed_tspans_not_the_css_attribute() {
    // A6a D1: the measured line text is the CASED string; SVG never leans on
    // the CSS text-transform attribute.
    let node = a6_text_node("t", TextNode {
        content: "hello".to_owned(),
        text_transform: lumen_core::TextTransform::Uppercase,
        ..TextNode::default()
    });
    let (svg, _d) = render(&scene_with(node));
    assert!(svg.contains(">HELLO</tspan>"), "{svg}");
    assert!(!svg.contains("text-transform"), "must not emit the CSS attribute: {svg}");
}

#[test]
fn svg_emits_text_decoration_attribute() {
    let node = a6_text_node("t", TextNode {
        content: "sale".to_owned(),
        underline: true,
        strikethrough: true,
        ..TextNode::default()
    });
    let (svg, _d) = render(&scene_with(node));
    assert!(svg.contains("text-decoration=\"underline line-through\""), "{svg}");

    let underline_only = a6_text_node("u", TextNode {
        content: "link".to_owned(),
        underline: true,
        ..TextNode::default()
    });
    let (svg2, _d) = render(&scene_with(underline_only));
    assert!(svg2.contains("text-decoration=\"underline\""), "{svg2}");
    assert!(!svg2.contains("line-through"), "{svg2}");
}

#[derive(Debug)]
struct DiagnosticMeasurer;

impl lumen_core::TextMeasurer for DiagnosticMeasurer {
    fn measure(
        &self,
        input: &lumen_core::TextMeasureInput,
    ) -> lumen_core::TextMeasureOutput {
        let mut out = lumen_core::HeuristicTextMeasurer.measure(input);
        out.diagnostics.push(lumen_core::Diagnostic::warning(
            lumen_core::Phase::Layout,
            "LUMS0100",
            "fake whole-family fallback".to_owned(),
            None,
        ));
        out
    }
    fn shaping(&self) -> bool {
        true
    }
}

#[test]
fn svg_export_folds_measured_diagnostics_r1() {
    // R1: a direct SVG export must surface the measurer's own diagnostics
    // (LUMS0100/0103/0104) even with no preceding preflight.
    use std::sync::Arc;
    let node = a6_text_node("t", TextNode {
        content: "copy".to_owned(),
        ..TextNode::default()
    });
    let scene = scene_with(node);
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
        .with_measurer(Arc::new(DiagnosticMeasurer))
        .export(&scene, &request)
        .expect("exports");
    assert!(
        result.diagnostics.iter().any(|d| d.code == "LUMS0100"),
        "R1 fold missing: {:#?}",
        result.diagnostics
    );
}
