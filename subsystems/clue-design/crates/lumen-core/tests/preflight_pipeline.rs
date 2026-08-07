use lumen_core::{
    compile_dsl_into_scene, platform_default_brand_kit, preflight_scene,
    scene_has_token_references, validate_brand_kit, BrandKit, BrandMode, ColorTokenValue,
    DiagnosticSeverity, Dimension, DocumentId, Medium, NodeId, NodeKind, Paint, PreflightOptions,
    Scene, TokenResolutionOptions,
};
use std::collections::BTreeMap;

const ACME_BRAND_KIT: &str = include_str!("../fixtures/brand_kits/acme_full.json");

fn acme_brand_kit() -> BrandKit {
    serde_json::from_str(ACME_BRAND_KIT).unwrap()
}

fn tokenized_dsl() -> &'static str {
    r#"
page page_a4
  hero autolayout(h) p(24,24) s(240,hug) fill($surface.brand) stroke($surface.brand,$stroke.width.firm) g($space.md) pad($space.md) rd($radius.md) o($opacity.subtle)
    headline text "Plan" p(0,0) s(160,80) style($type.headline)
  slot_text text "Plan" p(24,96) s(132,48) font("Inter",16,700,left) slot(campaign.headline)
"#
}

#[test]
fn platform_default_brand_kit_validates() {
    let brand_kit = platform_default_brand_kit().unwrap();
    let diagnostics = validate_brand_kit(&brand_kit);

    assert_no_diagnostics_errors(&diagnostics);
}

#[test]
fn concrete_scene_without_brand_kit_preflights() {
    let mut scene = Scene::new(DocumentId::from("doc_concrete_preflight"), "Concrete");
    let compile_output = compile_dsl_into_scene(
        r#"
page page_a4
  card rect p(16,16) s(120,48) fill(#111827) rd(8)
  headline text "Plan" p(24,28) s(96,24) font("Inter",16,700,left) fill(#ffffff)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());
    assert!(!scene_has_token_references(&scene));

    let result = preflight_scene(scene, None, PreflightOptions::default());

    assert_no_diagnostics_errors(&result.diagnostics);
    assert!(result.brand_report.is_none());
    assert!(result.brand_ref_operations.is_empty());
    assert!(result.token_operations.is_empty());
    assert!(result.layout_result.is_some());
    assert!(!result.layout_operations.is_empty());
}

#[test]
fn tokenized_scene_without_brand_kit_stops_before_layout() {
    let mut scene = Scene::new(DocumentId::from("doc_missing_brand"), "Missing Brand");
    let compile_output = compile_dsl_into_scene(tokenized_dsl(), &mut scene);

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());
    assert!(scene_has_token_references(&scene));

    let result = preflight_scene(scene, None, PreflightOptions::default());

    assert!(result.has_errors());
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMP0300"
            && diagnostic.severity == DiagnosticSeverity::Error
            && diagnostic.message.contains("surface.brand")
            && diagnostic.message.contains("type.headline")
    }));
    assert!(result.brand_report.is_none());
    assert!(result.layout_result.is_none());
    assert!(result.brand_ref_operations.is_empty());
    assert!(result.token_operations.is_empty());
    assert!(result.layout_operations.is_empty());
    assert!(scene_has_token_references(&result.scene));
}

#[test]
fn tokenized_scene_with_platform_default_brand_kit_preflights() {
    let brand_kit = platform_default_brand_kit().unwrap();
    let mut scene = Scene::new(
        DocumentId::from("doc_platform_default_preflight"),
        "Platform Default",
    );
    let compile_output = compile_dsl_into_scene(tokenized_dsl(), &mut scene);

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());

    let result = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());

    assert_no_diagnostics_errors(&result.diagnostics);
    assert_eq!(result.brand_ref_operations.len(), 1);
    assert!(!result.token_operations.is_empty());
    assert!(!result.layout_operations.is_empty());
    assert!(result.brand_report.is_some());
    assert!(result.layout_result.is_some());
    assert!(!scene_has_token_references(&result.scene));
}

#[test]
fn preflight_resolves_brand_tokens_before_layout() {
    let brand_kit = acme_brand_kit();
    let mut scene = Scene::new(DocumentId::from("doc_preflight"), "Preflight");
    let compile_output = compile_dsl_into_scene(tokenized_dsl(), &mut scene);

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());

    let hero = &scene.nodes[&NodeId::from("hero")];
    assert_eq!(
        hero.layout.as_ref().unwrap().gap_token,
        Some("space.md".to_owned())
    );
    assert_eq!(hero.corner.token, Some("radius.md".to_owned()));
    assert!(matches!(
        &hero.fills[0].paint,
        Paint::Token { token } if token == "surface.brand"
    ));

    let result = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());

    assert_no_diagnostics_errors(&result.diagnostics);
    assert_eq!(result.brand_ref_operations.len(), 1);
    assert!(!result.token_operations.is_empty());
    assert!(!result.layout_operations.is_empty());
    assert!(result.brand_report.is_some());
    assert!(result.layout_result.is_some());

    let hero = &result.scene.nodes[&NodeId::from("hero")];
    assert_eq!(hero.layout.as_ref().unwrap().gap, 12.0);
    assert!(hero.layout.as_ref().unwrap().gap_token.is_none());
    assert_eq!(
        hero.layout.as_ref().unwrap().padding,
        [12.0, 12.0, 12.0, 12.0]
    );
    assert!(hero.layout.as_ref().unwrap().padding_token.is_none());
    assert_eq!(hero.corner.top_left, 8.0);
    assert!(hero.corner.token.is_none());
    assert_eq!(hero.opacity, 0.72);
    assert!(hero.opacity_token.is_none());
    assert_eq!(hero.strokes[0].width, 2.0);
    assert!(hero.strokes[0].width_token.is_none());
    assert!(matches!(&hero.fills[0].paint, Paint::Solid { .. }));
    assert!(hero.computed.is_some());

    let headline = &result.scene.nodes[&NodeId::from("headline")];
    let NodeKind::Text(text) = &headline.kind else {
        panic!("expected text node");
    };
    assert_eq!(text.font_family, "Source Sans 3");
    assert_eq!(text.font_size, 56.0);
    assert_eq!(text.font_weight, 800);
    assert!(text.style_token.is_none());
    assert!(matches!(&headline.fills[0].paint, Paint::Solid { .. }));
    assert!(headline.computed.is_some());
}

#[test]
fn preflight_applies_computed_geometry_after_dimension_tokens_resolve() {
    let brand_kit = acme_brand_kit();
    let mut scene = Scene::new(DocumentId::from("doc_dim_token"), "Dimension Token");
    let compile_output = compile_dsl_into_scene(
        r#"
page page_a4
  badge rect p(16,16) s($space.xl,$space.md) fill($surface.brand)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());
    assert_eq!(
        scene.nodes[&NodeId::from("badge")].size.width,
        Dimension::Token {
            token: "space.xl".to_owned()
        }
    );

    let result = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());

    assert_no_diagnostics_errors(&result.diagnostics);
    let badge = &result.scene.nodes[&NodeId::from("badge")];
    assert_eq!(badge.size.width, Dimension::Fixed(24.0));
    assert_eq!(badge.size.height, Dimension::Fixed(12.0));
    let computed = badge.computed.as_ref().unwrap();
    assert_eq!(computed.layout_bounds.width, 24.0);
    assert_eq!(computed.layout_bounds.height, 12.0);
}

#[test]
fn preflight_uses_scene_medium_for_brand_token_resolution() {
    let mut brand_kit = acme_brand_kit();
    brand_kit
        .tokens
        .colors
        .get_mut("surface.brand")
        .unwrap()
        .value
        .modes
        .insert(
            "medium.print".to_owned(),
            ColorTokenValue::Hex {
                value: "#123456".to_owned(),
            },
        );

    let mut scene = Scene::new(DocumentId::from("doc_print_medium"), "Print Medium");
    scene.meta.medium = Some(Medium::Print);
    let compile_output = compile_dsl_into_scene(
        r#"
page page_a4
  card rect p(16,16) s(120,48) fill($surface.brand)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());

    let result = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());

    assert_no_diagnostics_errors(&result.diagnostics);
    let card = &result.scene.nodes[&NodeId::from("card")];
    assert!(matches!(
        &card.fills[0].paint,
        Paint::Solid {
            color: lumen_core::Color::Hex { value }
        } if value == "#123456"
    ));
}

#[test]
fn explicit_preflight_medium_mode_overrides_scene_medium() {
    let mut brand_kit = acme_brand_kit();
    brand_kit
        .tokens
        .colors
        .get_mut("surface.brand")
        .unwrap()
        .value
        .modes
        .insert(
            "medium.print".to_owned(),
            ColorTokenValue::Hex {
                value: "#123456".to_owned(),
            },
        );

    let mut scene = Scene::new(DocumentId::from("doc_explicit_medium"), "Explicit Medium");
    scene.meta.medium = Some(Medium::Print);
    let compile_output = compile_dsl_into_scene(
        r#"
page page_a4
  card rect p(16,16) s(120,48) fill($surface.brand)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());

    let result = preflight_scene(
        scene,
        Some(&brand_kit),
        PreflightOptions {
            token_resolution: TokenResolutionOptions {
                mode: BrandMode {
                    values: BTreeMap::from([("medium".to_owned(), "digital".to_owned())]),
                },
                ..TokenResolutionOptions::default()
            },
            ..PreflightOptions::default()
        },
    );

    assert_no_diagnostics_errors(&result.diagnostics);
    let card = &result.scene.nodes[&NodeId::from("card")];
    assert!(!matches!(
        &card.fills[0].paint,
        Paint::Solid {
            color: lumen_core::Color::Hex { value }
        } if value == "#123456"
    ));
}

#[test]
fn preflight_keeps_computed_geometry_when_text_validation_fails() {
    let mut scene = Scene::new(
        DocumentId::from("doc_text_fit_debug_preview"),
        "Text Fit Debug Preview",
    );
    let compile_output = compile_dsl_into_scene(
        r#"
page linkedin_square size(1080,1080,px)
  stack al(v,x(s),g(24),pad(0)) p(72,128) s(580,hug)
    headline text "Spend less time on the phone and more time in the operating room." p(0,0) s(fill,36) font("Inter",52,700,left) lh(1.08) wrap_text(true) max_lines(2)
    body text "Insight Health handles calls, scheduling, and patient routing for busy neurosurgery practices." p(0,0) s(fill,hug) font("Inter",18,400,left) lh(1.4) wrap_text(true) max_lines(4)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&compile_output.compile_output.diagnostics);
    assert!(compile_output.operation_error.is_none());

    let result = preflight_scene(scene, None, PreflightOptions::default());

    assert!(result.has_errors());
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMV0903" && diagnostic.severity == DiagnosticSeverity::Error
    }));
    assert!(result.layout_result.is_some());
    assert!(!result.layout_operations.is_empty());

    let headline = result
        .scene
        .nodes
        .get(&NodeId::from("headline"))
        .and_then(|node| node.computed.as_ref())
        .expect("headline should keep computed geometry for debug preview");
    let body = result
        .scene
        .nodes
        .get(&NodeId::from("body"))
        .and_then(|node| node.computed.as_ref())
        .expect("body should keep computed geometry for debug preview");

    assert!(body.layout_bounds.y > headline.layout_bounds.y);
}

fn assert_no_dsl_errors(diagnostics: &[lumen_core::DslDiagnostic]) {
    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.diagnostic.severity != DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
}

fn assert_no_diagnostics_errors(diagnostics: &[lumen_core::Diagnostic]) {
    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
}
