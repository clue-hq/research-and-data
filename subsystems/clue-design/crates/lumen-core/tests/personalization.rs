//! Phase G personalization runtime conformance (slice G0 onward).
//!
//! G0 pins the fixture contract: a finalized mailer template revision plus
//! three binding sets (nominal, worst-case lengths, missing optional
//! content). The ignored tests name the runtime surface that later slices
//! (G1 binding contracts, G2-G4 derivation, G6 fit reports) make real.

use lumen_core::{layout_scene, ContentType, DocumentStatus, LayoutOptions, Scene};

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
#[ignore = "G1: BindingSet contracts land in lumen_core::binding"]
fn g1_binding_sets_parse_and_validate_against_the_revision() {
    unimplemented!("lumen_core::binding::{{BindingSet, validate_binding_set}}");
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
