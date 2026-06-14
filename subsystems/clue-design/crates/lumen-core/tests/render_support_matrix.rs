//! Effects Contract V0, slice X6: the renderer support matrix is code, not
//! prose. These tests pin the per-format verdicts, the feature scanner,
//! and the preflight surface that announces degradation before export.

use lumen_core::{
    effect_features_for_node, effect_support_diagnostics, preflight_scene, Color, DocumentId,
    Effect, EffectFeature, EffectId, EffectKind, EffectSupportLevel, ExportFormat, ExportProfile,
    Node, NodeId, NodeKind, Operation, Orientation, Page, PageId, PagePreset, PageSize, Paint,
    PaintId, ParentRef, PreflightOptions, RenderTarget, RendererEffectSupport, Scene, SizeSpec,
    Stroke, StrokeAlign, StrokeCap, Transform, Unit,
};

const ALL_FEATURES: [EffectFeature; 10] = [
    EffectFeature::MultiFill,
    EffectFeature::MultiStroke,
    EffectFeature::LinearGradientPaint,
    EffectFeature::RadialGradientPaint,
    EffectFeature::StrokeDash,
    EffectFeature::StrokeCapJoin,
    EffectFeature::StrokeAlignment,
    EffectFeature::DropShadow,
    EffectFeature::DropShadowSpread,
    EffectFeature::LayeredShadows,
];

fn solid(value: &str) -> Paint {
    Paint::Solid {
        color: Color::Hex {
            value: value.to_owned(),
        },
    }
}

fn shadow(id: &str, spread: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::DropShadow {
            color: Color::Hex {
                value: "#000000".to_owned(),
            },
            opacity: 0.18,
            x: 0.0,
            y: 8.0,
            blur: 24.0,
            spread,
            color_token: None,
        },
    }
}

#[test]
fn png_inherits_svg_for_every_feature() {
    for feature in ALL_FEATURES {
        assert_eq!(
            RendererEffectSupport::level(&RenderTarget::Svg, feature),
            RendererEffectSupport::level(&RenderTarget::Png { scale: 2.0 }, feature),
            "PNG must inherit the SVG verdict for {feature:?}"
        );
    }
}

#[test]
fn svg_is_native_except_stroke_alignment() {
    for feature in ALL_FEATURES {
        let expected = if feature == EffectFeature::StrokeAlignment {
            EffectSupportLevel::Approximate
        } else {
            EffectSupportLevel::Native
        };
        assert_eq!(
            RendererEffectSupport::level(&RenderTarget::Svg, feature),
            expected,
            "{feature:?}"
        );
    }
}

#[test]
fn pdf_is_solid_paint_only() {
    use EffectFeature::*;
    use EffectSupportLevel::*;
    let cases = [
        (MultiFill, Approximate),
        (MultiStroke, Approximate),
        (LinearGradientPaint, Unsupported),
        (RadialGradientPaint, Unsupported),
        (StrokeDash, Approximate),
        (StrokeCapJoin, Approximate),
        (StrokeAlignment, Approximate),
        (DropShadow, Unsupported),
        (DropShadowSpread, Unsupported),
        (LayeredShadows, Unsupported),
    ];
    for (feature, expected) in cases {
        assert_eq!(
            RendererEffectSupport::level(&RenderTarget::Pdf, feature),
            expected,
            "{feature:?}"
        );
    }
}

#[test]
fn konva_approximates_alignment_spread_and_layered_shadows() {
    use EffectFeature::*;
    for feature in ALL_FEATURES {
        let expected = if matches!(feature, StrokeAlignment | DropShadowSpread | LayeredShadows) {
            EffectSupportLevel::Approximate
        } else {
            EffectSupportLevel::Native
        };
        assert_eq!(
            RendererEffectSupport::level(&RenderTarget::KonvaScene, feature),
            expected,
            "{feature:?}"
        );
    }
}

#[test]
fn feature_scanner_reports_the_features_in_use() {
    let mut node = Node::new(NodeId::from("card"), NodeKind::Rect);
    assert!(effect_features_for_node(&node).is_empty());

    node.fills = vec![
        lumen_core::editing::solid_fill("fill_a", "#ffffff"),
        Fill {
            id: PaintId::from("fill_gradient"),
            paint: Paint::LinearGradient {
                angle: 90.0,
                stops: vec![lumen_core::scene::ColorStop {
                    color: Color::Hex {
                        value: "#ffffff".to_owned(),
                    },
                    position: 0.0,
                }],
            },
        },
    ];
    node.strokes = vec![Stroke {
        dash: Some(vec![6.0, 4.0]),
        cap: StrokeCap::Round,
        align: StrokeAlign::Inside,
        ..Stroke::solid(PaintId::from("stroke_a"), solid("#111827"), 1.0)
    }];
    node.effects = vec![shadow("shadow_a", 0.0), shadow("shadow_b", 4.0)];

    use EffectFeature::*;
    assert_eq!(
        effect_features_for_node(&node),
        vec![
            MultiFill,
            LinearGradientPaint,
            StrokeDash,
            StrokeCapJoin,
            StrokeAlignment,
            DropShadow,
            DropShadowSpread,
            LayeredShadows,
        ]
    );
}

use lumen_core::Fill;

fn scene_with_effect_card(profile_format: ExportFormat) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_matrix"), "Matrix");
    let mut node = Node::new(NodeId::from("card"), NodeKind::Rect);
    node.transform = Transform {
        x: 24.0,
        y: 24.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(200.0, 120.0);
    node.fills = vec![lumen_core::editing::solid_fill("fill_a", "#ffffff")];
    node.effects = vec![shadow("shadow_soft", 0.0)];
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
                    background: Vec::new(),
                },
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_card")),
                index: 0,
                node,
            },
        ])
        .unwrap();
    scene.export_profiles.push(ExportProfile {
        name: "primary".to_owned(),
        format: profile_format,
        pdf_intent: None,
        raster: None,
        include_bleed: false,
        embed_fonts: false,
    });
    scene
}

#[test]
fn support_diagnostics_emit_lumx_codes_per_verdict() {
    let scene = scene_with_effect_card(ExportFormat::Pdf);

    let pdf = effect_support_diagnostics(&scene, &[], &RenderTarget::Pdf);
    assert!(
        pdf.iter().any(|diagnostic| diagnostic.code == "LUMX0002"
            && diagnostic.message.contains("drop shadow")),
        "{pdf:#?}"
    );

    let svg = effect_support_diagnostics(&scene, &[], &RenderTarget::Svg);
    assert!(
        svg.is_empty(),
        "SVG is native for this scene's features: {svg:#?}"
    );
}

#[test]
fn preflight_surfaces_matrix_verdicts_for_export_profiles() {
    let scene = scene_with_effect_card(ExportFormat::Pdf);
    let result = preflight_scene(scene, None, PreflightOptions::default());

    assert!(
        result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMX0002"),
        "preflight must announce PDF effect degradation before export: {:#?}",
        result.diagnostics
    );
    assert!(
        !result.has_errors(),
        "matrix verdicts are warnings, not preflight failures"
    );

    // The same scene with an SVG profile preflights without LUMX verdicts.
    let svg_scene = scene_with_effect_card(ExportFormat::Svg);
    let svg_result = preflight_scene(svg_scene, None, PreflightOptions::default());
    assert!(
        !svg_result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.starts_with("LUMX")),
        "{:#?}",
        svg_result.diagnostics
    );
}
