use lumen_core::{
    collect_scene_token_references, compare_brand_kit_compatibility, compile_dsl_into_scene,
    compile_styles_brand_kit, generate_brand_kit, platform_default_brand_kit, preflight_scene,
    resolve_scene_tokens, summarize_brand_kit_for_authoring, validate_brand_kit,
    validate_brand_kit_product_ready, validate_scene_brand_governance, AssetId, AssetSource,
    BrandApprovalStatus, BrandAssets, BrandCompatibilityPolicy, BrandCompatibilityStatus,
    BrandConstraints, BrandGovernanceStrictness, BrandKit, BrandKitId, BrandMode, BrandModeSpec,
    BrandSeed, BrandSeedLogoRef, BrandSource, Color, ColorToken, ColorTokenValue, ComputedGeometry,
    ContrastPair, DiagnosticSeverity, Dimension, DocumentId, Fill, FontAsset, FontFace,
    FontLicense, FontStyle, ImageNode, LogoAsset, LogoColorMode, LogoUsage, LogoVariant, Medium,
    ModeValue, Node, NodeId, NodeKind, NumberToken, NumberTokenValue, NumberUnit, Operation,
    Orientation, Page, PageId, PagePreset, PageSize, Paint, PaintId, PreflightOptions, Rect, Scene,
    SizeSpec, Stroke, TextAlign, TextNode, TextSpan, TokenAlias, TokenCatalog, TokenChangeKind,
    TokenResolutionOptions, TokenStrictness, TypographyToken, TypographyTokenValue, Unit,
};
use std::collections::BTreeMap;

const ACME_BRAND_KIT: &str = include_str!("../fixtures/brand_kits/acme_full.json");
const VALID_INSIGHT_HEALTH_STYLES: &str =
    include_str!("../fixtures/styles/valid_insight_health.styles");
const INVALID_DUPLICATE_TOKEN_STYLES: &str =
    include_str!("../fixtures/styles/invalid_duplicate_token.styles");
const INVALID_MODE_DEFAULT_STYLES: &str =
    include_str!("../fixtures/styles/invalid_mode_default.styles");
const TOKENIZED_LINKEDIN_SQUARE: &str =
    include_str!("../fixtures/brand_templates/tokenized_linkedin_square.lumen");
const TOKENIZED_EMAIL_HERO: &str =
    include_str!("../fixtures/brand_templates/tokenized_email_hero.lumen");
const TOKENIZED_ONE_PAGER_SECTION: &str =
    include_str!("../fixtures/brand_templates/tokenized_one_pager_section.lumen");
const TOKENIZED_REPORT_COVER: &str =
    include_str!("../fixtures/brand_templates/tokenized_report_cover.lumen");

#[test]
fn brand_kit_fixture_round_trips_and_validates() {
    let brand_kit: BrandKit = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    let diagnostics = validate_brand_kit(&brand_kit);
    let product_ready = validate_brand_kit_product_ready(&brand_kit);

    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
    assert!(
        product_ready
            .iter()
            .all(|diagnostic| diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "{product_ready:#?}"
    );
    assert_eq!(brand_kit.approval_status, BrandApprovalStatus::Approved);
    assert_eq!(brand_kit.version, 3);
    assert_eq!(brand_kit.modes.defaults["medium"], "digital");
    assert!(brand_kit.tokens.colors.contains_key("surface.card"));
    assert!(brand_kit.tokens.typography.contains_key("type.cta"));
    assert!(brand_kit.tokens.assets.contains_key("logo.primary"));

    let json = serde_json::to_string_pretty(&brand_kit).unwrap();
    let decoded: BrandKit = serde_json::from_str(&json).unwrap();
    assert_eq!(brand_kit, decoded);
}

#[test]
fn a_font_licenses_embed_basis_survives_the_kit_round_trip() {
    // D-F2 (clone-fidelity F0, carried to F1.5). A font ingested from a workspace's OWN brand
    // material is embeddable on this platform, and the BASIS for that permission is the
    // platform's Terms of Use — not a license anybody read off the site. F0 could not say so in
    // its own field: `FontLicense` was a fixed struct, serde dropped the unknown `basis` key on
    // the validate round trip, and the basis had to ride inside a restrictions LINE instead.
    // This is that round trip, with the real field.
    let mut value: serde_json::Value = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    value["assets"]["fonts"]["brand"]["license"]["basis"] =
        serde_json::Value::String("platform-terms".to_owned());

    let brand_kit: BrandKit = serde_json::from_value(value).unwrap();
    assert_eq!(
        brand_kit.assets.fonts["brand"].license.basis.as_deref(),
        Some("platform-terms")
    );

    let json = serde_json::to_string(&brand_kit).unwrap();
    let decoded: BrandKit = serde_json::from_str(&json).unwrap();
    assert_eq!(
        decoded.assets.fonts["brand"].license.basis.as_deref(),
        Some("platform-terms"),
        "the basis must survive serialization, or the pipeline persists a kit that lost it"
    );
    assert_eq!(brand_kit, decoded);
}

#[test]
fn a_font_license_with_no_basis_serializes_exactly_as_it_did_before() {
    // Every kit that exists today lacks the field. Tolerated absent, and absent on the way out
    // too — `skip_serializing_if` keeps a pre-F1 kit's bytes identical, so adding the field
    // re-writes nothing at rest.
    let brand_kit: BrandKit = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    assert!(brand_kit.assets.fonts["brand"].license.basis.is_none());

    let value = serde_json::to_value(&brand_kit).unwrap();
    assert!(
        value["assets"]["fonts"]["brand"]["license"]
            .get("basis")
            .is_none(),
        "an absent basis must not serialize as null"
    );
}

#[test]
fn platform_default_is_product_ready_for_phase_c_contract() {
    let brand_kit = platform_default_brand_kit().unwrap();

    let diagnostics = validate_brand_kit_product_ready(&brand_kit);

    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
    assert!(brand_kit.modes.axes.contains_key("medium"));
    assert_eq!(brand_kit.modes.defaults["medium"], "digital");
    assert_eq!(brand_kit.approval_status, BrandApprovalStatus::Approved);
}

#[test]
fn tokenized_artifact_templates_preflight_across_brand_kits() {
    let platform = platform_default_brand_kit().unwrap();
    let acme: BrandKit = serde_json::from_str(ACME_BRAND_KIT).unwrap();

    let templates = [
        (
            "linkedin_square",
            TOKENIZED_LINKEDIN_SQUARE,
            PageId::from("linkedin_square"),
            (1080.0, 1080.0),
            NodeId::from("canvas"),
        ),
        (
            "email_header",
            TOKENIZED_EMAIL_HERO,
            PageId::from("email_header"),
            (1200.0, 520.0),
            NodeId::from("hero"),
        ),
        (
            "one_pager_section",
            TOKENIZED_ONE_PAGER_SECTION,
            PageId::from("one_pager_section"),
            (1440.0, 900.0),
            NodeId::from("section"),
        ),
        (
            "report_cover",
            TOKENIZED_REPORT_COVER,
            PageId::from("report_cover"),
            (816.0, 1056.0),
            NodeId::from("cover"),
        ),
    ];

    for (name, source, page_id, expected_size, comparison_node_id) in templates {
        let platform_scene = compile_and_preflight_template(name, source, &platform, &page_id);
        let acme_scene = compile_and_preflight_template(name, source, &acme, &page_id);

        let page = platform_scene
            .pages
            .get(&page_id)
            .unwrap_or_else(|| panic!("missing page {page_id} in {name}"));
        assert_eq!(page.size.width, expected_size.0, "{name}");
        assert_eq!(page.size.height, expected_size.1, "{name}");
        assert!(collect_scene_token_references(&platform_scene).is_empty());
        assert!(collect_scene_token_references(&acme_scene).is_empty());

        let platform_fill = first_solid_fill_hex(&platform_scene, &comparison_node_id)
            .unwrap_or_else(|| panic!("missing platform fill for {comparison_node_id}"));
        let acme_fill = first_solid_fill_hex(&acme_scene, &comparison_node_id)
            .unwrap_or_else(|| panic!("missing acme fill for {comparison_node_id}"));
        assert_ne!(
            platform_fill, acme_fill,
            "{name} should resolve differently across Brand Kits"
        );
    }
}

#[test]
fn brand_authoring_summary_exposes_product_ready_tokens_and_modes() {
    let brand_kit = platform_default_brand_kit().unwrap();

    let summary = summarize_brand_kit_for_authoring(&brand_kit);

    assert_eq!(summary.id, BrandKitId::from("brand_kit_platform_default"));
    assert!(summary.product_ready, "{:#?}", summary.diagnostics);
    assert_eq!(summary.default_mode.values["theme"], "light");
    assert_eq!(summary.default_mode.values["density"], "comfortable");
    assert_eq!(summary.default_mode.values["accessibility"], "standard");
    assert_eq!(summary.default_mode.values["medium"], "digital");
    assert!(summary.mode_axes.contains_key("medium"));
    assert!(summary
        .tokens
        .surface_tokens
        .contains(&"surface.brand".to_owned()));
    assert!(summary
        .tokens
        .text_tokens
        .contains(&"text.primary".to_owned()));
    assert!(summary
        .tokens
        .typography_tokens
        .contains(&"type.headline".to_owned()));
    assert!(summary
        .tokens
        .spacing_tokens
        .contains(&"space.card.padding".to_owned()));
    assert!(summary
        .tokens
        .radius_tokens
        .contains(&"radius.card".to_owned()));
    assert!(summary
        .assets
        .logo_tokens
        .contains(&"logo.primary".to_owned()));
    assert!(summary
        .authoring_rules
        .iter()
        .any(|rule| rule.contains("style($type.*)")));
}

#[test]
fn brand_seed_generator_produces_product_ready_unreviewed_brand_kit() {
    let report = generate_brand_kit(&health_brand_seed());

    assert!(
        report.brand_kit.is_some(),
        "expected generated brand kit, got diagnostics: {:#?}",
        report.diagnostics
    );
    assert!(
        report.confidence > 0.7,
        "expected useful confidence for evidence-backed seed, got {}",
        report.confidence
    );
    assert!(report.missing_inputs.is_empty(), "{report:#?}");

    let brand_kit = report.brand_kit.unwrap();
    let product_ready = validate_brand_kit_product_ready(&brand_kit);

    assert!(
        product_ready
            .iter()
            .all(|diagnostic| diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "{product_ready:#?}"
    );
    assert_eq!(
        brand_kit.approval_status,
        BrandApprovalStatus::GeneratedUnreviewed
    );
    assert!(brand_kit.compatibility_policy.require_product_ready_tokens);
    assert!(brand_kit.tokens.colors.contains_key("surface.brand"));
    assert!(brand_kit.tokens.colors.contains_key("text.primary"));
    assert!(brand_kit.tokens.spacing.contains_key("space.xl"));
    assert!(brand_kit.tokens.radii.contains_key("radius.md"));
    assert!(brand_kit.tokens.typography.contains_key("type.headline"));
    assert!(brand_kit.tokens.assets.contains_key("logo.primary"));
    assert!(brand_kit.assets.logos.contains_key("primary"));
    assert_eq!(
        brand_kit.modes.axes.get("medium").unwrap(),
        &vec!["digital".to_owned(), "print".to_owned()]
    );
}

#[test]
fn generated_brand_kit_can_drive_tokenized_preflight() {
    let report = generate_brand_kit(&health_brand_seed());
    let brand_kit = report.brand_kit.expect("generated kit");
    let mut scene = tokenized_scene(&brand_kit);
    scene
        .nodes
        .get_mut(&NodeId::from("node_headline"))
        .unwrap()
        .size = SizeSpec::fixed(640.0, 96.0);
    scene
        .pages
        .get_mut(&PageId::from("page_brand"))
        .unwrap()
        .size = lumen_core::normalize_page_size(lumen_core::PageSizeInput::new(
        720.0,
        320.0,
        Unit::Px,
        Some(PagePreset::Custom),
        Orientation::Landscape,
    ));

    let result = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());

    assert!(
        !result.has_errors(),
        "expected generated brand kit to resolve tokenized scene, got {:#?}",
        result.diagnostics
    );
    assert!(!result.token_operations.is_empty());
    assert!(!result.layout_operations.is_empty());

    let headline = result
        .scene
        .nodes
        .get(&NodeId::from("node_headline"))
        .unwrap();
    let NodeKind::Text(text) = &headline.kind else {
        panic!("expected text node");
    };
    assert_eq!(text.font_family, "Source Sans 3");
    assert!(text.style_token.is_none());
    assert!(headline.computed.is_some());
}

#[test]
fn brand_seed_generator_reports_missing_evidence_without_blocking_draft_generation() {
    let report = generate_brand_kit(&BrandSeed {
        id: BrandKitId::from("brand_seed_sparse"),
        version: 1,
        name: "Sparse Brand".to_owned(),
        primary_color: "#245E63".to_owned(),
        description: None,
        secondary_color: None,
        accent_color: None,
        neutral_color: None,
        preferred_fonts: Vec::new(),
        logo_refs: Vec::new(),
        tone_words: Vec::new(),
        website_url: None,
        style_guide_asset_ids: Vec::new(),
        sources: Vec::new(),
        default_mode: BrandMode::default(),
    });

    assert!(report.brand_kit.is_some(), "{report:#?}");
    assert!(report
        .missing_inputs
        .contains(&"preferred_fonts".to_owned()));
    assert!(report.missing_inputs.contains(&"logo_refs".to_owned()));
    assert!(report
        .missing_inputs
        .contains(&"website_or_style_guide".to_owned()));
    assert!(report.confidence < 0.7);
}

#[test]
fn brand_seed_generator_rejects_invalid_required_seed_fields() {
    let mut seed = health_brand_seed();
    seed.primary_color = "#nothex".to_owned();

    let report = generate_brand_kit(&seed);

    assert!(report.brand_kit.is_none());
    assert_eq!(report.confidence, 0.0);
    assert!(report
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0902"));
}

#[test]
fn product_ready_validation_reports_missing_semantic_contract() {
    let mut brand_kit = acme_brand_kit();
    brand_kit.approval_status = BrandApprovalStatus::Approved;

    let diagnostics = validate_brand_kit_product_ready(&brand_kit);

    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0800"));
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0801"));
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0817"));
}

#[test]
fn scene_brand_governance_flags_raw_styles() {
    let brand_kit = acme_brand_kit();
    let mut scene = Scene::new(DocumentId::from("doc_governance"), "Governance");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene
        .pages
        .insert(PageId::from("page_governance"), page("page_governance"));

    let mut node = Node::new(NodeId::from("node_raw"), NodeKind::Rect);
    node.fills = vec![Fill {
        id: PaintId::from("raw_fill"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#2463EB".to_owned(),
            },
        },
    }];
    scene.nodes.insert(node.id.clone(), node);
    scene
        .pages
        .get_mut(&PageId::from("page_governance"))
        .unwrap()
        .children
        .push(NodeId::from("node_raw"));

    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0804"
            && diagnostic.severity == lumen_core::DiagnosticSeverity::Error
    }));
}

#[test]
fn scene_brand_governance_flags_raw_layout_typography_and_hints() {
    let brand_kit = platform_default_brand_kit().unwrap();
    let mut scene = Scene::new(DocumentId::from("doc_governance_rich"), "Governance Rich");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene
        .pages
        .insert(PageId::from("page_governance"), page("page_governance"));

    let mut card = Node::new(NodeId::from("node_raw_card"), NodeKind::Rect);
    card.fills = vec![Fill {
        id: PaintId::from("raw_fill"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#2463EB".to_owned(),
            },
        },
    }];
    card.corner.top_left = 18.0;
    card.corner.top_right = 18.0;
    card.corner.bottom_right = 18.0;
    card.corner.bottom_left = 18.0;
    card.opacity = 0.8;
    card.layout = Some(lumen_core::AutoLayoutProps {
        gap: 18.0,
        padding: [20.0, 20.0, 20.0, 20.0],
        ..lumen_core::AutoLayoutProps::default()
    });

    let text = Node::new(
        NodeId::from("node_raw_text"),
        NodeKind::Text(TextNode {
            content: "Raw typography".to_owned(),
            font_family: "Times".to_owned(),
            font_size: 22.0,
            font_weight: 500,
            align: TextAlign::Left,
            style_token: None,
            ..TextNode::default()
        }),
    );

    scene
        .pages
        .get_mut(&PageId::from("page_governance"))
        .unwrap()
        .children = vec![card.id.clone(), text.id.clone()];
    scene.nodes.insert(card.id.clone(), card);
    scene.nodes.insert(text.id.clone(), text);

    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0804"
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("fill($surface.card)"))
    }));
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0805"
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("equivalent") && !hint.contains("style($type.body)"))
    }));
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0806"
            && diagnostic.message.contains("corner radius")
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("rd($radius.card)"))
    }));
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0806"
            && diagnostic.message.contains("opacity")
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("o($opacity.subtle)"))
    }));
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0806"
            && diagnostic.message.contains("layout gap")
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("resolved geometry") && !hint.contains("$space."))
    }));
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0806"
            && diagnostic.message.contains("layout padding")
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("resolved geometry") && !hint.contains("$space."))
    }));
}

#[test]
fn unbound_geometry_and_type_governance_preserves_policy_without_prescribing_replacements() {
    for strictness in [BrandGovernanceStrictness::Advisory, BrandGovernanceStrictness::Strict] {
        for empty in [false, true] {
            let mut kit = platform_default_brand_kit().unwrap();
            kit.tokens.spacing.clear();
            kit.tokens.typography.clear();
            if !empty {
                kit.tokens.spacing.insert("bespoke.margin".to_owned(), NumberToken {
                    value: ModeValue {
                        default: NumberTokenValue::Number { value: 19.0, unit: NumberUnit::Px },
                        modes: BTreeMap::new(),
                    },
                    role: None, description: None, provenance: None,
                });
            }
            // Resolution requires a structurally valid kit. Keep its unrelated
            // component references while testing the same bespoke/missing token.
            let mut resolution_kit = platform_default_brand_kit().unwrap();
            resolution_kit.tokens.spacing.extend(kit.tokens.spacing.clone());
            let mut scene = Scene::new(DocumentId::from("doc_unbound"), "Intentional literals");
            scene.meta.brand_kit = Some(resolution_kit.brand_ref());
            let mut node = Node::new(NodeId::from("literal"), NodeKind::Text(TextNode {
                font_family: "Inter".to_owned(), font_size: 37.0,
                line_height: 1.4, letter_spacing: 0.7,
                ..TextNode::default()
            }));
            node.layout = Some(lumen_core::AutoLayoutProps {
                gap: 13.0, padding: [71.0, 62.0, 53.0, 44.0],
                ..lumen_core::AutoLayoutProps::default()
            });
            scene.nodes.insert(node.id.clone(), node);
            let before = scene.clone();
            let diagnostics = validate_scene_brand_governance(&scene, &kit, strictness.clone());
            let relevant: Vec<_> = diagnostics.iter().filter(|d| {
                d.code == "LUMB0805" || (d.code == "LUMB0806" && d.message.contains("layout"))
            }).collect();
            assert_eq!(relevant.len(), 3);
            for diagnostic in relevant {
                assert_eq!(diagnostic.severity, if strictness == BrandGovernanceStrictness::Strict {
                    DiagnosticSeverity::Error
                } else { DiagnosticSeverity::Warning });
                assert_eq!(diagnostic.subject, Some(lumen_core::DiagnosticSubject::Node(NodeId::from("literal"))));
                assert!(diagnostic.message.contains("binding"));
                let hint = diagnostic.hint.as_deref().unwrap();
                assert!(!hint.contains('$'), "No arbitrary or invented replacement: {hint}");
                assert!(hint.contains("advisory") && hint.contains("strict"));
                if diagnostic.code == "LUMB0805" {
                    assert!(hint.contains("equivalent") && hint.contains("tracking"));
                } else {
                    assert!(hint.contains("resolved geometry"));
                }
            }
            assert_eq!(scene, before);
            let resolved = resolve_scene_tokens(&scene, &resolution_kit, &TokenResolutionOptions::default());
            assert!(!resolved.diagnostics.iter().any(|d| d.severity == DiagnosticSeverity::Error), "{:?}", resolved.diagnostics);
            let literal_layout = resolved.scene.nodes[&NodeId::from("literal")].layout.as_ref().unwrap();
            assert_eq!(literal_layout.gap, 13.0);
            assert_eq!(literal_layout.padding, [71.0, 62.0, 53.0, 44.0]);
            let node = scene.nodes.get_mut(&NodeId::from("literal")).unwrap();
            let layout = node.layout.as_mut().unwrap();
            layout.gap_token = Some("bespoke.margin".to_owned());
            layout.padding_token = Some("bespoke.margin".to_owned());
            if let NodeKind::Text(text) = &mut node.kind {
                text.style_token = Some("authored.style".to_owned());
            }
            // Bindings suppress only missing-binding governance. Their validity
            // and numeric precedence still belong to canonical token resolution.
            let bound = validate_scene_brand_governance(&scene, &kit, strictness.clone());
            assert!(!bound.iter().any(|d| d.code == "LUMB0805" || d.code == "LUMB0806"));
            let resolved = resolve_scene_tokens(&scene, &resolution_kit, &TokenResolutionOptions::default());
            let layout = resolved.scene.nodes[&NodeId::from("literal")].layout.as_ref().unwrap();
            if empty {
                assert_eq!(layout.padding, [71.0, 62.0, 53.0, 44.0]);
                assert!(resolved.diagnostics.iter().any(|d| d.code == "LUMB0301"));
            } else {
                assert_eq!(layout.gap, 19.0);
                assert_eq!(layout.padding, [19.0; 4]);
            }
        }
    }
}

#[test]
fn compatibility_report_flags_removed_tokens_and_assets() {
    let from = platform_default_brand_kit().unwrap();
    let mut to = from.clone();
    to.version = 2;
    to.tokens.colors.remove("surface.brand");
    to.tokens.typography.remove("type.headline");
    to.assets.fonts.remove("brand");

    let report = compare_brand_kit_compatibility(&from, &to);

    assert_eq!(report.status, BrandCompatibilityStatus::MigrationRequired);
    assert!(report
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0814"));
    assert!(report
        .token_changes
        .iter()
        .any(|change| change.path == "surface.brand"));
    assert!(report
        .token_changes
        .iter()
        .any(|change| change.path == "brand"));
}

#[test]
fn compatibility_report_flags_removed_mode_values() {
    let from = platform_default_brand_kit().unwrap();
    let mut to = from.clone();
    to.version = 2;
    to.modes
        .axes
        .get_mut("medium")
        .unwrap()
        .retain(|value| value != "print");

    let report = compare_brand_kit_compatibility(&from, &to);

    assert_eq!(report.status, BrandCompatibilityStatus::MigrationRequired);
    assert!(report
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0813"
            && diagnostic.message.contains("medium.print")));
    assert!(report.token_changes.iter().any(|change| {
        change.path == "mode.medium.print" && change.kind == TokenChangeKind::ModeCoverageChanged
    }));
}

#[test]
fn resolver_materializes_scene_tokens_without_renderer_semantics() {
    let brand_kit = acme_brand_kit();
    let scene = tokenized_scene(&brand_kit);

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());

    assert!(
        report
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "{:#?}",
        report.diagnostics
    );
    assert_eq!(report.operations.len(), 3);
    assert!(matches!(report.operations[0], Operation::UpdatePage { .. }));

    let page = report.scene.pages.get(&PageId::from("page_brand")).unwrap();
    assert!(matches!(
        page.background[0].paint,
        Paint::Solid {
            color: Color::Hex { .. }
        }
    ));

    let rect = report.scene.nodes.get(&NodeId::from("node_card")).unwrap();
    assert_eq!(rect.size.width, Dimension::Fixed(24.0));
    assert_eq!(rect.size.height, Dimension::Fixed(12.0));
    assert_eq!(rect.strokes[0].width, 2.0);
    assert!(rect.strokes[0].width_token.is_none());
    assert_eq!(rect.corner.top_left, 8.0);
    assert!(rect.corner.token.is_none());
    assert_eq!(rect.opacity, 0.72);
    assert!(rect.opacity_token.is_none());
    assert_eq!(rect.layout.as_ref().unwrap().gap, 16.0);
    assert!(rect.layout.as_ref().unwrap().gap_token.is_none());

    let headline = report
        .scene
        .nodes
        .get(&NodeId::from("node_headline"))
        .unwrap();
    let NodeKind::Text(text) = &headline.kind else {
        panic!("expected text node");
    };
    assert_eq!(text.font_family, "Inter");
    assert_eq!(text.font_size, 32.0);
    assert_eq!(text.font_weight, 800);
    assert!(text.style_token.is_none());
    assert_eq!(headline.fills.len(), 1);
    assert_eq!(
        headline.fills[0].id,
        PaintId::from("paint_headline_existing")
    );
    assert!(matches!(
        headline.fills[0].paint,
        Paint::Solid {
            color: Color::Hex { .. }
        }
    ));
}

#[test]
fn a6b_span_token_fill_resolves_like_a_node_fill() {
    // D8: a $token span fill joins the resolution walk exactly like a node
    // fill — it materializes to a Solid, and its token reference is collected.
    let brand_kit = acme_brand_kit();
    let mut scene = tokenized_scene(&brand_kit);
    {
        let headline = scene.nodes.get_mut(&NodeId::from("node_headline")).unwrap();
        let NodeKind::Text(text) = &mut headline.kind else {
            panic!("expected text node");
        };
        text.content = "Brand headline".to_owned();
        text.spans = vec![TextSpan {
            start: 0,
            end: 5,
            fill: Some(Paint::Token {
                token: "surface.brand".to_owned(),
            }),
            font_weight: None,
            underline: None,
            strikethrough: None,
            italic: None,
        }];
    }

    // The span's token is collected as a scene reference.
    let references = collect_scene_token_references(&scene);
    assert!(
        references.iter().any(|r| r.token == "surface.brand"
            && r.field.contains("span")),
        "span fill token is collected: {references:#?}"
    );

    // Resolution materializes the span fill to a Solid hex (bindings consumed).
    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());
    let headline = report
        .scene
        .nodes
        .get(&NodeId::from("node_headline"))
        .unwrap();
    let NodeKind::Text(text) = &headline.kind else {
        panic!("expected text node");
    };
    assert!(
        matches!(
            text.spans[0].fill,
            Some(Paint::Solid {
                color: Color::Hex { .. }
            })
        ),
        "span fill resolved to Solid: {:?}",
        text.spans[0].fill
    );
}

#[test]
fn resolver_stores_translucent_oklch_as_css_alpha_last_hex() {
    let mut brand_kit = acme_brand_kit();
    brand_kit.tokens.colors.insert(
        "surface.brand".to_owned(),
        color_token(ColorTokenValue::Oklch {
            l: 1.0,
            c: 0.0,
            h: 0.0,
            alpha: 0.5,
        }),
    );
    let scene = tokenized_scene(&brand_kit);

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());

    let page = report.scene.pages.get(&PageId::from("page_brand")).unwrap();
    let Paint::Solid {
        color: Color::Hex { value },
    } = &page.background[0].paint
    else {
        panic!("expected resolved solid hex paint");
    };
    assert_eq!(value, "#FFFFFF80");
}

#[test]
fn resolver_uses_brand_kit_mode_defaults_when_options_omit_mode() {
    let mut brand_kit = acme_brand_kit();
    brand_kit
        .modes
        .defaults
        .insert("theme".to_owned(), "dark".to_owned());
    brand_kit
        .tokens
        .colors
        .get_mut("surface.brand")
        .unwrap()
        .value
        .modes
        .insert(
            "theme.dark".to_owned(),
            ColorTokenValue::Hex {
                value: "#D9F7FB".to_owned(),
            },
        );
    let scene = tokenized_scene(&brand_kit);

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());

    let page = report.scene.pages.get(&PageId::from("page_brand")).unwrap();
    let Paint::Solid {
        color: Color::Hex { value },
    } = &page.background[0].paint
    else {
        panic!("expected resolved solid hex paint");
    };
    assert_eq!(value, "#D9F7FB");
}

#[test]
fn deserialized_empty_mode_keeps_brand_defaults_active() {
    let mut brand_kit = acme_brand_kit();
    brand_kit
        .modes
        .defaults
        .insert("theme".to_owned(), "dark".to_owned());
    brand_kit
        .tokens
        .colors
        .get_mut("surface.brand")
        .unwrap()
        .value
        .modes
        .insert(
            "theme.dark".to_owned(),
            ColorTokenValue::Hex {
                value: "#D9F7FB".to_owned(),
            },
        );
    let scene = tokenized_scene(&brand_kit);
    let mode: BrandMode = serde_json::from_str("{}").unwrap();
    assert!(mode.values.is_empty());

    let report = resolve_scene_tokens(
        &scene,
        &brand_kit,
        &TokenResolutionOptions {
            mode,
            ..TokenResolutionOptions::default()
        },
    );

    let page = report.scene.pages.get(&PageId::from("page_brand")).unwrap();
    let Paint::Solid {
        color: Color::Hex { value },
    } = &page.background[0].paint
    else {
        panic!("expected resolved solid hex paint");
    };
    assert_eq!(value, "#D9F7FB");
}

#[test]
fn percent_number_tokens_are_domain_safe() {
    let mut geometry_kit = acme_brand_kit();
    geometry_kit.tokens.spacing.insert(
        "space.xl".to_owned(),
        number_with_unit(50.0, NumberUnit::Percent),
    );
    let geometry_scene = tokenized_scene(&geometry_kit);

    let geometry_report = resolve_scene_tokens(
        &geometry_scene,
        &geometry_kit,
        &TokenResolutionOptions::default(),
    );

    assert!(geometry_report
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0313"));
    assert_eq!(
        geometry_report.scene.nodes[&NodeId::from("node_card")]
            .size
            .width,
        Dimension::Token {
            token: "space.xl".to_owned()
        }
    );

    let mut opacity_kit = acme_brand_kit();
    opacity_kit.tokens.opacity.insert(
        "opacity.subtle".to_owned(),
        number_with_unit(50.0, NumberUnit::Percent),
    );
    let opacity_scene = tokenized_scene(&opacity_kit);

    let opacity_report = resolve_scene_tokens(
        &opacity_scene,
        &opacity_kit,
        &TokenResolutionOptions::default(),
    );

    assert!(opacity_report
        .diagnostics
        .iter()
        .all(|diagnostic| diagnostic.code != "LUMB0313"));
    assert_eq!(
        opacity_report.scene.nodes[&NodeId::from("node_card")].opacity,
        0.5
    );
}

#[test]
fn styles_compiler_generates_mode_ready_catalog_tokens() {
    let source = r#"
        color primary = color(#2F6C70)
        spacing space = number(0,4,8,16,24)
        radius radius = number(0,4,8)
        alias surface.brand = $primary.mid
        typography headline = typography(Inter,32,800,$surface.brand)
        font brand = font(Inter,Arial|sans-serif)
    "#;

    let brand_kit = compile_styles_brand_kit(
        source,
        BrandKitId::from("brand_kit_styles"),
        1,
        "Styles Brand",
    )
    .expect("styles source compiles");

    assert!(brand_kit.tokens.colors.contains_key("primary.50"));
    assert!(brand_kit.tokens.colors.contains_key("primary.intense"));
    assert!(brand_kit.tokens.spacing.contains_key("space.lg"));
    assert!(brand_kit.tokens.radii.contains_key("radius.sm"));
    assert!(brand_kit.tokens.aliases.contains_key("surface.brand"));
    assert!(brand_kit.tokens.typography.contains_key("headline"));
    assert!(brand_kit.assets.fonts.contains_key("brand"));
}

#[test]
fn styles_compiler_expands_compact_program_to_product_ready_brand_kit() {
    let brand_kit = compile_styles_brand_kit(
        VALID_INSIGHT_HEALTH_STYLES,
        BrandKitId::from("unused_input_id"),
        1,
        "Input Name",
    )
    .expect("product-ready styles source compiles");

    assert_eq!(brand_kit.id, BrandKitId::from("brand_kit_insight_health"));
    assert_eq!(brand_kit.version, 4);
    assert_eq!(brand_kit.name, "Insight Health");
    assert_eq!(
        brand_kit.approval_status,
        BrandApprovalStatus::GeneratedUnreviewed
    );
    assert!(brand_kit.compatibility_policy.require_product_ready_tokens);

    let product_ready = validate_brand_kit_product_ready(&brand_kit);
    assert!(
        product_ready
            .iter()
            .all(|diagnostic| diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "{product_ready:#?}"
    );

    assert!(brand_kit.tokens.colors.contains_key("palette.primary.700"));
    assert!(brand_kit.tokens.colors.contains_key("surface.brand"));
    assert!(brand_kit.tokens.spacing.contains_key("space.16"));
    assert!(brand_kit.tokens.radii.contains_key("radius.card"));
    assert!(brand_kit
        .tokens
        .stroke_widths
        .contains_key("stroke.width.focus"));
    assert!(brand_kit.tokens.opacity.contains_key("opacity.scrim"));
    assert!(brand_kit.tokens.typography.contains_key("type.headline"));
    assert!(brand_kit.tokens.typography.contains_key("type.body"));
    assert!(brand_kit.tokens.assets.contains_key("logo.primary"));
    assert_eq!(
        brand_kit.assets.fonts["brand"].family,
        "Source Sans 3".to_owned()
    );
    assert_eq!(
        brand_kit.assets.fonts["brand"].fallback_stack,
        vec!["Arial".to_owned(), "sans-serif".to_owned()]
    );
    assert_eq!(brand_kit.assets.logos["primary"].min_size, Some(48.0));
    assert_eq!(brand_kit.assets.logos["primary"].clearspace, Some(16.0));
    assert!(brand_kit
        .tokens
        .assets
        .contains_key("asset.illustration.primary"));
    assert!(brand_kit.tokens.assets.contains_key("asset.icon.primary"));
    assert!(brand_kit.tokens.assets.contains_key("asset.texture.subtle"));
    let illustration = &brand_kit.assets.images["illustration.primary"];
    assert_eq!(
        illustration.asset_id,
        AssetId::from("asset_healthcare_card_svg")
    );
    assert_eq!(illustration.role, "spot_illustration");
    assert_eq!(illustration.mime_type.as_deref(), Some("image/svg+xml"));
    assert!(illustration.style_tags.contains(&"healthcare".to_owned()));
    assert!(illustration
        .allowed_contexts
        .contains(&"feature_card".to_owned()));
    assert!(illustration
        .preferred_color_tokens
        .contains(&"palette.primary.700".to_owned()));
    assert_eq!(illustration.recolor_allowed, Some(true));
    assert_eq!(illustration.crop_allowed, Some(false));
    assert_eq!(
        illustration.license.as_ref().map(|license| &license.name),
        Some(&"client_owned".to_owned())
    );
    assert_eq!(
        brand_kit.constraints.tone,
        vec![
            "clinical".to_owned(),
            "calm".to_owned(),
            "expert".to_owned()
        ]
    );
}

#[test]
fn styles_fixture_preflights_tokenized_scene_without_unresolved_tokens() {
    let brand_kit = compile_styles_brand_kit(
        VALID_INSIGHT_HEALTH_STYLES,
        BrandKitId::from("unused_input_id"),
        1,
        "Input Name",
    )
    .expect("styles fixture compiles");
    let mut scene = tokenized_scene(&brand_kit);
    scene
        .nodes
        .get_mut(&NodeId::from("node_headline"))
        .unwrap()
        .size = SizeSpec::fixed(640.0, 96.0);
    scene
        .pages
        .get_mut(&PageId::from("page_brand"))
        .unwrap()
        .size = lumen_core::normalize_page_size(lumen_core::PageSizeInput::new(
        720.0,
        320.0,
        Unit::Px,
        Some(PagePreset::Custom),
        Orientation::Landscape,
    ));

    let result = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());

    assert!(
        !result.has_errors(),
        "expected valid styles fixture to drive preflight, got {:#?}",
        result.diagnostics
    );
    assert!(!result.token_operations.is_empty());
}

#[test]
fn styles_fixture_authoring_summary_is_agent_ready() {
    let brand_kit = compile_styles_brand_kit(
        VALID_INSIGHT_HEALTH_STYLES,
        BrandKitId::from("unused_input_id"),
        1,
        "Input Name",
    )
    .expect("styles fixture compiles");

    let summary = summarize_brand_kit_for_authoring(&brand_kit);

    assert_eq!(summary.name, "Insight Health");
    assert_eq!(
        summary.approval_status,
        BrandApprovalStatus::GeneratedUnreviewed
    );
    assert!(summary.product_ready, "{:#?}", summary.diagnostics);
    assert!(summary.tone.contains(&"clinical".to_owned()));
    assert!(summary
        .imagery
        .iter()
        .any(|rule| rule.contains("healthcare")));
    assert!(summary
        .iconography
        .iter()
        .any(|rule| rule.contains("icons")));
    assert!(summary
        .assets
        .font_families
        .contains(&"Source Sans 3".to_owned()));
    assert!(summary
        .tokens
        .surface_tokens
        .contains(&"surface.brand".to_owned()));
    assert!(summary
        .tokens
        .typography_tokens
        .contains(&"type.cta".to_owned()));
    assert!(summary
        .tokens
        .stroke_width_tokens
        .contains(&"stroke.width.focus".to_owned()));
    assert!(summary
        .tokens
        .asset_tokens
        .contains(&"logo.primary".to_owned()));
    assert!(summary
        .tokens
        .asset_tokens
        .contains(&"asset.illustration.primary".to_owned()));
    assert!(summary
        .assets
        .image_asset_tokens
        .contains(&"asset.texture.subtle".to_owned()));
}

#[test]
fn styles_compiler_rejects_duplicate_generated_tokens() {
    let diagnostics = compile_styles_brand_kit(
        INVALID_DUPLICATE_TOKEN_STYLES,
        BrandKitId::from("brand_kit_duplicate"),
        1,
        "Duplicate",
    )
    .expect_err("duplicate generated token should fail");

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0701"
            && diagnostic.message.contains("styles line 2")
            && diagnostic.message.contains("duplicate color token")
    }));
}

#[test]
fn styles_compiler_rejects_invalid_mode_defaults() {
    let diagnostics = compile_styles_brand_kit(
        INVALID_MODE_DEFAULT_STYLES,
        BrandKitId::from("brand_kit_invalid_mode"),
        1,
        "Invalid Mode",
    )
    .expect_err("invalid mode default should fail");

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0701" && diagnostic.message.contains("default print is not listed")
    }));
}

#[test]
fn scene_brand_governance_flags_logo_on_disallowed_background() {
    let brand_kit = acme_brand_kit();
    let mut scene = Scene::new(DocumentId::from("doc_logo_background"), "Logo Background");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene
        .pages
        .insert(PageId::from("page_logo"), page("page_logo"));

    let logo = Node::new(
        NodeId::from("node_logo"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_logo_primary"),
            alt: Some("Acme Health logo".to_owned()),
        }),
    );
    scene
        .pages
        .get_mut(&PageId::from("page_logo"))
        .unwrap()
        .children = vec![logo.id.clone()];
    scene.nodes.insert(logo.id.clone(), logo);

    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0810"
            && diagnostic.severity == lumen_core::DiagnosticSeverity::Error
            && diagnostic.message.contains("surface.page")
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("surface.brand"))
    }));

    scene
        .pages
        .get_mut(&PageId::from("page_logo"))
        .unwrap()
        .background = vec![Fill {
        id: PaintId::from("page_bg"),
        paint: Paint::Token {
            token: "surface.brand".to_owned(),
        },
    }];
    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code != "LUMB0810"),
        "{diagnostics:#?}"
    );
}

#[test]
fn scene_brand_governance_flags_insufficient_text_contrast() {
    let mut brand_kit = acme_brand_kit();
    brand_kit.tokens.colors.insert(
        "surface.page".to_owned(),
        color_token(ColorTokenValue::Hex {
            value: "#FFFFFF".to_owned(),
        }),
    );
    let mut scene = Scene::new(DocumentId::from("doc_text_contrast"), "Text Contrast");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene
        .pages
        .insert(PageId::from("page_contrast"), page("page_contrast"));
    scene
        .pages
        .get_mut(&PageId::from("page_contrast"))
        .unwrap()
        .background = vec![Fill {
        id: PaintId::from("page_bg"),
        paint: Paint::Token {
            token: "surface.page".to_owned(),
        },
    }];

    let mut text = Node::new(
        NodeId::from("node_text"),
        NodeKind::Text(TextNode {
            content: "Book a consultation".to_owned(),
            font_size: 18.0,
            style_token: Some("type.body".to_owned()),
            ..TextNode::default()
        }),
    );
    text.size = SizeSpec::fixed(320.0, 48.0);
    text.fills = vec![Fill {
        id: PaintId::from("text_fill"),
        paint: Paint::Token {
            token: "text.inverse".to_owned(),
        },
    }];
    scene
        .pages
        .get_mut(&PageId::from("page_contrast"))
        .unwrap()
        .children = vec![text.id.clone()];
    scene.nodes.insert(text.id.clone(), text);

    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0807"
            && diagnostic.severity == lumen_core::DiagnosticSeverity::Error
            && diagnostic.message.contains("text contrast")
            && diagnostic.message.contains("surface.page")
    }));

    scene
        .pages
        .get_mut(&PageId::from("page_contrast"))
        .unwrap()
        .background = vec![Fill {
        id: PaintId::from("page_bg"),
        paint: Paint::Token {
            token: "surface.brand".to_owned(),
        },
    }];
    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code != "LUMB0807"),
        "{diagnostics:#?}"
    );
}

#[test]
fn scene_brand_governance_flags_logo_below_minimum_size() {
    let brand_kit = acme_brand_kit();
    let mut scene = logo_scene_on_allowed_background(&brand_kit);

    scene
        .nodes
        .get_mut(&NodeId::from("node_logo"))
        .unwrap()
        .size = SizeSpec::fixed(32.0, 96.0);

    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0809"
            && diagnostic.severity == lumen_core::DiagnosticSeverity::Error
            && diagnostic
                .message
                .contains("below the Brand Kit minimum 64.0px")
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("at least 64.0px"))
    }));

    scene
        .nodes
        .get_mut(&NodeId::from("node_logo"))
        .unwrap()
        .size = SizeSpec::fixed(64.0, 96.0);
    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code != "LUMB0809"),
        "{diagnostics:#?}"
    );
}

#[test]
fn scene_brand_governance_uses_computed_logo_size_when_available() {
    let brand_kit = acme_brand_kit();
    let mut scene = logo_scene_on_allowed_background(&brand_kit);
    let logo = scene.nodes.get_mut(&NodeId::from("node_logo")).unwrap();
    logo.size = SizeSpec::fixed(96.0, 96.0);
    logo.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 40.0,
            height: 80.0,
        },
        render_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 40.0,
            height: 80.0,
        },
        text_lines: Vec::new(),
    });

    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Strict);

    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMB0809"),
        "{diagnostics:#?}"
    );
}

#[test]
fn scene_brand_governance_flags_print_transparency() {
    let brand_kit = acme_brand_kit();
    let mut scene = Scene::new(
        DocumentId::from("doc_print_transparency"),
        "Print Transparency",
    );
    scene.meta.medium = Some(Medium::Print);
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene
        .pages
        .insert(PageId::from("page_print"), page("page_print"));

    let mut card = Node::new(NodeId::from("node_print_card"), NodeKind::Rect);
    card.opacity_token = Some("opacity.subtle".to_owned());
    scene
        .pages
        .get_mut(&PageId::from("page_print"))
        .unwrap()
        .children = vec![card.id.clone()];
    scene.nodes.insert(card.id.clone(), card);

    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Advisory);

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMB0811"
            && diagnostic.severity == lumen_core::DiagnosticSeverity::Error
            && diagnostic.message.contains("opacity.subtle")
            && diagnostic
                .hint
                .as_deref()
                .is_some_and(|hint| hint.contains("opacity.emphasis"))
    }));

    scene.meta.medium = Some(Medium::Digital);
    let diagnostics =
        validate_scene_brand_governance(&scene, &brand_kit, BrandGovernanceStrictness::Advisory);

    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code != "LUMB0811"),
        "{diagnostics:#?}"
    );
}

#[test]
fn strict_mode_rejects_bare_tokenizable_styles() {
    let brand_kit = acme_brand_kit();
    let mut scene = Scene::new(DocumentId::from("doc_bare"), "Bare");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene
        .pages
        .insert(PageId::from("page_bare"), page("page_bare"));

    let mut node = Node::new(NodeId::from("node_bare"), NodeKind::Rect);
    node.fills = vec![Fill {
        id: PaintId::from("paint_bare"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#ff0000".to_owned(),
            },
        },
    }];
    scene
        .pages
        .get_mut(&PageId::from("page_bare"))
        .unwrap()
        .children = vec![node.id.clone()];
    scene.nodes.insert(node.id.clone(), node);

    let text = Node::new(
        NodeId::from("node_bare_text"),
        NodeKind::Text(TextNode {
            content: "Bare typography".to_owned(),
            font_family: "Times".to_owned(),
            font_size: 18.0,
            font_weight: 400,
            align: TextAlign::Left,
            style_token: None,
            ..TextNode::default()
        }),
    );
    scene
        .pages
        .get_mut(&PageId::from("page_bare"))
        .unwrap()
        .children
        .push(text.id.clone());
    scene.nodes.insert(text.id.clone(), text);

    let diagnostics = resolve_scene_tokens(
        &scene,
        &brand_kit,
        &TokenResolutionOptions {
            strictness: TokenStrictness::Explicit,
            ..TokenResolutionOptions::default()
        },
    )
    .diagnostics;

    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0500"));
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0506"));
}

#[test]
fn brand_validation_reports_alias_cycles_and_font_export_warnings() {
    let mut brand_kit = acme_brand_kit();
    brand_kit.tokens.colors.insert(
        "cycle.a".to_owned(),
        color_token(ColorTokenValue::Alias {
            token: "cycle.b".to_owned(),
        }),
    );
    brand_kit.tokens.colors.insert(
        "cycle.b".to_owned(),
        color_token(ColorTokenValue::Alias {
            token: "cycle.a".to_owned(),
        }),
    );
    brand_kit
        .assets
        .fonts
        .get_mut("brand")
        .unwrap()
        .license
        .embeddable = false;

    let diagnostics = validate_brand_kit(&brand_kit);

    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0202"));
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0613"));
}

#[test]
fn brand_validation_and_resolution_diagnose_missing_font_asset_refs() {
    let mut brand_kit = acme_brand_kit();
    set_headline_font_asset(&mut brand_kit, Some("missing_font"));
    let scene = tokenized_scene(&brand_kit);

    let validation = validate_brand_kit(&brand_kit);
    assert!(validation
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0413"));

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());
    assert!(report.operations.is_empty());
    assert!(report
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0413"));
}

#[test]
fn brand_validation_diagnoses_missing_typography_color_refs() {
    let mut brand_kit = acme_brand_kit();
    set_headline_color(&mut brand_kit, Some("missing.color"));

    let diagnostics = validate_brand_kit(&brand_kit);

    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0201"));
}

#[test]
fn brand_ref_mismatch_blocks_resolution() {
    let brand_kit = acme_brand_kit();
    let mut scene = tokenized_scene(&brand_kit);
    scene.meta.brand_kit = Some(lumen_core::BrandKitRef {
        id: BrandKitId::from("other_brand"),
        version: 99,
    });

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());

    assert!(report.operations.is_empty());
    assert_eq!(report.scene, scene);
    assert!(report
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMB0101"));
}

fn health_brand_seed() -> BrandSeed {
    BrandSeed {
        id: BrandKitId::from("brand_seed_health"),
        version: 3,
        name: "Insight Health".to_owned(),
        primary_color: "#075E68".to_owned(),
        description: Some("Professional healthcare automation brand".to_owned()),
        secondary_color: Some("#2F80ED".to_owned()),
        accent_color: Some("#16A34A".to_owned()),
        neutral_color: Some("#111827".to_owned()),
        preferred_fonts: vec!["Source Sans 3".to_owned(), "Inter".to_owned()],
        logo_refs: vec![BrandSeedLogoRef {
            logo_id: "primary".to_owned(),
            asset_id: AssetId::from("asset_insight_logo"),
            usage: LogoUsage::Primary,
            color_mode: LogoColorMode::FullColor,
            variant: Some("full_color".to_owned()),
            width: Some(160.0),
            height: Some(40.0),
        }],
        tone_words: vec![
            "clinical".to_owned(),
            "calm".to_owned(),
            "trustworthy".to_owned(),
        ],
        website_url: Some("https://insight.example".to_owned()),
        style_guide_asset_ids: vec![AssetId::from("asset_style_guide")],
        sources: vec![BrandSource::Manual {
            label: "seeded from product onboarding".to_owned(),
            confidence: 0.9,
        }],
        default_mode: BrandMode::default(),
    }
}

fn tokenized_scene(brand_kit: &BrandKit) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_brand"), "Brand Tokens");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    let mut page = page("page_brand");
    page.background = vec![Fill {
        id: PaintId::from("paint_page_bg"),
        paint: Paint::Token {
            token: "surface.brand".to_owned(),
        },
    }];
    page.children = vec![NodeId::from("node_card"), NodeId::from("node_headline")];
    scene.pages.insert(page.id.clone(), page);

    let mut card = Node::new(NodeId::from("node_card"), NodeKind::Rect);
    card.size = SizeSpec {
        width: Dimension::Token {
            token: "space.xl".to_owned(),
        },
        height: Dimension::Token {
            token: "space.md".to_owned(),
        },
    };
    card.fills = vec![Fill {
        id: PaintId::from("paint_card"),
        paint: Paint::Solid {
            color: Color::Token {
                token: "text.primary".to_owned(),
            },
        },
    }];
    card.strokes = vec![Stroke {
        width_token: Some("stroke.width.firm".to_owned()),
        ..Stroke::solid(
            PaintId::from("paint_card_stroke"),
            Paint::Token {
                token: "text.inverse".to_owned(),
            },
            0.0,
        )
    }];
    card.corner.token = Some("radius.md".to_owned());
    card.opacity_token = Some("opacity.subtle".to_owned());
    card.layout = Some(lumen_core::AutoLayoutProps {
        gap: 0.0,
        gap_token: Some("space.lg".to_owned()),
        padding: [0.0; 4],
        padding_token: Some("space.sm".to_owned()),
        grow: 0.0,
        ..lumen_core::AutoLayoutProps::default()
    });
    scene.nodes.insert(card.id.clone(), card);

    let mut headline = Node::new(
        NodeId::from("node_headline"),
        NodeKind::Text(TextNode {
            content: "Brand headline".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 16.0,
            font_weight: 400,
            align: TextAlign::Left,
            style_token: Some("type.headline".to_owned()),
            ..TextNode::default()
        }),
    );
    headline.size = SizeSpec::fixed(240.0, 48.0);
    headline.fills = vec![Fill {
        id: PaintId::from("paint_headline_existing"),
        paint: Paint::Token {
            token: "text.primary".to_owned(),
        },
    }];
    scene.nodes.insert(headline.id.clone(), headline);
    scene
}

fn logo_scene_on_allowed_background(brand_kit: &BrandKit) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_logo_size"), "Logo Size");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    let mut page = page("page_logo");
    page.background = vec![Fill {
        id: PaintId::from("page_bg"),
        paint: Paint::Token {
            token: "surface.brand".to_owned(),
        },
    }];
    page.children = vec![NodeId::from("node_logo")];
    scene.pages.insert(page.id.clone(), page);

    let mut logo = Node::new(
        NodeId::from("node_logo"),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_logo_primary"),
            alt: Some("Acme Health logo".to_owned()),
        }),
    );
    logo.size = SizeSpec::fixed(96.0, 96.0);
    scene.nodes.insert(logo.id.clone(), logo);
    scene
}

#[test]
fn text_color_is_corrected_for_surface_contrast() {
    // P1.1: type.headline bakes in text.inverse (white), for a hero on a dark/brand
    // surface. On a LIGHT surface that is invisible, so resolution must flip it to a
    // dark, legible color; on a DARK surface it must stay light.
    let brand_kit = platform_default_brand_kit().unwrap();

    fn hex_rgb(value: &str) -> (f64, f64, f64) {
        let v = value.trim_start_matches('#');
        let parse = |s: &str| u8::from_str_radix(s, 16).unwrap() as f64 / 255.0;
        (parse(&v[0..2]), parse(&v[2..4]), parse(&v[4..6]))
    }
    fn brightness((r, g, b): (f64, f64, f64)) -> f64 {
        0.299 * r + 0.587 * g + 0.114 * b
    }

    let headline_color_on = |surface_hex: &str| -> (f64, f64, f64) {
        let mut scene = Scene::new(DocumentId::from("doc_contrast"), "Contrast");
        scene.meta.brand_kit = Some(brand_kit.brand_ref());
        scene.pages.insert(PageId::from("page"), page("page"));
        let mut artboard = Node::new(NodeId::from("artboard"), NodeKind::Frame);
        artboard.fills = vec![Fill {
            id: PaintId::from("bg"),
            paint: Paint::Solid {
                color: Color::Hex {
                    value: surface_hex.to_owned(),
                },
            },
        }];
        let headline = Node::new(
            NodeId::from("headline"),
            NodeKind::Text(TextNode {
                content: "Your visit is confirmed.".to_owned(),
                style_token: Some("type.headline".to_owned()),
                ..TextNode::default()
            }),
        );
        artboard.children = vec![headline.id.clone()];
        scene.pages.get_mut(&PageId::from("page")).unwrap().children = vec![artboard.id.clone()];
        scene.nodes.insert(headline.id.clone(), headline);
        scene.nodes.insert(artboard.id.clone(), artboard);

        let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());
        let headline = report.scene.nodes.get(&NodeId::from("headline")).unwrap();
        let Paint::Solid {
            color: Color::Hex { value },
        } = &headline.fills[0].paint
        else {
            panic!(
                "expected a resolved solid hex text fill, got {:?}",
                headline.fills
            );
        };
        hex_rgb(value)
    };

    let on_light = headline_color_on("#FFFFFF");
    assert!(
        brightness(on_light) < 0.5,
        "headline on a light surface must resolve to a dark color, got {on_light:?}"
    );

    let on_dark = headline_color_on("#0B1220");
    assert!(
        brightness(on_dark) > 0.5,
        "headline on a dark surface must resolve to a light color, got {on_dark:?}"
    );
}

// ---- Fill precedence: an author's explicit text fill beats the role's color ----
//
// A type role bakes one color (the platform default `type.display` bakes
// `text.primary`). That color is a DEFAULT for text carrying no color of its
// own. Resolution used to push it over `fills[0]` unconditionally, so an author
// who wrote `fill($text.inverse)` on a branded ground got the role's dark text
// instead — and the P1.1 correction did not rescue it, because the pair cleared
// the lenient 3.0 floor. These pin the precedence, not the threshold.

/// A mid-tone branded ground chosen so the role's baked `text.primary`
/// (`#111827`) CLEARS the P1.1 floor (~3.1:1) while the author's
/// `text.inverse` white is markedly better (~5.7:1). That is the shape of the
/// live defect: the correction had no reason to fire, so the clobber stood.
const BRAND_GROUND: &str = "#7C3AED";

/// Resolve one text node under the platform default kit and report the fill
/// entry it ends up with. The node sits inside an artboard painted
/// `surface_hex` so P1.1's surface tracking has a real ground to measure.
fn resolved_text_fill(
    style_token: Option<&str>,
    author_fill: Option<Paint>,
    surface_hex: &str,
) -> (PaintId, String) {
    let brand_kit = platform_default_brand_kit().unwrap();
    let mut scene = Scene::new(DocumentId::from("doc_fill_precedence"), "Fill Precedence");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene.pages.insert(PageId::from("page"), page("page"));

    let mut artboard = Node::new(NodeId::from("artboard"), NodeKind::Frame);
    artboard.fills = vec![Fill {
        id: PaintId::from("bg"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: surface_hex.to_owned(),
            },
        },
    }];

    let mut headline = Node::new(
        NodeId::from("headline"),
        NodeKind::Text(TextNode {
            content: "Clinical notes write themselves.".to_owned(),
            style_token: style_token.map(str::to_owned),
            ..TextNode::default()
        }),
    );
    if let Some(paint) = author_fill {
        // The id the DSL compiler mints for an authored `fill(...)`.
        headline.fills = vec![Fill {
            id: PaintId::from("paint_headline_fill_1"),
            paint,
        }];
    }

    artboard.children = vec![headline.id.clone()];
    scene.pages.get_mut(&PageId::from("page")).unwrap().children = vec![artboard.id.clone()];
    scene.nodes.insert(headline.id.clone(), headline);
    scene.nodes.insert(artboard.id.clone(), artboard);

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());
    let headline = report.scene.nodes.get(&NodeId::from("headline")).unwrap();
    assert_eq!(
        headline.fills.len(),
        1,
        "expected exactly one text fill, got {:#?}",
        headline.fills
    );
    let Paint::Solid {
        color: Color::Hex { value },
    } = &headline.fills[0].paint
    else {
        panic!(
            "expected a resolved solid hex text fill, got {:#?}",
            headline.fills
        );
    };
    (headline.fills[0].id.clone(), value.to_ascii_uppercase())
}

#[test]
fn author_token_fill_beats_the_type_role_color() {
    // The live repro (run_bcdcf3e484fd48b7805c8eb561a64854, iterations 001-003):
    // `style($type.display) fill($text.inverse)` on the brand ground rendered
    // `#000000` because the role's baked `text.primary` overwrote the author's
    // white. The author's token must win and resolve through the ordinary fill
    // path instead.
    let (fill_id, hex) = resolved_text_fill(
        Some("type.display"),
        Some(Paint::Token {
            token: "text.inverse".to_owned(),
        }),
        BRAND_GROUND,
    );

    assert_eq!(
        fill_id,
        PaintId::from("paint_headline_fill_1"),
        "the author's own fill entry must survive resolution"
    );
    assert_eq!(
        hex, "#FFFFFF",
        "explicit fill($text.inverse) must beat the role's baked text.primary"
    );
}

#[test]
fn author_literal_hex_fill_beats_the_type_role_color() {
    // Same rule for a literal color: the author said white, they get white.
    let (fill_id, hex) = resolved_text_fill(
        Some("type.display"),
        Some(Paint::Solid {
            color: Color::Hex {
                value: "#FFFFFF".to_owned(),
            },
        }),
        BRAND_GROUND,
    );

    assert_eq!(fill_id, PaintId::from("paint_headline_fill_1"));
    assert_eq!(
        hex, "#FFFFFF",
        "an explicit literal fill must beat the role's baked text.primary"
    );
}

#[test]
fn text_with_no_author_fill_still_takes_the_role_color_and_p1_1_correction() {
    // The path P1.1 was built for is untouched: with no author fill, the role's
    // color lands in a role-owned fill entry, corrected only when the pair is
    // genuinely illegible.
    let (fill_id, on_light) = resolved_text_fill(Some("type.display"), None, "#FFFFFF");
    assert_eq!(
        fill_id,
        PaintId::from("headline_text_fill"),
        "the role synthesizes its own fill entry when the author wrote none"
    );
    assert_eq!(
        on_light, "#111827",
        "text.primary on white clears the floor, so the role's color stands"
    );

    // Same ground as the two author-fill tests above. With no author fill the
    // role's dark color survives here, because it clears the lenient 3.0 floor
    // — which is exactly why the old unconditional clobber went unnoticed.
    let (_, on_brand) = resolved_text_fill(Some("type.display"), None, BRAND_GROUND);
    assert_eq!(
        on_brand, "#111827",
        "the role's color still applies when the author named none"
    );

    let (_, on_dark) = resolved_text_fill(Some("type.display"), None, "#0B1220");
    assert_eq!(
        on_dark, "#FFFFFF",
        "text.primary on a near-black ground is illegible, so P1.1 flips it"
    );
}

#[test]
fn authored_dsl_hero_keeps_its_inverse_text_on_the_brand_ground() {
    // Run-2's exact shape, end to end through the DSL compiler: a branded
    // artboard whose every text child names both a type role and an explicit
    // $text.inverse fill. Before the precedence rule all three came back dark.
    let brand_kit = platform_default_brand_kit().unwrap();
    let source = concat!(
        "page hero size(1080,1080,px)\n",
        "  artboard fr p(0,0) s(1080,1080) fill($surface.brand)\n",
        "    eyebrow text \"Insight Health\" p(96,96) s(888,44) ",
        "style($type.eyebrow) fill($text.inverse)\n",
        "    headline text \"Clinical notes write themselves.\" p(96,200) s(888,240) ",
        "style($type.display) fill($text.inverse) wrap_text(true)\n",
        "    body text \"Stop documenting after the visit.\" p(96,480) s(888,120) ",
        "style($type.body) fill($text.inverse) wrap_text(true)\n",
    );

    let mut scene = Scene::new(DocumentId::from("doc_run2_hero"), "Run 2 Hero");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    let output = compile_dsl_into_scene(source, &mut scene);
    let dsl_errors = output
        .compile_output
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.diagnostic.severity == DiagnosticSeverity::Error)
        .collect::<Vec<_>>();
    assert!(dsl_errors.is_empty(), "{dsl_errors:#?}");
    assert!(
        output.operation_error.is_none(),
        "{:#?}",
        output.operation_error
    );

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());
    for node_id in ["eyebrow", "headline", "body"] {
        let node = report.scene.nodes.get(&NodeId::from(node_id)).unwrap();
        let Paint::Solid {
            color: Color::Hex { value },
        } = &node.fills[0].paint
        else {
            panic!(
                "{node_id}: expected a resolved solid hex fill, got {:#?}",
                node.fills
            );
        };
        assert_eq!(
            value.to_ascii_uppercase(),
            "#FFFFFF",
            "{node_id} authored fill($text.inverse) and must render white on $surface.brand"
        );
    }
}

fn page(id: &str) -> Page {
    Page {
        id: PageId::from(id),
        name: "Brand Page".to_owned(),
        size: PageSize {
            width: 320.0,
            height: 180.0,
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

fn set_headline_font_asset(brand_kit: &mut BrandKit, font_asset: Option<&str>) {
    let token = brand_kit
        .tokens
        .typography
        .get_mut("type.headline")
        .unwrap();
    if let TypographyTokenValue::Style {
        font_asset: current,
        ..
    } = &mut token.value.default
    {
        *current = font_asset.map(str::to_owned);
    } else {
        panic!("expected style typography token");
    }
}

fn set_headline_color(brand_kit: &mut BrandKit, color: Option<&str>) {
    let token = brand_kit
        .tokens
        .typography
        .get_mut("type.headline")
        .unwrap();
    if let TypographyTokenValue::Style { color: current, .. } = &mut token.value.default {
        *current = color.map(str::to_owned);
    } else {
        panic!("expected style typography token");
    }
}

fn acme_brand_kit() -> BrandKit {
    let mut colors = BTreeMap::new();
    colors.insert(
        "surface.brand".to_owned(),
        color_token(ColorTokenValue::Hex {
            value: "#004D5A".to_owned(),
        }),
    );
    colors.insert(
        "text.primary".to_owned(),
        color_token(ColorTokenValue::Hex {
            value: "#152326".to_owned(),
        }),
    );
    colors.insert(
        "text.inverse".to_owned(),
        color_token(ColorTokenValue::Hex {
            value: "#FFFFFF".to_owned(),
        }),
    );

    let mut spacing = BTreeMap::new();
    spacing.insert("space.sm".to_owned(), number(8.0));
    spacing.insert("space.md".to_owned(), number(12.0));
    spacing.insert("space.lg".to_owned(), number(16.0));
    spacing.insert("space.xl".to_owned(), number(24.0));

    let mut radii = BTreeMap::new();
    radii.insert("radius.md".to_owned(), number(8.0));

    let mut stroke_widths = BTreeMap::new();
    stroke_widths.insert("stroke.width.firm".to_owned(), number(2.0));

    let mut opacity = BTreeMap::new();
    opacity.insert(
        "opacity.subtle".to_owned(),
        NumberToken {
            value: ModeValue {
                default: NumberTokenValue::Number {
                    value: 0.72,
                    unit: NumberUnit::Ratio,
                },
                modes: BTreeMap::new(),
            },
            role: Some("visibility".to_owned()),
            description: None,
            provenance: None,
        },
    );

    let mut typography = BTreeMap::new();
    typography.insert(
        "type.headline".to_owned(),
        TypographyToken {
            value: ModeValue {
                default: TypographyTokenValue::Style {
                    font_family: "Inter".to_owned(),
                    font_size: 32.0,
                    font_weight: 800,
                    line_height: Some(1.1),
                    letter_spacing: Some(0.0),
                    color: Some("text.inverse".to_owned()),
                    font_asset: Some("brand".to_owned()),
                },
                modes: BTreeMap::new(),
            },
            role: Some("headline".to_owned()),
            description: None,
            provenance: None,
        },
    );

    let mut fonts = BTreeMap::new();
    fonts.insert(
        "brand".to_owned(),
        FontAsset {
            family: "Inter".to_owned(),
            source: AssetSource::System {
                family: "Inter".to_owned(),
            },
            faces: vec![FontFace {
                weight: 800,
                style: FontStyle::Normal,
                asset_id: None,
                source_url: None,
            }],
            fallback_stack: vec!["Arial".to_owned(), "sans-serif".to_owned()],
            scripts: vec!["latin".to_owned()],
            license: FontLicense {
                name: "open_font_license".to_owned(),
                embeddable: true,
                subsettable: true,
                source_url: None,
                restrictions: Vec::new(),
                basis: None,
            },
            provenance: None,
            metrics: None,
        },
    );

    let mut logos = BTreeMap::new();
    logos.insert(
        "primary".to_owned(),
        LogoAsset {
            variants: vec![LogoVariant {
                name: "full_color".to_owned(),
                asset_id: AssetId::from("asset_logo_primary"),
                color_mode: LogoColorMode::FullColor,
                width: Some(120.0),
                height: Some(32.0),
            }],
            usage: LogoUsage::Primary,
            min_size: Some(64.0),
            clearspace: Some(12.0),
            allowed_backgrounds: vec!["surface.brand".to_owned()],
            license: None,
            provenance: None,
            title: None,
            description: None,
            usage_note: None,
        },
    );

    BrandKit {
        id: BrandKitId::from("brand_kit_acme"),
        version: 1,
        name: "Acme Health".to_owned(),
        description: Some("Healthcare ABM demo brand".to_owned()),
        sources: vec![BrandSource::Manual {
            label: "manual".to_owned(),
            confidence: 1.0,
        }],
        provenance: None,
        approval_status: BrandApprovalStatus::Draft,
        compatibility_policy: BrandCompatibilityPolicy::default(),
        modes: BrandModeSpec::default(),
        tokens: TokenCatalog {
            colors,
            typography,
            numbers: BTreeMap::new(),
            spacing,
            radii,
            stroke_widths,
            opacity,
            shadows: BTreeMap::new(),
            effects: BTreeMap::new(),
            assets: BTreeMap::new(),
            aliases: BTreeMap::from([(
                "color.surface".to_owned(),
                TokenAlias {
                    token: "surface.brand".to_owned(),
                    description: None,
                },
            )]),
            styles: BTreeMap::new(),
        },
        assets: BrandAssets {
            fonts,
            logos,
            images: BTreeMap::new(),
        },
        constraints: BrandConstraints {
            allow_gradients: false,
            tone: vec!["calm".to_owned(), "clinical".to_owned()],
            imagery: vec!["people-first".to_owned()],
            iconography: vec!["line icons".to_owned()],
            accessibility_notes: vec!["Prefer AA contrast".to_owned()],
            print_constraints: vec!["Avoid unlicensed font embedding".to_owned()],
            contrast_pairs: vec![ContrastPair {
                foreground: "text.inverse".to_owned(),
                background: "surface.brand".to_owned(),
                min_ratio: 4.5,
            }],
        },
    }
}

fn compile_and_preflight_template(
    name: &str,
    source: &str,
    brand_kit: &BrandKit,
    page_id: &PageId,
) -> Scene {
    let mut scene = Scene::new(
        DocumentId::from(format!("doc_{name}_{}", brand_kit.id.as_str())),
        format!("Phase C {name}"),
    );
    let output = compile_dsl_into_scene(source, &mut scene);
    let dsl_errors = output
        .compile_output
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.diagnostic.severity == DiagnosticSeverity::Error)
        .collect::<Vec<_>>();
    assert!(
        dsl_errors.is_empty(),
        "{name} failed DSL compile for {}: {:#?}",
        brand_kit.id.as_str(),
        dsl_errors
    );
    assert!(
        output.operation_error.is_none(),
        "{name} failed operation application for {}: {:#?}",
        brand_kit.id.as_str(),
        output.operation_error
    );
    assert!(
        scene.pages.contains_key(page_id),
        "{name} did not create expected page {page_id}"
    );

    let result = preflight_scene(scene, Some(brand_kit), PreflightOptions::default());
    let preflight_errors = result
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
        .collect::<Vec<_>>();
    assert!(
        preflight_errors.is_empty(),
        "{name} failed preflight for {}: {:#?}",
        brand_kit.id.as_str(),
        preflight_errors
    );
    result.scene
}

fn first_solid_fill_hex(scene: &Scene, node_id: &NodeId) -> Option<String> {
    let node = scene.nodes.get(node_id)?;
    let fill = node.fills.first()?;
    match &fill.paint {
        Paint::Solid {
            color: Color::Hex { value },
        } => Some(value.clone()),
        _ => None,
    }
}

fn color_token(value: ColorTokenValue) -> ColorToken {
    ColorToken {
        value: ModeValue {
            default: value,
            modes: BTreeMap::new(),
        },
        role: None,
        description: None,
        provenance: None,
    }
}

fn number(value: f64) -> NumberToken {
    number_with_unit(value, NumberUnit::Px)
}

fn number_with_unit(value: f64, unit: NumberUnit) -> NumberToken {
    NumberToken {
        value: ModeValue {
            default: NumberTokenValue::Number { value, unit },
            modes: BTreeMap::new(),
        },
        role: None,
        description: None,
        provenance: None,
    }
}

#[test]
fn font_size_step_token_overrides_role_default_size() {
    // P1.4: a `$type.size.*` step token overrides the role's baked-in size, while
    // the role still supplies weight / color / line-height. This is how a 1080²
    // social hero gets a dominant size without abandoning the headline role.
    let brand_kit = platform_default_brand_kit().unwrap();
    let mut scene = Scene::new(DocumentId::from("doc_typesize"), "TypeSize");
    scene.meta.brand_kit = Some(brand_kit.brand_ref());
    scene.pages.insert(PageId::from("page_ts"), page("page_ts"));

    // Role headline (default 56, weight 800) + explicit 7xl (80) size override.
    let hero = Node::new(
        NodeId::from("node_hero"),
        NodeKind::Text(TextNode {
            content: "Meet Magic-Doc.".to_owned(),
            style_token: Some("type.headline".to_owned()),
            font_size_token: Some("type.size.7xl".to_owned()),
            ..TextNode::default()
        }),
    );
    // No role, just a size step (6xl = 64) — resolves with no style_token present.
    let bare = Node::new(
        NodeId::from("node_bare"),
        NodeKind::Text(TextNode {
            content: "64".to_owned(),
            font_size_token: Some("type.size.6xl".to_owned()),
            ..TextNode::default()
        }),
    );
    scene.nodes.insert(hero.id.clone(), hero);
    scene.nodes.insert(bare.id.clone(), bare);
    scene
        .pages
        .get_mut(&PageId::from("page_ts"))
        .unwrap()
        .children = vec![NodeId::from("node_hero"), NodeId::from("node_bare")];

    let report = resolve_scene_tokens(&scene, &brand_kit, &TokenResolutionOptions::default());
    assert!(
        report
            .diagnostics
            .iter()
            .all(|d| d.severity != lumen_core::DiagnosticSeverity::Error),
        "{:#?}",
        report.diagnostics
    );

    let hero = report.scene.nodes.get(&NodeId::from("node_hero")).unwrap();
    let NodeKind::Text(text) = &hero.kind else {
        panic!("expected text node");
    };
    // Override wins over the role's default 56pt.
    assert_eq!(text.font_size, 80.0);
    // Role still supplied the weight (headline = 800), proving it's a superset,
    // not a replacement.
    assert_eq!(text.font_weight, 800);
    assert!(text.style_token.is_none());
    assert!(text.font_size_token.is_none());

    let bare = report.scene.nodes.get(&NodeId::from("node_bare")).unwrap();
    let NodeKind::Text(text) = &bare.kind else {
        panic!("expected text node");
    };
    assert_eq!(text.font_size, 64.0);
    assert!(text.font_size_token.is_none());
}
