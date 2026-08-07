//! Effects Contract V0, slice X1: scene-model tests.
//!
//! The effect/stroke extensions must be serde back-compatible (pre-effects
//! JSON parses and round-trips byte-identically) and validation must reject
//! duplicate stack IDs and non-finite numbers.

use lumen_core::validation::validate_scene;
use lumen_core::{
    Color, DocumentId, Effect, EffectId, EffectKind, Node, NodeId, NodeKind, Operation,
    Orientation, Page, PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Scene, Stroke,
    StrokeAlign, StrokeCap, StrokeJoin, Unit,
};

const MINIMAL_SCENE: &str = include_str!("../fixtures/minimal_scene.json");

fn page(id: &str) -> Page {
    Page {
        id: PageId::from(id),
        name: id.to_owned(),
        size: PageSize {
            width: 1080.0,
            height: 1080.0,
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

fn drop_shadow(id: &str) -> Effect {
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
            spread: 0.0,
            color_token: None,
        },
    }
}

fn scene_with_card() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_effects"), "Effects");
    scene
        .apply_operation(Operation::AddPage { page: page("p1") })
        .unwrap();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("p1")),
            index: 0,
            node: Node::new(NodeId::from("card"), NodeKind::Rect),
        })
        .unwrap();
    scene
}

#[test]
fn pre_effects_scene_json_still_parses_and_round_trips_byte_identically() {
    let scene: Scene = serde_json::from_str(MINIMAL_SCENE).expect("V0 scene fixture parses");
    let node = &scene.nodes[&NodeId::from("node_contact_name")];
    assert!(node.effects.is_empty());

    // Re-serializing must not introduce effects/dash/cap/join/align keys:
    // the JSON value must be identical to the fixture.
    let original: serde_json::Value = serde_json::from_str(MINIMAL_SCENE).unwrap();
    let round_tripped = serde_json::to_value(&scene).unwrap();
    assert_eq!(
        round_tripped, original,
        "scene serialization must stay byte-compatible with pre-effects fixtures"
    );
}

#[test]
fn stroke_extensions_default_and_round_trip() {
    let stroke_json = serde_json::json!({
        "id": "paint_card_stroke_1",
        "paint": { "kind": "solid", "color": { "kind": "hex", "value": "#111827" } },
        "width": 1.0
    });
    let stroke: Stroke = serde_json::from_value(stroke_json.clone()).expect("V0 stroke parses");
    assert_eq!(stroke.dash, None);
    assert_eq!(stroke.cap, StrokeCap::Butt);
    assert_eq!(stroke.join, StrokeJoin::Miter);
    assert_eq!(stroke.align, StrokeAlign::Center);
    assert_eq!(
        serde_json::to_value(&stroke).unwrap(),
        stroke_json,
        "default stroke extensions must not serialize"
    );

    let advanced = Stroke {
        dash: Some(vec![6.0, 4.0]),
        cap: StrokeCap::Round,
        join: StrokeJoin::Bevel,
        align: StrokeAlign::Inside,
        ..stroke
    };
    let value = serde_json::to_value(&advanced).unwrap();
    assert_eq!(value["dash"], serde_json::json!([6.0, 4.0]));
    assert_eq!(value["cap"], "round");
    assert_eq!(value["join"], "bevel");
    assert_eq!(value["align"], "inside");
    let reparsed: Stroke = serde_json::from_value(value).unwrap();
    assert_eq!(reparsed, advanced);
}

#[test]
fn effect_serde_round_trips_with_optional_color_token() {
    let mut effect = drop_shadow("shadow_soft");
    let value = serde_json::to_value(&effect).unwrap();
    assert_eq!(value["kind"]["kind"], "drop_shadow");
    assert!(
        value["kind"].get("color_token").is_none(),
        "absent color_token must not serialize"
    );
    let reparsed: Effect = serde_json::from_value(value).unwrap();
    assert_eq!(reparsed, effect);

    let EffectKind::DropShadow { color_token, .. } = &mut effect.kind else {
        panic!("expected drop shadow");
    };
    *color_token = Some("shadow.soft".to_owned());
    let value = serde_json::to_value(&effect).unwrap();
    assert_eq!(value["kind"]["color_token"], "shadow.soft");
    let reparsed: Effect = serde_json::from_value(value).unwrap();
    assert_eq!(reparsed, effect);
}

#[test]
fn validation_rejects_duplicate_effect_ids() {
    let mut scene = scene_with_card();
    let node = scene.nodes.get_mut(&NodeId::from("card")).unwrap();
    node.effects = vec![drop_shadow("shadow_soft"), drop_shadow("shadow_soft")];

    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMV0700"),
        "duplicate effect ids must be a validation error: {diagnostics:#?}"
    );
}

#[test]
fn validation_rejects_non_finite_effect_values() {
    let mut scene = scene_with_card();
    let mut effect = drop_shadow("shadow_soft");
    let EffectKind::DropShadow { blur, .. } = &mut effect.kind else {
        panic!("expected drop shadow");
    };
    *blur = f64::NAN;
    scene.nodes.get_mut(&NodeId::from("card")).unwrap().effects = vec![effect];

    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMV0701"),
        "non-finite effect values must be a validation error: {diagnostics:#?}"
    );
}

#[test]
fn validation_rejects_negative_or_non_finite_dash_values() {
    let mut scene = scene_with_card();
    let node = scene.nodes.get_mut(&NodeId::from("card")).unwrap();
    node.strokes = vec![Stroke {
        dash: Some(vec![6.0, -4.0]),
        ..Stroke::solid(
            PaintId::from("paint_card_stroke_1"),
            Paint::Solid {
                color: Color::Hex {
                    value: "#111827".to_owned(),
                },
            },
            1.0,
        )
    }];

    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMV0702"),
        "negative dash values must be a validation error: {diagnostics:#?}"
    );
}

#[test]
fn validation_rejects_duplicate_paint_ids_within_a_stack() {
    let mut scene = scene_with_card();
    let node = scene.nodes.get_mut(&NodeId::from("card")).unwrap();
    node.fills = vec![
        lumen_core::editing::solid_fill("paint_card_fill_1", "#ffffff"),
        lumen_core::editing::solid_fill("paint_card_fill_1", "#f5f1e9"),
    ];

    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMV0703"),
        "duplicate fill ids must be a validation error: {diagnostics:#?}"
    );
}

#[test]
fn effects_apply_through_update_node_and_survive_checked_apply() {
    let mut scene = scene_with_card();
    scene
        .apply_operation_checked(Operation::UpdateNode {
            node_id: NodeId::from("card"),
            patch: lumen_core::NodePatch {
                effects: lumen_core::FieldPatch::Set(vec![drop_shadow("shadow_soft")]),
                ..lumen_core::NodePatch::default()
            },
        })
        .expect("effect update applies");
    assert_eq!(
        scene.nodes[&NodeId::from("card")].effects,
        vec![drop_shadow("shadow_soft")]
    );
}

// ---------------------------------------------------------------------------
// A4: glow / layer blur / inner shadow validation
// ---------------------------------------------------------------------------

fn set_effects(scene: &mut Scene, effects: Vec<Effect>) {
    scene.nodes.get_mut(&NodeId::from("card")).unwrap().effects = effects;
}

fn glow(id: &str, blur: f64, spread: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::Glow {
            color: Color::Hex {
                value: "#a855f7".to_owned(),
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

fn inner_shadow(id: &str, blur: f64, spread: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::InnerShadow {
            color: Color::Hex {
                value: "#101828".to_owned(),
            },
            opacity: 0.6,
            x: 0.0,
            y: 6.0,
            blur,
            spread,
            color_token: None,
        },
    }
}

#[test]
fn a4_effect_kinds_serde_round_trip_with_tags() {
    for (effect, tag) in [
        (glow("g", 20.0, 4.0), "glow"),
        (layer_blur("lb", 8.0), "layer_blur"),
        (inner_shadow("is", 10.0, 2.0), "inner_shadow"),
    ] {
        let value = serde_json::to_value(&effect).unwrap();
        assert_eq!(value["kind"]["kind"], tag, "serde tag for {tag}");
        let reparsed: Effect = serde_json::from_value(value).unwrap();
        assert_eq!(reparsed, effect);
    }
}

#[test]
fn validation_rejects_negative_layer_blur_radius() {
    let mut scene = scene_with_card();
    set_effects(&mut scene, vec![layer_blur("lb", -4.0)]);
    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMV0704"),
        "negative layer-blur radius is rejected: {diagnostics:#?}"
    );
}

#[test]
fn validation_rejects_negative_glow_blur_and_spread() {
    for effect in [glow("g", -2.0, 4.0), glow("g", 2.0, -4.0)] {
        let mut scene = scene_with_card();
        set_effects(&mut scene, vec![effect]);
        let diagnostics = validate_scene(&scene);
        assert!(
            diagnostics.iter().any(|d| d.code == "LUMV0704"),
            "negative glow blur/spread is rejected: {diagnostics:#?}"
        );
    }
}

#[test]
fn validation_rejects_non_finite_inner_shadow_and_allows_signed_offset() {
    // Non-finite blur -> LUMV0701.
    let mut scene = scene_with_card();
    set_effects(&mut scene, vec![inner_shadow("is", f64::INFINITY, 2.0)]);
    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMV0701"),
        "non-finite inner-shadow blur is rejected: {diagnostics:#?}"
    );

    // A negative y offset is legal (offsets are signed); no LUMV0704.
    let mut ok = scene_with_card();
    let mut effect = inner_shadow("is", 10.0, 0.0);
    if let EffectKind::InnerShadow { y, .. } = &mut effect.kind {
        *y = -6.0;
    }
    set_effects(&mut ok, vec![effect]);
    let clean = validate_scene(&ok);
    assert!(
        !clean.iter().any(|d| d.code == "LUMV0704"),
        "signed inner-shadow offset must not trip the non-negative check: {clean:#?}"
    );
}

#[test]
fn validation_rejects_duplicate_ids_across_effect_kinds() {
    let mut scene = scene_with_card();
    set_effects(&mut scene, vec![glow("fx", 20.0, 4.0), layer_blur("fx", 8.0)]);
    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMV0700"),
        "a duplicate id across effect kinds is rejected: {diagnostics:#?}"
    );
}
