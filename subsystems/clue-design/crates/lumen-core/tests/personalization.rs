//! Phase G personalization runtime conformance (slice G0 onward).
//!
//! G0 pins the fixture contract: a finalized mailer template revision plus
//! three binding sets (nominal, worst-case lengths, missing optional
//! content). The ignored tests name the runtime surface that later slices
//! (G1 binding contracts, G2-G4 derivation, G6 fit reports) make real.

use lumen_core::{
    layout_scene, validate_binding_set, BindingSet, BoundValue, ContentType, DocumentStatus,
    LayoutOptions, Scene,
};

fn fixture(path: &str) -> String {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    std::fs::read_to_string(format!("{manifest_dir}/fixtures/{path}"))
        .unwrap_or_else(|error| panic!("fixture {path} should be readable: {error}"))
}

pub fn mailer_revision_scene() -> Scene {
    Scene::from_json(&fixture("conformance/phase_g_mailer_revision.json"))
        .expect("mailer revision fixture should parse as a scene")
}

fn binding_fixture(name: &str) -> serde_json::Value {
    serde_json::from_str(&fixture(&format!("binding/{name}.json")))
        .unwrap_or_else(|error| panic!("binding fixture {name} should parse: {error}"))
}

fn binding_set(name: &str) -> BindingSet {
    BindingSet::from_json(&fixture(&format!("binding/{name}.json"))).unwrap_or_else(|error| {
        panic!("binding fixture {name} should parse as BindingSet: {error}")
    })
}

fn error_codes(diagnostics: &[lumen_core::Diagnostic]) -> Vec<&str> {
    diagnostics
        .iter()
        .filter(|d| d.severity == lumen_core::DiagnosticSeverity::Error)
        .map(|d| d.code.as_str())
        .collect()
}

#[test]
fn mailer_revision_fixture_is_a_finalized_template() {
    let scene = mailer_revision_scene();
    match &scene.meta.status {
        DocumentStatus::Finalized {
            template_revision_id,
        } => {
            assert_eq!(template_revision_id.to_string(), "tmpl_mailer_v1");
        }
        other => panic!("mailer fixture must be finalized, got {other:?}"),
    }
    assert!(
        !scene.export_profiles.is_empty(),
        "finalized revisions carry export profiles"
    );
}

#[test]
fn mailer_revision_fixture_carries_the_g_slot_contracts() {
    let scene = mailer_revision_scene();

    let name_slot = scene
        .slot_by_key(&"contact.full_name".into())
        .expect("contact.full_name slot");
    assert_eq!(name_slot.content_type, ContentType::TextShort);
    assert!(matches!(
        name_slot.overflow,
        lumen_core::OverflowPolicy::ShrinkFont { .. }
    ));

    let logo_slot = scene
        .slot_by_key(&"account.logo".into())
        .expect("account.logo slot");
    assert_eq!(logo_slot.content_type, ContentType::Logo);
    assert!(logo_slot.image_policy.is_some());

    let cta_slot = scene
        .slot_by_key(&"campaign.cta".into())
        .expect("campaign.cta slot");
    assert!(matches!(
        cta_slot.overflow,
        lumen_core::OverflowPolicy::AskAgentToRepair
    ));

    let insights = scene
        .slot_by_key(&"research.key_insights".into())
        .expect("research.key_insights slot");
    assert_eq!(insights.content_type, ContentType::RepeaterGroup);
    let repeater = insights.repeater.as_ref().expect("repeater rule");
    assert_eq!(
        repeater.item_slot_key.to_string(),
        "research.key_insights.item"
    );
    assert_eq!(repeater.reflow, lumen_core::ReflowPolicy::Stack);
    assert!(
        scene.nodes.contains_key(&repeater.template_node_id),
        "repeater template node must exist"
    );

    let quote = scene
        .slot_by_key(&"research.quote".into())
        .expect("research.quote slot");
    let conditional = quote.conditional.as_ref().expect("conditional rule");
    assert_eq!(conditional.expression, "has(research.quote)");
    assert_eq!(
        conditional.when_false,
        lumen_core::EmptyBehavior::HideRegion
    );

    let qr = scene
        .slot_by_key(&"campaign.qr".into())
        .expect("campaign.qr slot");
    assert_eq!(qr.content_type, ContentType::UrlQr);
}

#[test]
fn mailer_revision_fixture_passes_structural_validation_and_layout() {
    let scene = mailer_revision_scene();
    let structural = lumen_core::validation::validate_scene(&scene);
    let errors: Vec<_> = structural
        .iter()
        .filter(|d| d.severity == lumen_core::DiagnosticSeverity::Error)
        .collect();
    assert!(
        errors.is_empty(),
        "template fixture must validate cleanly, got {errors:#?}"
    );

    let layout = layout_scene(&scene, LayoutOptions::default());
    let layout_errors: Vec<_> = layout
        .diagnostics
        .iter()
        .filter(|d| d.severity == lumen_core::DiagnosticSeverity::Error)
        .collect();
    assert!(
        layout_errors.is_empty(),
        "template fixture must lay out without errors, got {layout_errors:#?}"
    );
}

#[test]
fn binding_fixtures_follow_the_b2_contract_shape() {
    for name in ["nominal", "worst_case", "missing_optional"] {
        let binding = binding_fixture(name);
        assert_eq!(binding["schema_version"], 1, "{name}: schema_version");
        assert_eq!(
            binding["template_revision_id"], "tmpl_mailer_v1",
            "{name}: revision pin"
        );
        assert!(
            binding["binding_set_id"].as_str().is_some(),
            "{name}: binding_set_id"
        );
        assert!(binding["values"].is_object(), "{name}: values map");
        assert!(
            binding["links"]["landing_page"]["url"].as_str().is_some(),
            "{name}: landing page link"
        );
        let generated = &binding["generated"]["qr_landing"];
        assert_eq!(generated["provider"], "qr", "{name}: qr provider");
        assert_eq!(
            generated["input"]["url_from"], "links.landing_page.url",
            "{name}: QR chains from the landing link"
        );
        assert_eq!(
            generated["bind_to_slot"], "campaign.qr",
            "{name}: QR binds to the UrlQr slot"
        );
    }
}

#[test]
fn missing_optional_binding_omits_the_conditional_quote() {
    let binding = binding_fixture("missing_optional");
    assert!(
        binding["values"].get("research.quote").is_none(),
        "missing_optional must omit research.quote so HideRegion executes"
    );
}

// ---------------------------------------------------------------------------
// Runtime surface named by G0; implemented by later slices.
// ---------------------------------------------------------------------------

#[test]
fn g1_binding_sets_parse_and_validate_against_the_revision() {
    let scene = mailer_revision_scene();
    for name in ["nominal", "worst_case", "missing_optional"] {
        let binding = binding_set(name);
        let diagnostics = validate_binding_set(&scene, &binding);
        let errors = error_codes(&diagnostics);
        assert!(
            errors.is_empty(),
            "{name} binding set must validate cleanly, got {diagnostics:#?}"
        );
    }
}

#[test]
fn g1_binding_round_trips_the_b2_wire_shape() {
    let raw = binding_fixture("nominal");
    let parsed = binding_set("nominal");
    let reserialized = serde_json::to_value(&parsed).expect("binding set should serialize");
    assert_eq!(
        raw, reserialized,
        "BindingSet must round-trip the B2 JSON byte-for-byte (field for field)"
    );
}

#[test]
fn g1_unknown_slot_key_is_lumg0010() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.values.insert(
        "contact.title".to_owned(),
        BoundValue::Text {
            value: "Chief of Surgery".to_owned(),
        },
    );
    let diagnostics = validate_binding_set(&scene, &binding);
    let unknown = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0010")
        .expect("unknown slot key must be LUMG0010");
    assert!(
        unknown.message.contains("contact.title"),
        "diagnostic names the offending key: {}",
        unknown.message
    );
}

#[test]
fn g1_kind_mismatch_is_lumg0011() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.values.insert(
        "contact.full_name".to_owned(),
        BoundValue::Asset {
            asset_id: "asset_acme_logo".into(),
        },
    );
    let diagnostics = validate_binding_set(&scene, &binding);
    let mismatch = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0011")
        .expect("kind mismatch must be LUMG0011");
    assert!(
        mismatch.message.contains("expects a text value") && mismatch.message.contains("asset"),
        "diagnostic names both sides: {}",
        mismatch.message
    );
}

#[test]
fn g1_missing_required_value_is_lumg0012() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.values.remove("contact.full_name");
    let diagnostics = validate_binding_set(&scene, &binding);
    let missing = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0012")
        .expect("uncovered required slot must be LUMG0012");
    assert!(
        missing.message.contains("contact.full_name"),
        "diagnostic names the slot: {}",
        missing.message
    );
}

#[test]
fn g1_missing_optional_conditional_slot_is_not_an_error() {
    let scene = mailer_revision_scene();
    let binding = binding_set("missing_optional");
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        error_codes(&diagnostics).is_empty(),
        "optional conditional slot without a value is legitimate absence: {diagnostics:#?}"
    );
}

#[test]
fn g1_cardinality_violation_is_lumg0013() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    let item = BoundValue::Text {
        value: "Extra insight".to_owned(),
    };
    binding.values.insert(
        "research.key_insights".to_owned(),
        BoundValue::List {
            items: vec![item.clone(), item.clone(), item.clone(), item.clone(), item],
        },
    );
    let diagnostics = validate_binding_set(&scene, &binding);
    let cardinality = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0013")
        .expect("five items against max 4 must be LUMG0013");
    assert!(
        cardinality.message.contains("5 items"),
        "diagnostic counts the items: {}",
        cardinality.message
    );
}

#[test]
fn g1_max_length_violation_is_lumg0014() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.values.insert(
        "campaign.cta".to_owned(),
        BoundValue::Text {
            value: "X".repeat(61),
        },
    );
    let diagnostics = validate_binding_set(&scene, &binding);
    let too_long = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0014")
        .expect("61 chars against max_length 60 must be LUMG0014");
    assert!(
        too_long.message.contains("61 characters") && too_long.message.contains("60"),
        "diagnostic carries both lengths: {}",
        too_long.message
    );
}

#[test]
fn g1_direct_item_slot_binding_is_lumg0016() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.values.insert(
        "research.key_insights.item".to_owned(),
        BoundValue::Text {
            value: "Direct item".to_owned(),
        },
    );
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMG0016"),
        "item slots bind through the repeater list: {diagnostics:#?}"
    );
}

#[test]
fn g1_direct_value_for_url_qr_slot_is_rejected() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.values.insert(
        "campaign.qr".to_owned(),
        BoundValue::Text {
            value: "https://go.example.com/direct".to_owned(),
        },
    );
    let diagnostics = validate_binding_set(&scene, &binding);
    let rejected = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0011")
        .expect("url_qr direct binding must be LUMG0011");
    assert!(
        rejected.message.contains("generated entry"),
        "diagnostic points at the generated chain: {}",
        rejected.message
    );
}

#[test]
fn g1_unsupported_conditional_form_is_lumg0100_naming_the_form() {
    let mut scene = mailer_revision_scene();
    let slot = scene
        .slots
        .values_mut()
        .find(|slot| slot.key.as_str() == "research.quote")
        .expect("quote slot");
    slot.conditional = Some(lumen_core::ConditionalRule {
        expression: "has(research.quote) && has(campaign.cta)".to_owned(),
        when_false: lumen_core::EmptyBehavior::HideRegion,
    });
    let binding = binding_set("nominal");
    let diagnostics = validate_binding_set(&scene, &binding);
    let unsupported = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0100")
        .expect("frozen grammar violation must be LUMG0100");
    assert!(
        unsupported
            .message
            .contains("has(research.quote) && has(campaign.cta)"),
        "diagnostic names the unsupported form: {}",
        unsupported.message
    );
}

#[test]
fn g1_paginate_reflow_is_an_explicit_v0_error() {
    let mut scene = mailer_revision_scene();
    let slot = scene
        .slots
        .values_mut()
        .find(|slot| slot.key.as_str() == "research.key_insights")
        .expect("insights slot");
    slot.repeater.as_mut().expect("repeater rule").reflow = lumen_core::ReflowPolicy::Paginate;
    let binding = binding_set("nominal");
    let diagnostics = validate_binding_set(&scene, &binding);
    let paginate = diagnostics
        .iter()
        .find(|d| d.code == "LUMG0018")
        .expect("paginate reflow must be the explicit V0 error LUMG0018");
    assert!(
        paginate.message.contains("paginate"),
        "diagnostic names the policy: {}",
        paginate.message
    );
}

#[test]
fn g1_generated_spec_chain_violations_have_precise_codes() {
    let scene = mailer_revision_scene();

    // Unknown bind_to_slot.
    let mut binding = binding_set("nominal");
    binding
        .generated
        .get_mut("qr_landing")
        .expect("qr spec")
        .bind_to_slot = "campaign.qr_missing".into();
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMG0200"),
        "unknown bind_to_slot must be LUMG0200: {diagnostics:#?}"
    );

    // Non-UrlQr target slot.
    let mut binding = binding_set("nominal");
    binding
        .generated
        .get_mut("qr_landing")
        .expect("qr spec")
        .bind_to_slot = "campaign.cta".into();
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMG0201"),
        "non-url_qr generated target must be LUMG0201: {diagnostics:#?}"
    );

    // Unresolvable url_from.
    let mut binding = binding_set("nominal");
    binding
        .generated
        .get_mut("qr_landing")
        .expect("qr spec")
        .input
        .url_from = Some("links.other_page.url".to_owned());
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMG0202"),
        "unresolvable url_from must be LUMG0202: {diagnostics:#?}"
    );

    // Invalid ec_level.
    let mut binding = binding_set("nominal");
    binding
        .generated
        .get_mut("qr_landing")
        .expect("qr spec")
        .input
        .ec_level = Some("ultra".to_owned());
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMG0203"),
        "invalid ec_level must be LUMG0203: {diagnostics:#?}"
    );
}

#[test]
fn g1_draft_snapshot_and_revision_mismatch_are_errors() {
    let mut scene = mailer_revision_scene();
    scene.meta.status = DocumentStatus::Draft;
    let binding = binding_set("nominal");
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMG0001"),
        "draft snapshot must be LUMG0001: {diagnostics:#?}"
    );

    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.template_revision_id = "tmpl_other".into();
    let diagnostics = validate_binding_set(&scene, &binding);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUMG0002"),
        "revision mismatch must be LUMG0002: {diagnostics:#?}"
    );
}

fn logo_record(asset_id: &str) -> lumen_core::AssetRecord {
    lumen_core::AssetRecord {
        id: asset_id.into(),
        label: format!("Logo {asset_id}"),
        kind: lumen_core::AssetKind::Logo,
        status: lumen_core::AssetStatus::Ready,
        source: lumen_core::AssetSource::Uploaded {
            asset_id: None,
            filename: Some(format!("{asset_id}.png")),
            uploaded_by: Some("ops".to_owned()),
        },
        media: lumen_core::AssetMediaMetadata {
            mime_type: Some("image/png".to_owned()),
            filename: Some(format!("{asset_id}.png")),
            byte_length: Some(2048),
            digest: Some(lumen_core::AssetDigest {
                algorithm: "sha256".to_owned(),
                value: format!("{:0<64}", asset_id.len()),
            }),
            location: None,
            thumbnail: None,
        },
        raster: Some(lumen_core::RasterAssetMetadata {
            pixel_width: 1200,
            pixel_height: 400,
            dpi_x: Some(300.0),
            dpi_y: Some(300.0),
            has_alpha: Some(true),
            color_profile: Some("srgb".to_owned()),
            aspect_ratio: Some(3.0),
        }),
        vector: None,
        font: None,
        logo: Some(lumen_core::LogoAssetMetadata {
            pixel_width: Some(1200),
            pixel_height: Some(400),
            width: Some(36.0),
            height: Some(12.0),
            dpi_x: Some(300.0),
            dpi_y: Some(300.0),
            has_transparency: Some(true),
            color_mode: Some("full_color".to_owned()),
            clearspace: Some(2.0),
        }),
        license: None,
        provenance: lumen_core::AssetProvenance::default(),
        tags: vec!["logo".to_owned()],
    }
}

fn qr_record(asset_id: &str) -> lumen_core::AssetRecord {
    lumen_core::AssetRecord {
        id: asset_id.into(),
        label: format!("QR {asset_id}"),
        kind: lumen_core::AssetKind::Vector,
        status: lumen_core::AssetStatus::Ready,
        source: lumen_core::AssetSource::Generated {
            request_id: Some(asset_id.to_owned()),
            model: "qr-v1".to_owned(),
        },
        media: lumen_core::AssetMediaMetadata {
            mime_type: Some("image/svg+xml".to_owned()),
            filename: Some(format!("{asset_id}.svg")),
            byte_length: Some(1024),
            digest: Some(lumen_core::AssetDigest {
                algorithm: "sha256".to_owned(),
                value: format!("{:1<64}", asset_id.len()),
            }),
            location: None,
            thumbnail: None,
        },
        raster: None,
        vector: Some(lumen_core::VectorAssetMetadata {
            width: Some(33.0),
            height: Some(33.0),
            view_box: Some([0.0, 0.0, 33.0, 33.0]),
            has_transparency: Some(false),
            path_data: None,
        }),
        font: None,
        logo: None,
        license: None,
        provenance: lumen_core::AssetProvenance::default(),
        tags: vec!["qr".to_owned(), "generated".to_owned()],
    }
}

fn derivation_assets(logo_asset_id: &str, binding_set_id: &str) -> lumen_core::DerivationAssets {
    let mut assets = lumen_core::DerivationAssets::default();
    assets
        .records
        .insert(logo_asset_id.into(), logo_record(logo_asset_id));
    assets.generated.insert(
        "qr_landing".to_owned(),
        qr_record(&format!("asset_gen_{binding_set_id}_qr_landing")),
    );
    assets
}

fn derive_fixture(name: &str) -> lumen_core::DerivedInstance {
    let scene = mailer_revision_scene();
    let binding = binding_set(name);
    let logo_asset_id = match binding.values.get("account.logo") {
        Some(BoundValue::Asset { asset_id }) => asset_id.to_string(),
        other => panic!("fixture {name} must bind account.logo, got {other:?}"),
    };
    let assets = derivation_assets(&logo_asset_id, &binding.binding_set_id);
    lumen_core::derive_instance(
        &scene,
        &binding,
        &assets,
        &lumen_core::DeriveOptions::default(),
    )
}

#[test]
fn g2_derivation_is_a_pure_function_of_its_inputs() {
    let first = derive_fixture("nominal");
    let second = derive_fixture("nominal");

    let first_json = first
        .scene
        .to_canonical_json()
        .expect("derived scene serializes");
    let second_json = second
        .scene
        .to_canonical_json()
        .expect("derived scene serializes");
    assert_eq!(
        first_json, second_json,
        "same inputs must produce byte-identical derived scene JSON"
    );
    assert_eq!(first.audit, second.audit, "audit must be deterministic");
    assert_eq!(
        first.diagnostics, second.diagnostics,
        "diagnostics must be deterministic"
    );
}

#[test]
fn g2_text_values_apply_through_canonical_operations() {
    let derived = derive_fixture("missing_optional");
    assert!(
        !derived.has_errors(),
        "missing_optional derivation must succeed: {:#?}",
        derived.diagnostics
    );

    let headline = derived
        .scene
        .node(&"node_headline".into())
        .expect("headline");
    let lumen_core::NodeKind::Text(text) = &headline.kind else {
        panic!("headline stays a text node");
    };
    assert_eq!(text.content, "Ms. Adaeze Okafor");

    let audit_entry = derived
        .audit
        .iter()
        .find(|entry| {
            entry.kind == lumen_core::InstanceAuditKind::TextApplied
                && entry.slot_key.as_ref().map(|key| key.as_str()) == Some("contact.full_name")
        })
        .expect("text application must be audited");
    assert_eq!(audit_entry.node_ids, vec!["node_headline".into()]);
}

#[test]
fn g2_asset_values_place_through_place_asset_in_slot() {
    let derived = derive_fixture("nominal");
    assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);

    let logo = derived.scene.node(&"node_logo".into()).expect("logo node");
    let lumen_core::NodeKind::Image(image) = &logo.kind else {
        panic!("logo node stays an image node");
    };
    assert_eq!(image.asset_id.to_string(), "asset_acme_logo");
    assert_eq!(
        logo.source_asset_id.as_ref().map(ToString::to_string),
        Some("asset_acme_logo".to_owned())
    );
    let placement = logo.asset_placement.as_ref().expect("placement recorded");
    assert_eq!(placement.fit, Some(lumen_core::ImageFitMode::Contain));
    assert!(
        derived.scene.assets.contains_key(&"asset_acme_logo".into()),
        "asset record must be upserted into the derived scene"
    );
}

#[test]
fn g2_generated_qr_binds_to_the_url_qr_slot() {
    let derived = derive_fixture("nominal");
    assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);

    let qr_node = derived.scene.node(&"node_qr".into()).expect("qr node");
    let lumen_core::NodeKind::Image(image) = &qr_node.kind else {
        panic!("qr node stays an image node (no path_data on the record)");
    };
    assert_eq!(
        image.asset_id.to_string(),
        "asset_gen_bind_acme_dr_sharma_qr_landing"
    );
    assert!(derived.audit.iter().any(|entry| {
        entry.kind == lumen_core::InstanceAuditKind::GeneratedAssetBound
            && entry.message.contains("qr_landing")
    }));
}

#[test]
fn g2_missing_supplied_records_are_precise_errors() {
    let scene = mailer_revision_scene();
    let binding = binding_set("nominal");

    // No logo record supplied.
    let mut assets = lumen_core::DerivationAssets::default();
    assets.generated.insert(
        "qr_landing".to_owned(),
        qr_record("asset_gen_bind_acme_dr_sharma_qr_landing"),
    );
    let derived = lumen_core::derive_instance(
        &scene,
        &binding,
        &assets,
        &lumen_core::DeriveOptions::default(),
    );
    assert!(
        derived
            .diagnostics
            .iter()
            .any(|d| d.code == "LUMG0301" && d.message.contains("asset_acme_logo")),
        "missing bound asset record must be LUMG0301: {:#?}",
        derived.diagnostics
    );

    // No generated record executed.
    let mut assets = lumen_core::DerivationAssets::default();
    assets
        .records
        .insert("asset_acme_logo".into(), logo_record("asset_acme_logo"));
    let derived = lumen_core::derive_instance(
        &scene,
        &binding,
        &assets,
        &lumen_core::DeriveOptions::default(),
    );
    assert!(
        derived
            .diagnostics
            .iter()
            .any(|d| d.code == "LUMG0302" && d.message.contains("qr_landing")),
        "missing generated record must be LUMG0302: {:#?}",
        derived.diagnostics
    );
}

#[test]
fn g2_derived_scene_keeps_revision_provenance_and_validates() {
    let derived = derive_fixture("nominal");
    match &derived.scene.meta.status {
        DocumentStatus::Finalized {
            template_revision_id,
        } => assert_eq!(template_revision_id.to_string(), "tmpl_mailer_v1"),
        other => panic!("derived instance keeps finalized provenance, got {other:?}"),
    }

    let structural = lumen_core::validation::validate_scene(&derived.scene);
    let errors: Vec<_> = structural
        .iter()
        .filter(|d| d.severity == lumen_core::DiagnosticSeverity::Error)
        .collect();
    assert!(
        errors.is_empty(),
        "derived scenes must pass full scene validation: {errors:#?}"
    );

    let geometry_present = derived
        .scene
        .nodes
        .values()
        .all(|node| node.computed.is_some());
    assert!(
        geometry_present,
        "derivation must leave computed geometry on every node"
    );
}

#[test]
fn g2_invalid_binding_sets_refuse_derivation_without_mutation() {
    let scene = mailer_revision_scene();
    let mut binding = binding_set("nominal");
    binding.values.remove("contact.full_name");
    let assets = derivation_assets("asset_acme_logo", &binding.binding_set_id);
    let derived = lumen_core::derive_instance(
        &scene,
        &binding,
        &assets,
        &lumen_core::DeriveOptions::default(),
    );
    assert!(derived.has_errors());
    assert!(
        derived.audit.is_empty(),
        "refused derivations must not record applied actions"
    );
    assert_eq!(
        derived.scene.to_canonical_json().unwrap(),
        scene.to_canonical_json().unwrap(),
        "refused derivations return the untouched snapshot"
    );
}

#[test]
fn g3_hide_region_removes_the_bound_subtree_pre_layout() {
    let derived = derive_fixture("missing_optional");
    assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);

    assert!(
        derived.scene.node(&"node_quote".into()).is_none(),
        "hidden region's bound node must be removed"
    );
    assert!(
        derived
            .scene
            .slot_by_key(&"research.quote".into())
            .is_none(),
        "hidden region's slot record must be removed"
    );
    assert!(
        !derived
            .scene
            .pages
            .values()
            .any(|page| page.children.contains(&"node_quote".into())),
        "page children must not reference the hidden node"
    );

    let hidden = derived
        .audit
        .iter()
        .find(|entry| entry.kind == lumen_core::InstanceAuditKind::ConditionalHidden)
        .expect("hide region must be audited");
    assert!(
        hidden.message.contains("research.quote") && hidden.message.contains("has(research.quote)"),
        "audit names the slot and the expression: {}",
        hidden.message
    );
    assert_eq!(hidden.node_ids, vec!["node_quote".into()]);

    // The derived scene must still be fully valid after subtree removal.
    let errors: Vec<_> = lumen_core::validation::validate_scene(&derived.scene)
        .into_iter()
        .filter(|d| d.severity == lumen_core::DiagnosticSeverity::Error)
        .collect();
    assert!(errors.is_empty(), "{errors:#?}");
}

#[test]
fn g3_satisfied_conditionals_apply_the_bound_value() {
    let derived = derive_fixture("nominal");
    assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);

    let quote = derived
        .scene
        .node(&"node_quote".into())
        .expect("quote node");
    let lumen_core::NodeKind::Text(text) = &quote.kind else {
        panic!("quote stays a text node");
    };
    assert_eq!(
        text.content,
        "Their team shipped twice as fast as any vendor we have worked with."
    );
    assert!(derived.audit.iter().any(|entry| {
        entry.kind == lumen_core::InstanceAuditKind::ConditionalSatisfied
            && entry.slot_key.as_ref().map(|key| key.as_str()) == Some("research.quote")
    }));
}

#[test]
fn g3_use_fallback_substitutes_the_placeholder() {
    let mut scene = mailer_revision_scene();
    let slot = scene
        .slots
        .values_mut()
        .find(|slot| slot.key.as_str() == "research.quote")
        .expect("quote slot");
    slot.conditional = Some(lumen_core::ConditionalRule {
        expression: "has(research.quote)".to_owned(),
        when_false: lumen_core::EmptyBehavior::UseFallback,
    });

    let binding = binding_set("missing_optional");
    let assets = derivation_assets("asset_northcare_logo", &binding.binding_set_id);
    let derived = lumen_core::derive_instance(
        &scene,
        &binding,
        &assets,
        &lumen_core::DeriveOptions::default(),
    );
    assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);

    let quote = derived
        .scene
        .node(&"node_quote".into())
        .expect("quote node kept");
    let lumen_core::NodeKind::Text(text) = &quote.kind else {
        panic!("quote stays a text node");
    };
    assert_eq!(text.content, "Their team shipped twice as fast.");
    assert!(derived
        .audit
        .iter()
        .any(|entry| entry.kind == lumen_core::InstanceAuditKind::ConditionalFallback));
}

#[test]
fn g3_validation_error_behavior_fails_the_instance() {
    let mut scene = mailer_revision_scene();
    let slot = scene
        .slots
        .values_mut()
        .find(|slot| slot.key.as_str() == "research.quote")
        .expect("quote slot");
    slot.conditional = Some(lumen_core::ConditionalRule {
        expression: "has(research.quote)".to_owned(),
        when_false: lumen_core::EmptyBehavior::ValidationError,
    });

    let binding = binding_set("missing_optional");
    let assets = derivation_assets("asset_northcare_logo", &binding.binding_set_id);
    let derived = lumen_core::derive_instance(
        &scene,
        &binding,
        &assets,
        &lumen_core::DeriveOptions::default(),
    );
    let error = derived
        .diagnostics
        .iter()
        .find(|d| d.code == "LUMG0311")
        .expect("validation_error behavior must be LUMG0311");
    assert!(
        error.message.contains("research.quote"),
        "diagnostic names the slot: {}",
        error.message
    );
}

#[test]
fn g3_eq_false_suppresses_the_bound_value_with_audit() {
    let mut scene = mailer_revision_scene();
    let slot = scene
        .slots
        .values_mut()
        .find(|slot| slot.key.as_str() == "research.quote")
        .expect("quote slot");
    slot.conditional = Some(lumen_core::ConditionalRule {
        expression: "eq(campaign.cta,\"Some other CTA\")".to_owned(),
        when_false: lumen_core::EmptyBehavior::PreservePlaceholder,
    });

    // nominal provides a quote value, but the eq() gate is false.
    let binding = binding_set("nominal");
    let assets = derivation_assets("asset_acme_logo", &binding.binding_set_id);
    let derived = lumen_core::derive_instance(
        &scene,
        &binding,
        &assets,
        &lumen_core::DeriveOptions::default(),
    );
    assert!(!derived.has_errors(), "{:#?}", derived.diagnostics);

    let quote = derived
        .scene
        .node(&"node_quote".into())
        .expect("quote node kept");
    let lumen_core::NodeKind::Text(text) = &quote.kind else {
        panic!("quote stays a text node");
    };
    assert_eq!(
        text.content, "Their team shipped twice as fast.",
        "placeholder content preserved; bound value not applied"
    );
    assert!(derived
        .audit
        .iter()
        .any(|entry| entry.kind == lumen_core::InstanceAuditKind::ValueIgnored));
    assert!(derived
        .audit
        .iter()
        .any(|entry| entry.kind == lumen_core::InstanceAuditKind::ConditionalPreserved));
}

#[test]
#[ignore = "G4: repeaters clone with lineage and deterministic _item_{n} ids"]
fn g4_repeaters_ride_phase_d_clone_machinery() {
    unimplemented!("clone-per-item, per-item slot suffix binding, stack reflow");
}

#[test]
#[ignore = "G6: InstanceFitReport surfaces every overflow, no silent failures"]
fn g6_fit_reports_catch_the_worst_case_overflow() {
    unimplemented!("worst_case binding set must produce an overflow verdict");
}
