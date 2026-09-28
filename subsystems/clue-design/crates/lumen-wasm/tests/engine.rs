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

#[test]
fn explicit_same_text_tokens_survive_wasm_wire_replay_but_raw_edits_detach() {
    let mut scene: Value = serde_json::from_str(MINIMAL_SCENE).unwrap();
    let text = &mut scene["nodes"]["node_contact_name"]["kind"];
    text["font_size"] = json!(16);
    text["style_token"] = json!("type.display");
    text["font_size_token"] = json!("type.size.7xl");
    let mut engine = Engine::from_scene_json(&scene.to_string()).unwrap();
    let mut kind = scene["nodes"]["node_contact_name"]["kind"].clone();
    kind["font_size"] = json!(80);
    let mut patch = node_transform_patch(0.0, 0.0);
    patch["transform"] = json!({"kind": "unchanged"});
    patch["kind"] = json!({"kind": "set", "value": kind});
    patch["explicit_text_tokens"] = json!({"style": true, "font_size": true});
    let operation = json!({"kind": "update_node", "node_id": "node_contact_name", "patch": patch});
    let result = parse(engine.apply_operations(&json!([operation]).to_string()));
    assert_eq!(result["ok"], true);
    let applied = parse(engine.scene_json());
    assert_eq!(
        applied["nodes"]["node_contact_name"]["kind"]["font_size_token"],
        "type.size.7xl"
    );
    let mut raw = operation;
    raw["patch"]
        .as_object_mut()
        .unwrap()
        .remove("explicit_text_tokens");
    raw["patch"]["kind"]["value"]["font_size"] = json!(44);
    let result = parse(engine.apply_operations(&json!([raw]).to_string()));
    assert_eq!(result["ok"], true);
    let applied = parse(engine.scene_json());
    assert_eq!(
        applied["nodes"]["node_contact_name"]["kind"]["font_size"].as_f64(),
        Some(44.0)
    );
    assert!(applied["nodes"]["node_contact_name"]["kind"]
        .get("style_token")
        .is_none());
    assert!(applied["nodes"]["node_contact_name"]["kind"]
        .get("font_size_token")
        .is_none());
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
fn slot_id_binding_matches_core_derivation() {
    // The editor pins its synchronous TS slotIdFromKey mirror against this
    // binding; this test pins the binding against lumen-core itself.
    assert_eq!(
        lumen_wasm::slot_id_for_key("account.name"),
        lumen_core::slot_id_for_key(&lumen_core::SlotKey::from("account.name")).to_string()
    );
    assert!(lumen_wasm::slot_id_for_key("account.name").starts_with("slot_account_name_"));
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
        // Baseline is the engine's relaid-out scene before the edit (the
        // engine establishes a computed baseline on load); the delta must
        // reconstruct the post-edit scene from THAT state, not from the raw
        // fixture (which carries no computed geometry).
        let mut snapshot: Value =
            serde_json::from_str(&engine.scene_json()).expect("baseline scene parses");
        let result = parse(engine.apply_structured_edit(&case["edit"].to_string()));
        assert_eq!(result["ok"], json!(true), "case {name}");

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
    // load_scene replaces state AND relays out, so the restored scene equals
    // a freshly loaded (relaid-out) baseline — the editor's render geometry is
    // single-source local heuristic, established identically on every load.
    let baseline: Value = serde_json::from_str(
        &Engine::from_scene_json(MINIMAL_SCENE)
            .expect("baseline loads")
            .scene_json(),
    )
    .expect("baseline scene");
    assert_eq!(restored, baseline);
}

// --- Editor coordinate-model fix (editor/coordinate-model-v0) -------------
// The browser engine now refreshes whole-tree `computed` geometry after every
// mutation and on load, so the editor renders parent and children from one
// coherent layout pass. These tests pin that behavior: a container drag keeps
// its children coherent, an unrelated edit perturbs nothing, and the derived
// geometry never leaks into the authored operations sent to the server.

const NESTED_SCENE: &str = include_str!("nested_frame_scene.json");

fn nested_engine() -> Engine {
    Engine::from_scene_json(NESTED_SCENE).expect("nested scene loads")
}

#[test]
fn set_measurements_makes_hug_text_geometry_skia_faithful() {
    // A hug-width text node takes its width from measurement (a fixed node
    // would not), so the editor-injected SkParagraph metrics become its
    // computed geometry (Wave 3 C4 measure-then-inject).
    let mut scene: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene json");
    scene["nodes"]["node_contact_name"]["size"] =
        json!({ "width": { "kind": "hug" }, "height": { "kind": "hug" } });
    let mut engine = Engine::from_scene_json(&scene.to_string()).expect("hug scene loads");

    let before = node_computed_width(&engine, "node_contact_name");

    // Provide a distinctive Skia width for the node's exact measurement input
    // (unconstrained → max_width omitted = None, the key layout uses).
    let measurements = json!([{
        "content": "Dr. Priya Sharma",
        "font_family": "Inter",
        "font_size": 18.0,
        "font_weight": 600,
        "line_height": 1.2,
        "letter_spacing": 0.0,
        "wrap": "wrap",
        "max_lines": null,
        "direction": "ltr",
        "width": 350.0,
        "height": 40.0
    }]);
    let ack = parse(engine.set_measurements(&measurements.to_string()));
    assert_eq!(ack["ok"], true, "{ack:#?}");
    assert_eq!(ack["count"], 1);

    let after = node_computed_width(&engine, "node_contact_name");
    assert_ne!(after, before, "heuristic width should be replaced");
    assert_eq!(after, 350.0, "computed width is the injected Skia width");

    // Legacy standalone reconcile/undo can replace geometry without changing
    // its text measurement signature, so it will not reinject these metrics.
    let original = scene.to_string();
    scene["nodes"]["node_contact_name"]["transform"]["x"] = json!(84.0);
    engine.load_scene(&scene.to_string()).expect("reconcile loads");
    assert_eq!(node_computed_width(&engine, "node_contact_name"), 350.0);
    assert_eq!(
        parse(engine.scene_json())["nodes"]["node_contact_name"]["computed"]["layout_bounds"]["x"],
        84.0
    );
    engine.load_scene(&original).expect("undo snapshot loads");
    assert_eq!(node_computed_width(&engine, "node_contact_name"), 350.0);

    // Clearing the override returns to the heuristic width.
    let clear = parse(engine.set_measurements("[]"));
    assert_eq!(clear["ok"], true);
    assert_eq!(node_computed_width(&engine, "node_contact_name"), before);
}

#[test]
fn measurement_ack_returns_unmet_layout_inputs_and_clears_them_after_shaping() {
    let mut engine = Engine::from_scene_json(MINIMAL_SCENE).expect("scene loads");
    let unconstrained = json!({
        "content": "Dr. Priya Sharma", "font_family": "Inter",
        "font_size": 18.0, "font_weight": 600, "line_height": 1.2,
        "letter_spacing": 0.0, "wrap": "wrap", "max_lines": null,
        "direction": "ltr", "width": 150.0, "height": 21.6
    });
    let ack = parse(engine.set_measurements(&json!([unconstrained]).to_string()));
    let missing = ack["missing"]
        .as_array()
        .expect("report unmet shaping requests");
    assert!(
        missing
            .iter()
            .all(|input| input["node_id"] == "node_contact_name"),
        "slot fixtures must retain their source node styling: {ack}"
    );
    assert!(
        missing.iter().any(|input| {
            input["content"] == "Dr. Priya Sharma"
                && input["max_width"] == 160.0
                && input["max_height"] == 28.0
        }),
        "the request is the engine's actual constraint, not an inferred container width: {ack}"
    );
    let mut filled = vec![unconstrained];
    for input in missing {
        let mut measured = input.clone();
        measured["width"] = json!(150.0);
        measured["height"] = json!(21.6);
        filled.push(measured);
    }
    let shaped = parse(engine.set_measurements(&json!(filled).to_string()));
    assert_eq!(shaped["missing"], json!([]));
}

#[test]
fn provided_lines_place_text_lines_and_narrow_the_hit_target() {
    // Plan 4 item F: `node_contact_name` is a fixed 160×28 box at (24,40) on
    // the minimal scene. A record keyed on that box (the key
    // `validate_text_nodes` measures with) carries ONE 60-wide line, so the
    // box's empty right half no longer hits the text.
    let mut engine = Engine::from_scene_json(MINIMAL_SCENE).expect("minimal scene loads");
    let measurements = json!([{
        "content": "Dr. Priya Sharma",
        "font_family": "Inter",
        "font_size": 18.0,
        "font_weight": 600,
        "line_height": 1.2,
        "letter_spacing": 0.0,
        "wrap": "wrap",
        "max_lines": null,
        "direction": "ltr",
        "max_width": 160.0,
        "max_height": 28.0,
        "width": 60.0,
        "height": 21.6,
        "lines": [{ "x": 0.0, "y": 0.0, "width": 60.0, "height": 21.6, "baseline": 17.0 }]
    }]);
    let ack = parse(engine.set_measurements(&measurements.to_string()));
    assert_eq!(ack["ok"], true, "{ack:#?}");

    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(
        scene["nodes"]["node_contact_name"]["computed"]["text_lines"],
        json!([{ "x": 24.0, "y": 40.0, "width": 60.0, "height": 21.6 }])
    );
    // Inside the box, right of the painted line: nothing (the page has no
    // other child).
    let miss = parse(engine.hit_test("page_a4", 150.0, 50.0));
    assert_eq!(miss["hit"], Value::Null, "{miss:#?}");
    // On the glyphs.
    let hit = parse(engine.hit_test("page_a4", 30.0, 50.0));
    assert_eq!(hit["hit"], "node_contact_name");
}

fn node_computed_width(engine: &Engine, node_id: &str) -> f64 {
    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    scene["nodes"][node_id]["computed"]["layout_bounds"]["width"]
        .as_f64()
        .expect("computed width")
}

#[test]
fn hit_test_returns_topmost_node_in_page_space() {
    // The engine relaid the tree on load, so hit-testing works over fresh
    // computed geometry (Wave 3 C3a). hero(40,40,400,300) ⊃ headline(60,60,
    // 200,40) and box(60,120,100,100); sibling(500,40,80,80).
    let engine = nested_engine();

    // Over the headline (a child): topmost is the child, stack is parent→child.
    let r = parse(engine.hit_test("page_a4", 70.0, 70.0));
    assert_eq!(r["hit"], "headline", "{r:#?}");
    assert_eq!(
        r["stack"],
        serde_json::json!(["hero", "headline"]),
        "bottom-to-top stack"
    );

    // Inside the hero frame but outside both children: the frame itself.
    let r2 = parse(engine.hit_test("page_a4", 300.0, 280.0));
    assert_eq!(r2["hit"], "hero");

    // Over the page-level sibling.
    let r3 = parse(engine.hit_test("page_a4", 520.0, 60.0));
    assert_eq!(r3["hit"], "sibling");

    // Empty canvas: no hit, empty stack.
    let r4 = parse(engine.hit_test("page_a4", 700.0, 520.0));
    assert_eq!(r4["hit"], Value::Null);
    assert_eq!(r4["stack"], serde_json::json!([]));
}

fn computed_bounds(scene: &Value, node_id: &str) -> (f64, f64, f64, f64) {
    let b = &scene["nodes"][node_id]["computed"]["layout_bounds"];
    (
        b["x"].as_f64().unwrap(),
        b["y"].as_f64().unwrap(),
        b["width"].as_f64().unwrap(),
        b["height"].as_f64().unwrap(),
    )
}

#[test]
fn load_establishes_whole_tree_computed_baseline() {
    let engine = nested_engine();
    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    // from_scene_json relaid out: every node has computed, parent-relative
    // child transforms resolved to absolute page coordinates.
    assert_eq!(computed_bounds(&scene, "hero").0, 40.0);
    assert_eq!(
        computed_bounds(&scene, "headline"),
        (60.0, 60.0, 200.0, 40.0)
    );
    assert_eq!(computed_bounds(&scene, "box"), (60.0, 120.0, 100.0, 100.0));
}

#[test]
fn container_drag_keeps_children_coherent() {
    let mut engine = nested_engine();
    // Drag the hero frame +100 in x (transform 40 -> 140).
    let operations = json!([{
        "kind": "update_node",
        "node_id": "hero",
        "patch": node_transform_patch(140.0, 40.0)
    }]);
    let result = parse(engine.apply_operations(&operations.to_string()));
    assert_eq!(result["ok"], true, "{result:#?}");

    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    let hero = computed_bounds(&scene, "hero");
    let headline = computed_bounds(&scene, "headline");
    let boxn = computed_bounds(&scene, "box");
    // Parent moved to 140; children moved by the SAME delta (+100) and keep
    // their exact relative offset inside the frame — no stale-offset desync,
    // no double-offset. This is the bug, fixed.
    assert_eq!(hero.0, 140.0);
    assert_eq!(headline.0, 160.0);
    assert_eq!(boxn.0, 160.0);
    assert_eq!(headline.0 - hero.0, 20.0, "relative offset preserved");
    assert_eq!(boxn.0 - hero.0, 20.0, "relative offset preserved");
    // y is untouched by an x-only drag.
    assert_eq!(headline.1, 60.0);
    assert_eq!(boxn.1, 120.0);
}

#[test]
fn unrelated_edit_does_not_perturb_other_nodes() {
    let mut engine = nested_engine();
    let before: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    let headline_before = computed_bounds(&before, "headline");
    let sibling_before = computed_bounds(&before, "sibling");

    // Move `box` (a sibling of headline inside hero). relayout is idempotent
    // for everything else: headline and the page-level sibling must not move.
    let operations = json!([{
        "kind": "update_node",
        "node_id": "box",
        "patch": node_transform_patch(20.0, 200.0)
    }]);
    parse(engine.apply_operations(&operations.to_string()));

    let after: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(computed_bounds(&after, "headline"), headline_before);
    assert_eq!(computed_bounds(&after, "sibling"), sibling_before);
    assert_eq!(computed_bounds(&after, "box").1, 240.0); // 40 + 200, moved
}

#[test]
fn non_geometry_edit_does_not_move_a_node() {
    let mut engine = nested_engine();
    let before: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    let headline_before = computed_bounds(&before, "headline");

    // A pure fill change clears computed on the node in core; relayout must
    // restore the SAME geometry (the node didn't move) — proving the broader
    // class of the bug (any render-affecting edit) is fixed, not just drag.
    let operations = json!([{
        "kind": "update_node",
        "node_id": "headline",
        "patch": {
            "name": { "kind": "unchanged" },
            "kind": { "kind": "unchanged" },
            "transform": { "kind": "unchanged" },
            "size": { "kind": "unchanged" },
            "fills": { "kind": "set", "value": [{
                "id": "fill_1",
                "paint": { "kind": "solid", "color": { "kind": "hex", "value": "#ff0000" } }
            }]},
            "strokes": { "kind": "unchanged" },
            "corner": { "kind": "unchanged" },
            "opacity": { "kind": "unchanged" },
            "opacity_token": { "kind": "unchanged" },
            "source_asset_id": { "kind": "unchanged" },
            "asset_placement": { "kind": "unchanged" },
            "clip": { "kind": "unchanged" },
            "layout": { "kind": "unchanged" },
            "computed": { "kind": "unchanged" },
            "locked": { "kind": "unchanged" },
            "effects": { "kind": "unchanged" }
        }
    }]);
    let result = parse(engine.apply_operations(&operations.to_string()));
    assert_eq!(result["ok"], true, "{result:#?}");

    let after: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(computed_bounds(&after, "headline"), headline_before);
}

#[test]
fn refreshed_computed_never_enters_authored_operations() {
    let mut engine = nested_engine();
    // A structured edit returns the canonical authored operations the editor
    // persists to the server. The relayout's computed writes must NOT appear
    // there — the server recomputes geometry canonically under Skia.
    let edit = json!({
        "kind": "move_after",
        "node_id": "headline",
        "anchor": "box"
    });
    let result = parse(engine.apply_structured_edit(&edit.to_string()));
    assert_eq!(result["ok"], true, "{result:#?}");
    let operations = result["operations"].as_array().expect("operations");
    for op in operations {
        // No operation may carry a computed `set` patch.
        let computed = &op["patch"]["computed"];
        assert_ne!(
            computed["kind"], "set",
            "authored op leaked a computed geometry write: {op:#?}"
        );
    }
}

#[test]
fn fixed_width_hug_text_takes_the_editor_height_measured_at_its_width() {
    // Ruling R8: `node_contact_name` fixed 160 wide, hug height. The editor's
    // line pass keys its record on `max_width = 160` with no height; that is
    // now the key the manual path measures with, so the injected height lands.
    let mut scene: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene json");
    scene["nodes"]["node_contact_name"]["size"] =
        json!({ "width": { "kind": "fixed", "value": 160.0 }, "height": { "kind": "hug" } });
    let mut engine = Engine::from_scene_json(&scene.to_string()).expect("scene loads");
    let measurements = json!([{
        "content": "Dr. Priya Sharma", "font_family": "Inter", "font_size": 18.0, "font_weight": 600,
        "line_height": 1.2, "letter_spacing": 0.0, "wrap": "wrap", "max_lines": null, "direction": "ltr",
        "max_width": 160.0, "width": 100.0, "height": 99.0
    }]);
    let ack = parse(engine.set_measurements(&measurements.to_string()));
    assert_eq!(ack["ok"], true, "{ack:#?}");
    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(
        scene["nodes"]["node_contact_name"]["computed"]["layout_bounds"]["height"],
        99.0
    );
    assert_eq!(
        scene["nodes"]["node_contact_name"]["computed"]["layout_bounds"]["width"],
        160.0
    );
}
