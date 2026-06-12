//! Cross-binding parity: the browser engine (lumen-wasm) and the server
//! helper binary must produce byte-identical structured-edit results —
//! canonical operations, inverse operations, touched targets, intent — for
//! the same inputs, because both route through
//! `lumen_core::build_structured_edit_batch`. This is the Track E
//! optimistic-path honesty check: if these ever diverge, optimistic editing
//! is lying about what the server will do.

use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Stdio};

const CASES: &str = include_str!("../../../fixtures/edit-parity/cases.json");
const MINIMAL_SCENE: &str = include_str!("../../lumen-core/fixtures/minimal_scene.json");

fn helper(request: Value) -> Value {
    let mut child = Command::new(env!("CARGO_BIN_EXE_lumen-api-helper"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("helper spawns");
    child
        .stdin
        .as_mut()
        .expect("stdin")
        .write_all(request.to_string().as_bytes())
        .expect("request written");
    let output = child.wait_with_output().expect("helper completes");
    serde_json::from_slice(&output.stdout).expect("helper returns JSON")
}

#[test]
fn wasm_engine_and_helper_binary_agree_byte_for_byte_on_structured_edits() {
    let fixture: Value = serde_json::from_str(CASES).expect("cases parse");
    let scene: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene parses");
    let cases = fixture["cases"].as_array().expect("cases array");
    assert!(!cases.is_empty());

    for case in cases {
        let name = case["name"].as_str().expect("case name");

        let helper_response = helper(json!({
            "action": "apply_structured_edit",
            "scene": scene.clone(),
            "edit": case["edit"].clone(),
        }));
        assert_eq!(helper_response["ok"], json!(true), "case {name}");

        let mut engine =
            lumen_wasm::Engine::from_scene_json(MINIMAL_SCENE).expect("scene loads in wasm engine");
        let wasm_response: Value =
            serde_json::from_str(&engine.apply_structured_edit(&case["edit"].to_string()))
                .expect("wasm engine returns JSON");
        assert_eq!(wasm_response["ok"], json!(true), "case {name}");

        // Canonical operations: identical.
        assert_eq!(
            wasm_response["operations"], helper_response["operations"],
            "case {name}: operations diverged between wasm engine and helper"
        );
        // Edit metadata (kind, touched targets, intent, checkpoint,
        // inverse operations, lineage): identical, no field skipped.
        assert_eq!(
            wasm_response["edit"], helper_response["edit"],
            "case {name}: edit envelope metadata diverged"
        );
        // Applied counts and diagnostics: identical.
        assert_eq!(
            wasm_response["applied_operations"], helper_response["applied_operations"],
            "case {name}"
        );
        assert_eq!(
            wasm_response["diagnostics"],
            helper_response
                .get("diagnostics")
                .cloned()
                .unwrap_or_else(|| json!([])),
            "case {name}: diagnostics diverged"
        );

        // Resulting scenes: identical (helper returns the full scene; the
        // wasm engine state is read back via its snapshot channel).
        let wasm_scene: Value =
            serde_json::from_str(&engine.scene_json()).expect("wasm scene serializes");
        assert_eq!(
            wasm_scene, helper_response["scene"],
            "case {name}: resulting scenes diverged"
        );
    }
}

#[test]
fn wasm_engine_and_helper_binary_agree_on_apply_operations() {
    let fixture: Value = serde_json::from_str(CASES).expect("cases parse");
    let scene: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene parses");

    // Use the pinned canonical operations from every parity case as raw
    // operation batches: the apply_operations channel must agree too
    // (operations, inverses, resulting scene).
    for case in fixture["cases"].as_array().expect("cases array") {
        let name = case["name"].as_str().expect("case name");
        let operations = case["expected_operations"].clone();

        let helper_response = helper(json!({
            "action": "apply_operations",
            "scene": scene.clone(),
            "operations": operations.clone(),
        }));
        assert_eq!(helper_response["ok"], json!(true), "case {name}");

        let mut engine =
            lumen_wasm::Engine::from_scene_json(MINIMAL_SCENE).expect("scene loads in wasm engine");
        let wasm_response: Value =
            serde_json::from_str(&engine.apply_operations(&operations.to_string()))
                .expect("wasm engine returns JSON");
        assert_eq!(wasm_response["ok"], json!(true), "case {name}");

        assert_eq!(
            wasm_response["inverse_operations"], helper_response["edit"]["inverse_operations"],
            "case {name}: inverse operations diverged"
        );
        let wasm_scene: Value =
            serde_json::from_str(&engine.scene_json()).expect("wasm scene serializes");
        assert_eq!(
            wasm_scene, helper_response["scene"],
            "case {name}: resulting scenes diverged"
        );
    }
}
