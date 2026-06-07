use lumen_core::{
    compile_styles_brand_kit, resolve_scene_tokens, validate_brand_kit, AssetId, AssetSource,
    BrandAssets, BrandConstraints, BrandKit, BrandKitId, BrandMode, BrandModeSpec, BrandSource,
    Color, ColorToken, ColorTokenValue, ContrastPair, Dimension, DocumentId, Fill, FontAsset,
    FontFace, FontLicense, FontStyle, LogoAsset, LogoColorMode, LogoUsage, LogoVariant, ModeValue,
    Node, NodeId, NodeKind, NumberToken, NumberTokenValue, NumberUnit, Operation, Orientation,
    Page, PageId, PagePreset, PageSize, Paint, PaintId, Scene, SizeSpec, Stroke, TextAlign,
    TextNode, TokenAlias, TokenCatalog, TokenResolutionOptions, TokenStrictness, TypographyToken,
    TypographyTokenValue, Unit,
};
use std::collections::BTreeMap;

const ACME_BRAND_KIT: &str = include_str!("../fixtures/brand_kits/acme_full.json");

#[test]
fn brand_kit_fixture_round_trips_and_validates() {
    let brand_kit: BrandKit = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    let diagnostics = validate_brand_kit(&brand_kit);

    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != lumen_core::DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );

    let json = serde_json::to_string_pretty(&brand_kit).unwrap();
    let decoded: BrandKit = serde_json::from_str(&json).unwrap();
    assert_eq!(brand_kit, decoded);
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
        id: PaintId::from("paint_card_stroke"),
        paint: Paint::Token {
            token: "text.inverse".to_owned(),
        },
        width: 0.0,
        width_token: Some("stroke.width.firm".to_owned()),
    }];
    card.corner.token = Some("radius.md".to_owned());
    card.opacity_token = Some("opacity.subtle".to_owned());
    card.layout = Some(lumen_core::AutoLayoutProps {
        gap: 0.0,
        gap_token: Some("space.lg".to_owned()),
        padding: [0.0; 4],
        padding_token: Some("space.sm".to_owned()),
        grow: 0.0,
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
            },
            provenance: None,
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
