use lumen_core::validation::validate_scene;
use lumen_core::{DiagnosticSeverity, ExportFormat, PageId, Scene};
use serde_json::Value;

const MANIFEST: &str = include_str!("../fixtures/visual_regression/manifest.json");
const VALID_MULTI_PAGE_SLOTS: &str =
    include_str!("../fixtures/conformance/valid_multi_page_slots.json");
const PENDING_BASELINE: &str = include_str!(
    "../fixtures/visual_regression/baselines/valid_multi_page_slots_agent_png_linkedin_ad.pending.txt"
);

#[test]
#[ignore = "run explicitly until export/svg-pdf provides concrete visual baselines"]
fn visual_regression_skeleton_manifest_is_runnable() {
    let manifest: Value = serde_json::from_str(MANIFEST).expect("visual manifest decodes");

    assert_eq!(manifest["schema_version"], 1);
    let cases = manifest["cases"]
        .as_array()
        .expect("visual manifest has cases");
    assert!(!cases.is_empty(), "visual manifest must define cases");

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

    assert!(
        PENDING_BASELINE.contains("valid_multi_page_slots_agent_png_linkedin_ad"),
        "pending baseline should identify its case"
    );
}

fn assert_visual_case_shape(case: &Value) {
    assert_eq!(
        case["scene_fixture"],
        "crates/lumen-core/fixtures/conformance/valid_multi_page_slots.json"
    );
    assert_eq!(case["profile"], "agent_png");
    assert_eq!(case["format"], "png");
    assert_eq!(case["page_id"], "page_linkedin_ad");
    assert_eq!(case["purpose"], "agent_critique");
    assert_eq!(
        case["baseline"],
        "crates/lumen-core/fixtures/visual_regression/baselines/valid_multi_page_slots_agent_png_linkedin_ad.pending.txt"
    );
    assert_eq!(case["status"], "pending_renderer");
}

fn scene_for_case(case: &Value) -> Scene {
    match case["scene_fixture"].as_str() {
        Some("crates/lumen-core/fixtures/conformance/valid_multi_page_slots.json") => {
            serde_json::from_str(VALID_MULTI_PAGE_SLOTS).expect("scene fixture decodes")
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
