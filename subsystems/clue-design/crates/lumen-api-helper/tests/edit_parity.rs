//! Cross-language edit parity: the fixture cases in
//! `fixtures/edit-parity/cases.json` pin the exact canonical operation
//! batches the Rust edit builders produce. The editor's Vitest suite
//! (`editParity.test.ts`) asserts its TypeScript wrapper and optimistic
//! helpers against the same file, so the two implementations cannot drift
//! silently.

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
fn edit_parity_cases_produce_pinned_canonical_operations() {
    let fixture: Value = serde_json::from_str(CASES).expect("cases parse");
    let scene: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene parses");
    let cases = fixture["cases"].as_array().expect("cases array");
    assert!(!cases.is_empty());

    for case in cases {
        let name = case["name"].as_str().expect("case name");
        let response = helper(json!({
            "action": "apply_structured_edit",
            "scene": scene.clone(),
            "edit": case["edit"].clone(),
        }));
        assert_eq!(response["ok"], true, "case {name}: {response:#?}");
        assert_eq!(
            response["operations"], case["expected_operations"],
            "case {name}: Rust builders diverged from the pinned parity operations"
        );
    }
}
