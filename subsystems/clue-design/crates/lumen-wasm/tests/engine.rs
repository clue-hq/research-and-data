//! Native tests for the exact engine logic the browser runs. The pinned
//! edit-parity fixture is asserted directly against the wasm engine: the
//! same structured edits must produce the same canonical operations the
//! API helper (and previously the TS mirrors) produce.

use lumen_wasm::{version_payload, Engine};
use serde_json::{json, Value};

const MINIMAL_SCENE: &str = include_str!("../../lumen-core/fixtures/minimal_scene.json");
const PARITY_CASES: &str = include_str!("../../../fixtures/edit-parity/cases.json");

fn engine() -> Engine {
    Engine::from_scene_json(MINIMAL_SCENE).expect("minimal scene loads")
}

fn parse(payload: String) -> Value {
    serde_json::from_str(&payload).expect("engine returns JSON")
}

fn transform(x: f64, y: f64) -> Value {
    json!({
        "x": x,
        "y": y,
        "rotation": 0.0,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "flip_x": false,
        "flip_y": false
    })
}

/// Full sparse node patch in canonical wire form (every field present, as
/// the TS builders emit), with `transform` set to the given position.
fn node_transform_patch(x: f64, y: f64) -> Value {
    json!({
        "name": { "kind": "unchanged" },
        "kind": { "kind": "unchanged" },
        "transform": { "kind": "set", "value": transform(x, y) },
        "size": { "kind": "unchanged" },
        "fills": { "kind": "unchanged" },
        "strokes": { "kind": "unchanged" },
        "corner": { "kind": "unchanged" },
        "opacity": { "kind": "unchanged" },
        "opacity_token": { "kind": "unchanged" },
        "source_asset_id": { "kind": "unchanged" },
        "asset_placement": { "kind": "unchanged" },
        "clip": { "kind": "unchanged" },
        "layout": { "kind": "unchanged" },
        "computed": { "kind": "unchanged" },
        "locked": { "kind": "unchanged" }
    })
}

/// Mechanical mirror of the TS-side `applySceneDelta`: merge a delta into a
/// scene JSON value. Asserting `snapshot + delta == engine scene` proves the
/// delta channel reconstructs state without full-scene serialization.
fn apply_delta(scene: &mut Value, delta: &Value) {
    let delta = delta.as_object().expect("delta is an object");
    if let Some(meta) = delta.get("meta") {
        scene["meta"] = meta.clone();
    }
    for field in ["pages", "nodes", "slots", "assets"] {
        if let Some(changes) = delta.get(field).and_then(Value::as_object) {
            let map = scene[field].as_object_mut().expect("scene map field");
            for (key, value) in changes {
                if value.is_null() {
                    map.remove(key);
                } else {
                    map.insert(key.clone(), value.clone());
                }
            }
        }
    }
    if let Some(profiles) = delta.get("export_profiles") {
        scene["export_profiles"] = profiles.clone();
    }
}

#[test]
fn version_reports_schema_commit_and_heuristic_measurement() {
    let version = version_payload();
    assert_eq!(version["schema_version"], json!(lumen_core::SCHEMA_VERSION));
    let commit = version["engine_commit"].as_str().expect("commit string");
    assert!(!commit.is_empty());
    assert_eq!(version["text_measurement"], json!("heuristic"));
}

#[test]
fn parity_cases_produce_pinned_canonical_operations() {
    let fixture: Value = serde_json::from_str(PARITY_CASES).expect("cases parse");
    let cases = fixture["cases"].as_array().expect("cases array");
    assert!(!cases.is_empty());

    for case in cases {
        let name = case["name"].as_str().expect("case name");
        let mut engine = engine();
        let result = parse(engine.apply_structured_edit(&case["edit"].to_string()));
        assert_eq!(result["ok"], json!(true), "case {name}: {result:#?}");
        assert_eq!(
            result["operations"], case["expected_operations"],
            "case {name}: wasm engine diverged from the pinned parity operations"
        );
    }
}

#[test]
fn parity_case_deltas_reconstruct_the_engine_scene() {
    let fixture: Value = serde_json::from_str(PARITY_CASES).expect("cases parse");
    for case in fixture["cases"].as_array().expect("cases array") {
        let name = case["name"].as_str().expect("case name");
        let mut engine = engine();
        let result = parse(engine.apply_structured_edit(&case["edit"].to_string()));
        assert_eq!(result["ok"], json!(true), "case {name}");

        let mut snapshot: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene parses");
        apply_delta(&mut snapshot, &result["delta"]);
        let engine_scene: Value =
            serde_json::from_str(&engine.scene_json()).expect("scene serializes");
        assert_eq!(
            snapshot, engine_scene,
            "case {name}: delta did not reconstruct the engine scene"
        );
    }
}

#[test]
fn apply_operations_returns_inverses_that_round_trip() {
    let mut engine = engine();
    let original: Value = serde_json::from_str(&engine.scene_json()).expect("scene");

    let operations = json!([{
        "kind": "update_node",
        "node_id": "node_contact_name",
        "patch": node_transform_patch(42.0, 24.0)
    }]);
    let result = parse(engine.apply_operations(&operations.to_string()));
    assert_eq!(result["ok"], json!(true), "{result:#?}");
    assert_eq!(result["applied_operations"], json!(1));
    let changed: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_ne!(original, changed);

    let inverses = result["inverse_operations"].clone();
    assert!(inverses.is_array(), "inverse operations expected");
    let undo = parse(engine.apply_operations(&inverses.to_string()));
    assert_eq!(undo["ok"], json!(true), "{undo:#?}");
    let restored: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(original, restored, "inverse batch must restore the scene");
}

#[test]
fn failed_batches_leave_the_scene_untouched() {
    let mut engine = engine();
    let before = engine.scene_json();
    let result = parse(engine.apply_operations(
        &json!([{ "kind": "remove_node", "node_id": "node_does_not_exist" }]).to_string(),
    ));
    assert_eq!(result["ok"], json!(false));
    assert!(result["error"]["code"].is_string());
    assert_eq!(before, engine.scene_json(), "failed batch must not mutate");
}

#[test]
fn invalid_json_is_reported_not_panicked() {
    let mut engine = engine();
    let result = parse(engine.apply_operations("not json"));
    assert_eq!(result["ok"], json!(false));
    assert_eq!(result["error"]["code"], json!("wasm.operations"));

    let result = parse(engine.apply_structured_edit("{\"kind\":\"unknown_kind\"}"));
    assert_eq!(result["ok"], json!(false));
    assert_eq!(result["error"]["code"], json!("wasm.structured_edit"));
}

#[test]
fn structured_edit_errors_mirror_core_error_codes() {
    let mut engine = engine();
    let result = parse(
        engine.apply_structured_edit(
            &json!({ "kind": "delete", "target": { "kind": "node", "id": "node_missing" } })
                .to_string(),
        ),
    );
    assert_eq!(result["ok"], json!(false));
    assert_eq!(result["error"]["code"], json!("edit.target_not_found"));
    assert!(result["diagnostics"]
        .as_array()
        .is_some_and(|d| !d.is_empty()));
}

#[test]
fn compile_dsl_block_applies_modify_lines_and_keeps_session() {
    let mut engine = engine();
    let result = parse(engine.compile_dsl_block("#node_contact_name text(\"WASM edit\")"));
    assert_eq!(result["ok"], json!(true), "{result:#?}");
    assert!(
        result["operation_report"]["applied_operations"]
            .as_u64()
            .is_some_and(|count| count > 0),
        "{result:#?}"
    );
    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(
        scene["nodes"]["node_contact_name"]["kind"]["content"],
        json!("WASM edit")
    );
    assert!(result["delta"]["nodes"]["node_contact_name"].is_object());
}

#[test]
fn layout_and_preflight_report_heuristic_measurement() {
    let engine = engine();
    let layout = parse(engine.layout_geometry());
    assert_eq!(layout["text_measurement"], json!("heuristic"));
    assert!(layout["geometry"]
        .as_object()
        .is_some_and(|geometry| !geometry.is_empty()));

    let preflight = parse(engine.preflight());
    assert_eq!(preflight["text_measurement"], json!("heuristic"));
    assert!(preflight["diagnostics"].is_array());
    // Read-only: preflight must not mutate the engine scene.
    assert_eq!(engine.scene_json(), engine.scene_json());
}

#[test]
fn load_scene_replaces_state_for_reconcile_and_undo_frames() {
    let mut engine = engine();
    parse(
        engine.apply_operations(
            &json!([{
                "kind": "update_node",
                "node_id": "node_contact_name",
                "patch": node_transform_patch(9.0, 9.0)
            }])
            .to_string(),
        ),
    );
    engine.load_scene(MINIMAL_SCENE).expect("snapshot reloads");
    let restored: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    let original: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene");
    assert_eq!(restored, original);
}
