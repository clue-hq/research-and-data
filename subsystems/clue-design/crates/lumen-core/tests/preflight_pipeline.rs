use lumen_core::{
    compile_dsl_into_scene, platform_default_brand_kit, preflight_scene,
    scene_has_token_references, validate_brand_kit, BrandKit, DiagnosticSeverity, Dimension,
    DocumentId, NodeId, NodeKind, Paint, PreflightOptions, Scene,
};

const ACME_BRAND_KIT: &str = include_str!("../fixtures/brand_kits/acme_full.json");

fn acme_brand_kit() -> BrandKit {
    serde_json::from_str(ACME_BRAND_KIT).unwrap()
}

fn tokenized_dsl() -> &'static str {
    r#"
page page_a4
  hero autolayout(h) p(24,24) s(180,hug) fill($surface.brand) stroke($surface.brand,$stroke.width.firm) g($space.md) pad($space.md) rd($radius.md) o($opacity.subtle)
    headline text "Plan" p(0,0) s(132,hug) style($type.headline)
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
    assert!(matches!(
        &hero.fills[0].paint,
        Paint::Solid {
            color: lumen_core::Color::Hex { value }
        } if value == "#004D5A"
    ));
    assert!(hero.computed.is_some());

    let headline = &result.scene.nodes[&NodeId::from("headline")];
    let NodeKind::Text(text) = &headline.kind else {
        panic!("expected text node");
    };
    assert_eq!(text.font_size, 32.0);
    assert_eq!(text.font_weight, 800);
    assert!(text.style_token.is_none());
    assert!(matches!(
        &headline.fills[0].paint,
        Paint::Solid {
            color: lumen_core::Color::Hex { value }
        } if value == "#FFFFFF"
    ));
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
