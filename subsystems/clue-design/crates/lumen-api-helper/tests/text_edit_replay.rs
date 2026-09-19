use lumen_core::{
    compile_dsl_into_scene, platform_default_brand_kit, DocumentId, Operation, Scene,
};
use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Stdio};

fn helper(request: Value) -> Value {
    let mut child = Command::new(env!("CARGO_BIN_EXE_lumen-api-helper"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(request.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}

fn fixture() -> (Value, Value) {
    let kit = platform_default_brand_kit().unwrap();
    let mut scene = Scene::new(DocumentId::from("text_edit_replay"), "Scoped text repair");
    let compiled = compile_dsl_into_scene(
        "page square size(1080,1080,px)\n  support text \"A bounded repair\" s(800,hug) font(\"Raw Fallback\",11,300,left) style($type.body) lh(1.35) ls(0.9)\n  other text \"Leave this authored node alone\" s(800,hug) style($type.body)",
        &mut scene,
    );
    assert!(!compiled.compile_output.has_errors());
    scene
        .apply_operation(Operation::SetBrandKitRef {
            brand_kit_id: kit.id.clone(),
            version: kit.version,
        })
        .unwrap();
    (
        serde_json::to_value(scene).unwrap(),
        serde_json::to_value(kit).unwrap(),
    )
}

#[test]
fn size_and_weight_repairs_preserve_other_effective_fields() {
    let (authored, kit) = fixture();
    let before = resolved(&authored, &kit);
    for (source, field, value) in [
        ("#support font_size(33.5)", "font_size", json!(33.5)),
        ("#support font_size(11)", "font_size", json!(11.0)),
        ("#support font_weight(700)", "font_weight", json!(700)),
    ] {
        let response = helper(json!({"action":"compile_dsl_into_scene", "scene":authored,
            "brand_kit":kit, "source":source}));
        assert_eq!(response["ok"], true, "{response:#}");
        assert!(
            response["dsl"]["compile_output"]["halted_at"].is_null(),
            "{response:#}"
        );
        let mut expected = typography(&before);
        expected[field] = value;
        assert_eq!(
            typography(&resolved(&response["scene"], &kit)),
            expected,
            "{source}"
        );
    }
}

#[test]
fn explicit_role_reauthoring_wins_and_inverse_restores_authored_scene() {
    let (authored, kit) = fixture();
    let response = helper(json!({"action":"compile_dsl_into_scene", "scene":authored,
        "brand_kit":kit, "source":"#support fill(#123456) style($type.caption)"}));
    assert!(
        response["dsl"]["compile_output"]["halted_at"].is_null(),
        "{response:#}"
    );
    assert_eq!(
        response["scene"]["nodes"]["support"]["kind"]["style_token"],
        "type.caption"
    );
    let operations = &response["dsl"]["compile_output"]["operations"];
    let replay =
        helper(json!({"action":"apply_operations", "scene":authored, "operations":operations}));
    assert_eq!(
        resolved(&response["scene"], &kit),
        resolved(&replay["scene"], &kit)
    );
    let undo = helper(json!({"action":"apply_operations", "scene":replay["scene"],
        "operations":replay["edit"]["inverse_operations"]}));
    assert_eq!(undo["scene"], authored);
}

#[test]
fn detachment_does_not_activate_shadowed_leading_token() {
    let (mut authored, kit) = fixture();
    // A real spacing token is valid as a leading carrier but is shadowed by
    // type.body's own leading until a role-detaching edit takes place.
    authored["nodes"]["support"]["kind"]["line_height_token"] = json!("space.xs");
    let before = resolved(&authored, &kit);
    let response = helper(json!({"action":"compile_dsl_into_scene", "scene":authored,
        "brand_kit":kit, "source":"#support fill(#123456)"}));
    assert!(
        response["dsl"]["compile_output"]["halted_at"].is_null(),
        "{response:#}"
    );
    assert_eq!(
        typography(&resolved(&response["scene"], &kit)),
        typography(&before)
    );
    assert!(response["scene"]["nodes"]["support"]["kind"]["line_height_token"].is_null());
}

#[test]
fn missing_required_role_refuses_edit_without_mutating_scene() {
    let (mut authored, kit) = fixture();
    authored["nodes"]["support"]["kind"]["style_token"] = json!("type.missing");
    let response = helper(json!({"action":"compile_dsl_into_scene", "scene":authored,
        "brand_kit":kit, "source":"#support fill(#123456)"}));
    assert!(
        !response["dsl"]["compile_output"]["halted_at"].is_null(),
        "{response:#}"
    );
    assert_eq!(response["scene"], authored);
}

#[test]
fn structured_fill_edits_match_preview_replay_and_restore_exactly() {
    let (authored, kit) = fixture();
    let before = resolved(&authored, &kit);
    for source in [&authored, &before] {
        let response = helper(json!({"action":"apply_structured_edit", "scene":source,
        "brand_kit":kit, "edit":{"kind":"modify",
            "target":{"kind":"node","id":"support"},
            "patch":{"kind":"node","value":{"fills":{"kind":"set","value":[
                {"id":"recolor", "paint":{"kind":"solid","color":{"kind":"hex","value":"#123456"}}}
            ]}}}}}));
        assert_eq!(response["ok"], true, "{response:#}");
        let replay = helper(json!({"action":"apply_operations", "scene":authored,
            "operations":response["operations"]}));
        assert_eq!(replay["ok"], true, "{replay:#}");
        assert_eq!(
            typography(&resolved(&response["scene"], &kit)),
            typography(&before)
        );
        assert_eq!(
            typography(&resolved(&replay["scene"], &kit)),
            typography(&before)
        );
        let undo = helper(json!({"action":"apply_operations", "scene":replay["scene"],
            "operations":replay["edit"]["inverse_operations"]}));
        assert_eq!(undo["scene"], authored);
    }
}

#[test]
fn explicit_channel_reauthoring_is_not_replaced_by_preservation() {
    let (authored, kit) = fixture();
    let response = helper(json!({"action":"compile_dsl_into_scene", "scene":authored,
        "brand_kit":kit, "source":"#support fill(#123456) lh($space.xs) font_size($type.size.2xl)"}));
    assert!(
        response["dsl"]["compile_output"]["halted_at"].is_null(),
        "{response:#}"
    );
    let text = &response["scene"]["nodes"]["support"]["kind"];
    assert_eq!(text["line_height_token"], "space.xs");
    assert_eq!(text["font_size_token"], "type.size.2xl");
    let after = resolved(&response["scene"], &kit);
    assert_eq!(after["nodes"]["support"]["kind"]["line_height"], 4.0);
}

fn resolved(scene: &Value, kit: &Value) -> Value {
    let response = helper(json!({"action":"preflight_scene", "scene":scene, "brand_kit":kit}));
    assert_eq!(response["ok"], true, "{response:#}");
    assert_eq!(response["preflight"]["has_errors"], false, "{response:#}");
    response["scene"].clone()
}

fn typography(scene: &Value) -> Value {
    let text = &scene["nodes"]["support"]["kind"];
    json!({"font_family":text["font_family"], "font_size":text["font_size"],
        "font_weight":text["font_weight"], "line_height":text["line_height"],
        "letter_spacing":text["letter_spacing"]})
}

#[test]
fn fill_only_preserves_effective_type_from_authored_seed() {
    let (authored, kit) = fixture();
    let before = resolved(&authored, &kit);
    assert_ne!(
        typography(&authored),
        typography(&before),
        "fixture needs distinct raw fallbacks"
    );
    let response = helper(json!({"action":"compile_dsl_into_scene", "scene":authored,
        "brand_kit":kit, "source":"#support fill(#123456)"}));
    assert_eq!(response["ok"], true, "{response:#}");
    assert!(
        response["dsl"]["compile_output"]["halted_at"].is_null(),
        "{response:#}"
    );
    let after = resolved(&response["scene"], &kit);
    assert_eq!(
        typography(&after),
        typography(&before),
        "recolor must preserve effective typography"
    );
    assert_eq!(
        response["scene"]["nodes"]["other"],
        authored["nodes"]["other"]
    );
}

#[test]
fn fill_only_operation_replay_matches_preflighted_working_scene() {
    let (authored, kit) = fixture();
    let before = resolved(&authored, &kit);
    let response = helper(json!({"action":"compile_dsl_into_scene", "scene":before,
        "brand_kit":kit, "source":"#support fill(#123456)"}));
    assert_eq!(response["ok"], true, "{response:#}");
    let operations = &response["dsl"]["compile_output"]["operations"];
    let replay =
        helper(json!({"action":"apply_operations", "scene":authored, "operations":operations}));
    assert_eq!(replay["ok"], true, "{replay:#}");
    let preview = resolved(&response["scene"], &kit);
    let saved = resolved(&replay["scene"], &kit);
    assert_eq!(
        typography(&saved),
        typography(&preview),
        "accepted operation replay must match preview"
    );
    assert_eq!(typography(&saved), typography(&before));
    let undo = helper(json!({"action":"apply_operations", "scene":replay["scene"],
        "operations":replay["edit"]["inverse_operations"]}));
    assert_eq!(undo["ok"], true, "{undo:#}");
    assert_eq!(
        undo["scene"], authored,
        "undo must restore authored bindings and all original fields"
    );
}
