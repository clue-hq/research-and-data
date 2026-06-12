use lumen_core::validation::validate_scene;
use lumen_core::{DiagnosticSeverity, ExportFormat, PageId, Scene};
use serde_json::Value;

const MANIFEST: &str = include_str!("../fixtures/visual_regression/manifest.json");
const VALID_MULTI_PAGE_SLOTS: &str =
    include_str!("../fixtures/conformance/valid_multi_page_slots.json");
const EFFECTS_CARD: &str = include_str!("../fixtures/effects/effects_card.json");
const PENDING_BASELINES: [(&str, &str); 2] = [
    (
        "valid_multi_page_slots_agent_png_linkedin_ad",
        include_str!(
            "../fixtures/visual_regression/baselines/valid_multi_page_slots_agent_png_linkedin_ad.pending.txt"
        ),
    ),
    (
        "effects_card_agent_png",
        include_str!("../fixtures/visual_regression/baselines/effects_card_agent_png.pending.txt"),
    ),
];

#[test]
#[ignore = "run explicitly until export/svg-pdf provides concrete visual baselines"]
fn visual_regression_skeleton_manifest_is_runnable() {
    let manifest: Value = serde_json::from_str(MANIFEST).expect("visual manifest decodes");

    assert_eq!(manifest["schema_version"], 1);
    let cases = manifest["cases"]
        .as_array()
        .expect("visual manifest has cases");
    assert!(
        cases.len() >= 2,
        "visual manifest must define the base and effects cases"
    );

    for case in cases {
        assert_visual_case_shape(case);

        let scene = scene_for_case(case);
        assert_scene_has_no_validation_errors(case["id"].as_str().unwrap(), &scene);

        let page_id = case["page_id"].as_str().expect("case page_id");
        assert!(
            scene.pages.contains_key(&PageId::from(page_id)),
            "visual case {case:?} targets missing page"
        );

        let profile_name = case["profile"].as_str().expect("case profile");
        let profile = scene
            .export_profiles
            .iter()
            .find(|candidate| candidate.name == profile_name)
            .expect("visual case profile exists on scene");
        assert_eq!(profile.format, format_for_case(case));
    }

    for (case_id, baseline) in PENDING_BASELINES {
        assert!(
            baseline.contains(case_id),
            "pending baseline should identify its case {case_id}"
        );
    }
}

fn assert_visual_case_shape(case: &Value) {
    for field in [
        "id",
        "scene_fixture",
        "profile",
        "format",
        "page_id",
        "purpose",
        "baseline",
        "status",
    ] {
        assert!(
            case[field].as_str().is_some_and(|value| !value.is_empty()),
            "visual case {case:?} is missing {field}"
        );
    }
    assert_eq!(case["status"], "pending_renderer");
    assert_eq!(case["purpose"], "agent_critique");
}

fn scene_for_case(case: &Value) -> Scene {
    match case["scene_fixture"].as_str() {
        Some("crates/lumen-core/fixtures/conformance/valid_multi_page_slots.json") => {
            serde_json::from_str(VALID_MULTI_PAGE_SLOTS).expect("scene fixture decodes")
        }
        Some("crates/lumen-core/fixtures/effects/effects_card.json") => {
            serde_json::from_str(EFFECTS_CARD).expect("effects scene fixture decodes")
        }
        other => panic!("unwired visual scene fixture: {other:?}"),
    }
}

fn format_for_case(case: &Value) -> ExportFormat {
    match case["format"].as_str() {
        Some("png") => ExportFormat::Png,
        Some("svg") => ExportFormat::Svg,
        Some("pdf") => ExportFormat::Pdf,
        Some("figma_manifest") => ExportFormat::FigmaManifest,
        other => panic!("unsupported visual format: {other:?}"),
    }
}

fn assert_scene_has_no_validation_errors(name: &str, scene: &Scene) {
    let diagnostics = validate_scene(scene);
    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
        "{name} has validation errors: {diagnostics:#?}"
    );
}
