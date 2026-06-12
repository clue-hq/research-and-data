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

#[test]
#[ignore = "G2: derive_instance(snapshot, binding_set, assets) is deterministic"]
fn g2_derivation_is_a_pure_function_of_its_inputs() {
    unimplemented!("lumen_core::instance::derive_instance");
}

#[test]
#[ignore = "G3: conditional EmptyBehavior executes with audit entries"]
fn g3_conditionals_execute_empty_behavior() {
    unimplemented!("HideRegion / UseFallback / ValidationError execution");
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
