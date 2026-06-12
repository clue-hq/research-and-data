use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Output, Stdio};

const MINIMAL_SCENE: &str = include_str!("../../lumen-core/fixtures/minimal_scene.json");
const GENERATED_RASTER: &str =
    include_str!("../../lumen-core/fixtures/assets/generated_raster_asset.json");
const VALID_INSIGHT_HEALTH_STYLES: &str =
    include_str!("../../lumen-core/fixtures/styles/valid_insight_health.styles");
const INVALID_DUPLICATE_TOKEN_STYLES: &str =
    include_str!("../../lumen-core/fixtures/styles/invalid_duplicate_token.styles");

fn helper(request: Value) -> Value {
    let output = helper_output(request, &[]);
    assert!(output.status.success(), "{output:?}");
    serde_json::from_slice(&output.stdout).expect("helper response should be JSON")
}

fn helper_output(request: Value, envs: &[(&str, &str)]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_lumen-api-helper"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .envs(envs.iter().copied())
        .spawn()
        .expect("helper binary should spawn");

    child
        .stdin
        .as_mut()
        .expect("stdin should be available")
        .write_all(request.to_string().as_bytes())
        .expect("request should write");

    child.wait_with_output().expect("helper should exit")
}

fn minimal_scene() -> Value {
    serde_json::from_str(MINIMAL_SCENE).unwrap()
}

fn generated_asset() -> Value {
    serde_json::from_str(GENERATED_RASTER).unwrap()
}

fn platform_brand_kit() -> Value {
    let response = helper(json!({ "action": "platform_default_brand_kit" }));
    assert_eq!(response["ok"], true, "{response:#?}");
    response["brand_kit"].clone()
}

fn tokenized_scene() -> Value {
    let mut scene = minimal_scene();
    scene["nodes"]["node_contact_name"]["kind"]["style_token"] = json!("type.body");
    scene["slots"] = json!({});
    scene
}

fn asset_placeholder_node() -> Value {
    json!({
        "id": "node_hero_image",
        "name": "Hero image",
        "kind": { "kind": "rect" },
        "transform": {
            "x": 24.0,
            "y": 76.0,
            "rotation": 0.0,
            "skew_x": 0.0,
            "skew_y": 0.0,
            "flip_x": false,
            "flip_y": false
        },
        "size": {
            "width": { "kind": "fixed", "value": 120.0 },
            "height": { "kind": "fixed", "value": 67.5 }
        },
        "children": [],
        "fills": [],
        "strokes": [],
        "corner": {
            "top_left": 0.0,
            "top_right": 0.0,
            "bottom_right": 0.0,
            "bottom_left": 0.0
        },
        "opacity": 1.0,
        "clip": false,
        "layout": null,
        "computed": null,
        "locked": false
    })
}

fn image_slot() -> Value {
    json!({
        "id": "slot_campaign_hero_image",
        "key": "campaign.hero_image",
        "label": "Hero image",
        "content_type": "image",
        "scope": { "kind": "document" },
        "bound_nodes": ["node_hero_image"],
        "required": false,
        "placeholder": "Generated clinic hero",
        "overflow": { "kind": "error" },
        "formatting": {
            "max_length": null,
            "allowed_pattern": null,
            "preserve_case": true
        },
        "cardinality": {
            "min_items": 1,
            "max_items": 1
        },
        "conditional": null,
        "repeater": null,
        "validation": {
            "samples": [],
            "worst_case": null,
            "max_length": null
        },
        "image_policy": {
            "fit": "cover",
            "focal_point": { "x": 0.5, "y": 0.42 },
            "min_dpi": 72,
            "preserve_transparency": false,
            "aspect_ratio": 1.7777777777777777
        },
        "editability": "template_and_instance",
        "binding_hints": []
    })
}

fn asset_operations() -> Vec<Value> {
    vec![
        json!({
            "kind": "insert_node",
            "parent": { "kind": "page", "id": "page_a4" },
            "index": 1,
            "node": asset_placeholder_node()
        }),
        json!({
            "kind": "upsert_slot",
            "slot": image_slot()
        }),
        json!({
            "kind": "upsert_asset",
            "asset": generated_asset()
        }),
        json!({
            "kind": "place_asset_in_slot",
            "slot_id": "slot_campaign_hero_image",
            "asset_id": "asset_generated_hero",
            "placement": {
                "fit": "cover",
                "focal_point": { "x": 0.5, "y": 0.42 },
                "preserve_transparency": false,
                "alt_text": "Generated clinic hero"
            }
        }),
    ]
}

#[test]
fn validates_scene_through_cli() {
    let response = helper(json!({
        "action": "validate_scene",
        "scene": minimal_scene()
    }));

    assert_eq!(response["ok"], true);
    assert!(response
        .get("diagnostics")
        .and_then(Value::as_array)
        .unwrap_or(&Vec::new())
        .iter()
        .all(|diagnostic| diagnostic["severity"] != "error"));
}

#[test]
fn emits_boundary_logs_when_enabled() {
    let output = helper_output(
        json!({
            "action": "validate_scene",
            "scene": minimal_scene()
        }),
        &[
            ("LUMEN_CORE_HELPER_LOG", "1"),
            ("LUMEN_REQUEST_ID", "req_helper_cli_test"),
            ("LUMEN_CORE_CALL_ID", "core_helper_cli_test"),
        ],
    );
    assert!(output.status.success(), "{output:?}");
    let response: Value =
        serde_json::from_slice(&output.stdout).expect("helper response should be JSON");
    assert_eq!(response["ok"], true);

    let stderr = String::from_utf8(output.stderr).expect("stderr should be utf8");
    let events = stderr
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).expect("stderr line should be JSON"))
        .collect::<Vec<_>>();
    assert_eq!(events.len(), 2, "{events:#?}");
    assert_eq!(events[0]["source"], "lumen-api-helper");
    assert_eq!(events[0]["event"], "core_helper_started");
    assert_eq!(events[0]["action"], "validate_scene");
    assert_eq!(events[0]["request_id"], "req_helper_cli_test");
    assert_eq!(events[0]["helper_call_id"], "core_helper_cli_test");
    assert_eq!(events[1]["event"], "core_helper_completed");
    assert_eq!(events[1]["ok"], true);
    assert_eq!(events[1]["diagnostic_count"].as_u64(), Some(0));
}

#[test]
fn applies_operation_batch_through_checked_core() {
    let response = helper(json!({
        "action": "apply_operations",
        "scene": minimal_scene(),
        "operations": [{
            "kind": "update_document",
            "patch": {
                "title": { "kind": "set", "value": "Updated letter" },
                "artifact_type": { "kind": "unchanged" },
                "medium": { "kind": "unchanged" },
                "brand_kit": { "kind": "unchanged" }
            }
        }]
    }));

    assert_eq!(response["ok"], true);
    assert_eq!(response["applied_operations"], 1);
    assert_eq!(response["scene"]["meta"]["title"], "Updated letter");
}

#[test]
fn applies_sparse_structured_edit_patch_through_checked_core() {
    let response = helper(json!({
        "action": "apply_structured_edit",
        "scene": minimal_scene(),
        "edit": {
            "kind": "modify",
            "target": { "kind": "node", "id": "node_contact_name" },
            "patch": {
                "kind": "node",
                "value": {
                    "text": {
                        "content": { "kind": "set", "value": "Targeted repair headline" },
                        "font_size": { "kind": "set", "value": 16.0 }
                    }
                }
            }
        }
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["applied_operations"], 1);
    assert_eq!(response["operations"].as_array().unwrap().len(), 1);
    assert_eq!(response["operations"][0]["kind"], "update_node");
    assert_eq!(response["edit"]["kind"], "modify");
    assert_eq!(
        response["scene"]["nodes"]["node_contact_name"]["kind"]["content"],
        "Targeted repair headline"
    );
    assert_eq!(
        response["scene"]["nodes"]["node_contact_name"]["kind"]["font_size"],
        16.0
    );
}

#[test]
fn structured_edit_failure_returns_diagnostics_without_scene() {
    let response = helper(json!({
        "action": "apply_structured_edit",
        "scene": minimal_scene(),
        "edit": {
            "kind": "delete",
            "target": { "kind": "node", "id": "missing_node" }
        }
    }));

    assert_eq!(response["ok"], false, "{response:#?}");
    assert_eq!(response["scene"], Value::Null);
    assert_eq!(response["error"]["code"], "edit.target_not_found");
    assert_eq!(response["diagnostics"][0]["code"], "edit.target_not_found");
}

#[test]
fn applies_asset_operations_through_checked_core_bridge() {
    let response = helper(json!({
        "action": "apply_operations",
        "scene": minimal_scene(),
        "operations": asset_operations()
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["applied_operations"], 4);
    assert_eq!(
        response["scene"]["assets"]["asset_generated_hero"]["kind"],
        "raster_image"
    );
    assert_eq!(
        response["scene"]["nodes"]["node_hero_image"]["kind"],
        json!({
            "kind": "image",
            "asset_id": "asset_generated_hero",
            "alt": "Generated clinic hero"
        })
    );
    assert_eq!(
        response["scene"]["nodes"]["node_hero_image"]["asset_placement"]["fit"],
        "cover"
    );
}

#[test]
fn compiles_dsl_into_scene_through_core_bridge() {
    let response = helper(json!({
        "action": "compile_dsl_into_scene",
        "scene": minimal_scene(),
        "source": r#"
page page_agent
  helper_headline text "Surgery-first scheduling" p(24,96) s(240,40) font("Inter",20,700,left) fill(#111827)
"#
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["applied_operations"], 2);
    assert_eq!(
        response["scene"]["nodes"]["helper_headline"]["kind"]["content"],
        "Surgery-first scheduling"
    );
    assert_eq!(
        response["dsl"]["compile_output"]["operations"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    assert!(response["dsl"]["session_snapshot"].is_object());
}

#[test]
fn preserves_dsl_session_across_helper_compile_blocks() {
    let first = helper(json!({
        "action": "compile_dsl_into_scene",
        "scene": minimal_scene(),
        "source": r#"
page page_agent
  hero frame p(24,24) s(400,200)
"#
    }));

    assert_eq!(first["ok"], true, "{first:#?}");
    let second = helper(json!({
        "action": "compile_dsl_into_scene",
        "scene": first["scene"].clone(),
        "dsl_session": first["dsl"]["session_snapshot"].clone(),
        "source": "    helper_body text \"Session child\" p(16,16) s(200,40) font(\"Inter\",16,500,left) fill(#111827)"
    }));

    assert_eq!(second["ok"], true, "{second:#?}");
    assert_eq!(second["applied_operations"], 1);
    assert_eq!(
        second["scene"]["nodes"]["hero"]["children"],
        json!(["helper_body"])
    );
    assert_eq!(
        second["scene"]["nodes"]["helper_body"]["kind"]["content"],
        "Session child"
    );
}

#[test]
fn exports_svg_preview_through_core_bridge() {
    let response = helper(json!({
        "action": "export_preview",
        "scene": minimal_scene(),
        "format": "svg",
        "page_ids": ["page_a4"]
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["export"]["artifacts"][0]["format"], "svg");
    assert_eq!(
        response["export"]["artifacts"][0]["mime_type"],
        "image/svg+xml"
    );
    assert!(
        response["export"]["artifacts"][0]["bytes"]
            .as_array()
            .unwrap()
            .len()
            > 20
    );
}

#[test]
fn rejects_invalid_operation_batch_without_scene() {
    let response = helper(json!({
        "action": "apply_operations",
        "scene": minimal_scene(),
        "operations": [{
            "kind": "insert_node",
            "parent": { "kind": "page", "id": "missing_page" },
            "index": 0,
            "node": {
                "id": "node_orphan",
                "name": null,
                "kind": { "kind": "rect" },
                "transform": {
                    "x": 0.0,
                    "y": 0.0,
                    "rotation": 0.0,
                    "skew_x": 0.0,
                    "skew_y": 0.0,
                    "flip_x": false,
                    "flip_y": false
                },
                "size": {
                    "width": { "kind": "fixed", "value": 10.0 },
                    "height": { "kind": "fixed", "value": 10.0 }
                },
                "children": [],
                "fills": [],
                "strokes": [],
                "corner": {
                    "top_left": 0.0,
                    "top_right": 0.0,
                    "bottom_right": 0.0,
                    "bottom_left": 0.0
                },
                "opacity": 1.0,
                "clip": false,
                "layout": null,
                "computed": null,
                "locked": false
            }
        }]
    }));

    assert_eq!(response["ok"], false);
    assert_eq!(response["error"]["code"], "op.page_missing");
    assert!(response.get("scene").is_none());
}

#[test]
fn preflights_with_platform_default_brand_kit() {
    let brand_kit = platform_brand_kit();

    let response = helper(json!({
        "action": "preflight_scene",
        "scene": tokenized_scene(),
        "brand_kit": brand_kit
    }));

    assert_eq!(response["ok"], true);
    assert_eq!(response["preflight"]["has_errors"], false);
    assert!(response["preflight"]["layout_operations"]
        .as_array()
        .unwrap()
        .iter()
        .any(|operation| operation["kind"] == "update_node"));
}

#[test]
fn validates_product_ready_brand_kit_through_core_bridge() {
    let brand_kit = platform_brand_kit();

    let response = helper(json!({
        "action": "validate_brand_kit",
        "brand_kit": brand_kit,
        "product_ready": true
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert!(response
        .get("diagnostics")
        .and_then(Value::as_array)
        .unwrap_or(&Vec::new())
        .iter()
        .all(|diagnostic| diagnostic["severity"] != "error"));
}

#[test]
fn compiles_styles_brand_kit_through_core_bridge() {
    let response = helper(json!({
        "action": "compile_styles_brand_kit",
        "source": VALID_INSIGHT_HEALTH_STYLES,
        "brand_kit_id": "brand_kit_insight_health",
        "version": 4,
        "name": "Insight Health"
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["brand_kit"]["id"], "brand_kit_insight_health");
    assert_eq!(response["brand_summary"]["product_ready"], true);
    assert!(response["brand_summary"]["tokens"]["surface_tokens"]
        .as_array()
        .unwrap()
        .iter()
        .any(|token| token == "surface.brand"));
    assert!(response["brand_summary"]["tokens"]["typography_tokens"]
        .as_array()
        .unwrap()
        .iter()
        .any(|token| token == "type.headline"));
    assert!(response["brand_summary"]["assets"]["image_asset_tokens"]
        .as_array()
        .unwrap()
        .iter()
        .any(|token| token == "asset.illustration.primary"));
}

#[test]
fn rejects_invalid_styles_brand_kit_through_core_bridge() {
    let response = helper(json!({
        "action": "compile_styles_brand_kit",
        "source": INVALID_DUPLICATE_TOKEN_STYLES,
        "brand_kit_id": "brand_kit_invalid",
        "version": 1,
        "name": "Invalid"
    }));

    assert_eq!(response["ok"], false, "{response:#?}");
    assert_eq!(response["error"]["code"], "helper.brand_styles");
    assert!(response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|diagnostic| diagnostic["severity"] == "error"));
}

#[test]
fn generates_brand_kit_from_seed_through_core_bridge() {
    let response = helper(json!({
        "action": "generate_brand_kit",
        "seed": {
            "id": "brand_kit_seeded_insight",
            "version": 2,
            "name": "Seeded Insight Health",
            "primary_color": "#075E68",
            "description": "Healthcare automation brand kit generated from seed inputs.",
            "secondary_color": "#0F766E",
            "accent_color": "#22C55E",
            "neutral_color": "#111827",
            "preferred_fonts": ["Source Sans 3", "Arial"],
            "logo_refs": [{
                "logo_id": "primary",
                "asset_id": "asset_logo_primary",
                "usage": "primary",
                "color_mode": "full_color",
                "variant": "default",
                "width": 160.0,
                "height": 48.0
            }],
            "tone_words": ["clinical", "calm", "expert"],
            "website_url": "https://example.test",
            "style_guide_asset_ids": [],
            "sources": [],
            "default_mode": {
                "values": {
                    "theme": "light",
                    "density": "comfortable",
                    "accessibility": "standard",
                    "medium": "digital"
                }
            }
        }
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["brand_kit"]["id"], "brand_kit_seeded_insight");
    assert_eq!(response["brand_summary"]["product_ready"], true);
    assert!(response["brand_generation"]["confidence"]
        .as_f64()
        .is_some_and(|confidence| confidence > 0.6));
    assert!(response["brand_summary"]["assets"]["logo_tokens"]
        .as_array()
        .unwrap()
        .iter()
        .any(|token| token == "logo.primary"));
}

#[test]
fn summarizes_brand_kit_for_authoring_through_core_bridge() {
    let brand_kit = platform_brand_kit();
    let response = helper(json!({
        "action": "summarize_brand_kit",
        "brand_kit": brand_kit
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["brand_summary"]["product_ready"], true);
    assert!(response["brand_summary"]["authoring_rules"]
        .as_array()
        .unwrap()
        .iter()
        .any(|rule| rule
            .as_str()
            .is_some_and(|rule| rule.contains("Use semantic tokens"))));
}

#[test]
fn validates_scene_brand_governance_through_core_bridge() {
    let brand_kit = platform_brand_kit();
    let response = helper(json!({
        "action": "validate_scene_brand_governance",
        "scene": minimal_scene(),
        "brand_kit": brand_kit,
        "strictness": "strict"
    }));

    assert_eq!(response["ok"], false, "{response:#?}");
    assert!(response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|diagnostic| diagnostic["code"] == "LUMB0805"
            && diagnostic["message"]
                .as_str()
                .is_some_and(|message| message.contains("raw typography"))));
    assert!(response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|diagnostic| diagnostic["hint"]
            .as_str()
            .is_some_and(|hint| hint.contains("style($type."))));
}

#[test]
fn compares_brand_kit_compatibility_through_core_bridge() {
    let from = platform_brand_kit();
    let mut to = from.clone();
    to["version"] = json!(2);
    to["tokens"]["colors"]
        .as_object_mut()
        .unwrap()
        .remove("surface.brand");

    let response = helper(json!({
        "action": "compare_brand_kit_compatibility",
        "from": from,
        "to": to
    }));

    assert_eq!(response["ok"], false, "{response:#?}");
    assert_eq!(
        response["brand_compatibility"]["status"],
        "migration_required"
    );
    assert!(response["brand_compatibility"]["token_changes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|change| change["path"] == "surface.brand" && change["kind"] == "removed"));
    assert!(response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|diagnostic| diagnostic["code"] == "LUMB0814"));
}

#[test]
fn finalizes_template_through_core_operation() {
    let response = helper(json!({
        "action": "finalize_template",
        "scene": minimal_scene(),
        "template_revision_id": "tmpl_test"
    }));

    assert_eq!(response["ok"], true);
    assert_eq!(response["scene"]["meta"]["status"]["kind"], "finalized");
    assert_eq!(
        response["scene"]["meta"]["status"]["template_revision_id"],
        "tmpl_test"
    );
}

const LOGO_PNG_BYTES: &[u8] =
    include_bytes!("../../lumen-export/fixtures/assets/acme-logo-8x8-red.png");

fn ingest_request(store_root: &str) -> Value {
    use base64::Engine;
    json!({
        "action": "ingest_asset",
        "store_root": store_root,
        "bytes_base64": base64::engine::general_purpose::STANDARD.encode(LOGO_PNG_BYTES),
        "asset_id": "asset_uploaded_logo_live",
        "label": "Uploaded logo",
        "declared_mime_type": "image/png",
        "filename": "acme-logo.png",
        "kind": "logo",
        "uploaded_by": "designer",
        "tags": ["logo"]
    })
}

#[test]
fn ingest_asset_stores_bytes_and_resolver_wires_export() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let ingested = helper(ingest_request(&store_root));
    assert_eq!(ingested["ok"], true, "{ingested:#?}");
    let record = ingested["asset"]["record"].clone();
    assert_eq!(record["kind"], "logo");
    assert_eq!(record["media"]["mime_type"], "image/png");
    assert_eq!(record["media"]["location"]["provider"], "local-store");
    assert_eq!(ingested["asset"]["deduplicated"], false);

    let relative_path = ingested["asset"]["relative_path"]
        .as_str()
        .expect("relative path");
    assert!(
        store_dir.path().join(relative_path).is_file(),
        "bytes should land under the digest key"
    );

    let again = helper(ingest_request(&store_root));
    assert_eq!(again["asset"]["deduplicated"], true, "{again:#?}");

    let mut operations = asset_operations();
    // The uploaded fixture is a square logo; align the slot policy with the
    // probed aspect ratio so placement validation passes.
    operations[1]["slot"]["image_policy"]["aspect_ratio"] = json!(1.0);
    operations[2] = json!({ "kind": "upsert_asset", "asset": record });
    operations[3]["asset_id"] = json!("asset_uploaded_logo_live");
    let applied = helper(json!({
        "action": "apply_operations",
        "scene": minimal_scene(),
        "operations": operations
    }));
    assert_eq!(applied["ok"], true, "{applied:#?}");

    let exported = helper(json!({
        "action": "export_preview",
        "scene": applied["scene"].clone(),
        "format": "svg",
        "page_ids": ["page_a4"],
        "asset_store_root": store_root
    }));
    assert_eq!(exported["ok"], true, "{exported:#?}");
    let svg_bytes: Vec<u8> = exported["export"]["artifacts"][0]["bytes"]
        .as_array()
        .expect("bytes array")
        .iter()
        .map(|value| value.as_u64().expect("byte") as u8)
        .collect();
    let svg = String::from_utf8(svg_bytes).expect("utf8 svg");
    assert!(
        svg.contains("data:image/png;base64,"),
        "store-backed resolver should embed real bytes: {svg}"
    );
    let diagnostics = exported["diagnostics"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for code in ["LUME0202", "LUME0210", "LUME0211"] {
        assert!(
            !diagnostics
                .iter()
                .any(|diagnostic| diagnostic["code"] == code),
            "no unresolved-asset diagnostics expected: {diagnostics:#?}"
        );
    }
}

#[test]
fn ingest_asset_rejects_mime_mismatch_without_storing() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = ingest_request(&store_root);
    request["declared_mime_type"] = json!("image/jpeg");
    let response = helper(request);

    assert_eq!(response["ok"], false, "{response:#?}");
    assert_eq!(response["error"]["code"], "ingest.mime_mismatch");
    assert_eq!(response["diagnostics"][0]["code"], "LUMA0600");
    assert_eq!(
        std::fs::read_dir(store_dir.path())
            .expect("read dir")
            .count(),
        0,
        "rejected uploads must not write bytes"
    );
}

#[test]
fn generate_qr_is_deterministic_and_stores_sanitized_vector_asset() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();
    let request = |asset_id: &str| {
        json!({
            "action": "generate_qr",
            "store_root": store_root,
            "data": "https://lumen.example/a/acme-health",
            "asset_id": asset_id,
            "label": "Acme landing QR",
            "print": true,
            "target_width_mm": 24.0
        })
    };

    let first = helper(request("asset_qr_acme"));
    assert_eq!(first["ok"], true, "{first:#?}");
    let record = &first["asset"]["record"];
    assert_eq!(record["kind"], "vector");
    assert_eq!(record["media"]["mime_type"], "image/svg+xml");
    assert_eq!(record["source"]["kind"], "generated");
    assert_eq!(record["source"]["model"], "qr-v1");
    assert_eq!(record["provenance"]["source_label"], "generated:qr");
    assert_eq!(record["license"]["allow_export"], true);
    assert_eq!(first["asset"]["qr"]["ec_level"], "h");
    assert_eq!(first["asset"]["qr"]["quiet_zone_modules"], 4);
    assert!(first["asset"]["qr"]["module_count"].as_u64().unwrap() > 0);
    assert_eq!(first["asset"]["deduplicated"], false);

    // Determinism: a second generation of the same data dedups to the
    // same stored digest under a different asset id.
    let second = helper(request("asset_qr_acme_again"));
    assert_eq!(second["ok"], true, "{second:#?}");
    assert_eq!(second["asset"]["deduplicated"], true);
    assert_eq!(
        first["asset"]["digest_value"],
        second["asset"]["digest_value"]
    );

    // Stored bytes are sanitized SVG with the quiet-zone viewBox.
    let stored = store_dir
        .path()
        .join(first["asset"]["relative_path"].as_str().unwrap());
    let svg = std::fs::read_to_string(stored).expect("stored svg");
    assert!(svg.contains("<svg"));
    assert!(!svg.contains("<script"));
}

#[test]
fn generate_qr_surfaces_print_size_and_empty_data_diagnostics() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let small = helper(json!({
        "action": "generate_qr",
        "store_root": store_root,
        "data": "https://lumen.example/a/acme-health",
        "asset_id": "asset_qr_small",
        "print": true,
        "target_width_mm": 12.0
    }));
    assert_eq!(small["ok"], true, "{small:#?}");
    assert!(small["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|diagnostic| diagnostic["code"] == "LUMA0700"));

    let empty = helper(json!({
        "action": "generate_qr",
        "store_root": store_root,
        "data": "   ",
        "asset_id": "asset_qr_empty"
    }));
    assert_eq!(empty["ok"], false);
    assert_eq!(empty["error"]["code"], "qr.empty_data");
    assert_eq!(empty["diagnostics"][0]["code"], "LUMA0702");
}

#[test]
fn generate_asset_normalizes_provider_output_with_provenance_and_licensing() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let response = helper(json!({
        "action": "generate_asset",
        "store_root": store_root,
        "provider": "stub-image-v0",
        "asset_id": "asset_stub_hero",
        "label": "Stub hero",
        "request": {
            "request_id": "req_stub_hero",
            "prompt": "teal clinic hero",
            "output_kind": "raster_image",
            "target_node_id": null,
            "target_slot_id": null,
            "constraints": {
                "width": 64,
                "height": 32,
                "mime_type": null,
                "transparent_background": null,
                "brand_notes": []
            }
        }
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    let record = &response["asset"]["record"];
    assert_eq!(record["kind"], "raster_image");
    assert_eq!(record["source"]["kind"], "generated");
    assert_eq!(record["source"]["model"], "stub-image-v0");
    assert_eq!(record["source"]["request_id"], "req_stub_hero");
    assert_eq!(
        record["provenance"]["source_label"],
        "generated:stub-image-v0"
    );
    assert_eq!(record["license"]["name"], "stub_generated");
    assert_eq!(record["raster"]["pixel_width"], 64);
    assert_eq!(record["raster"]["pixel_height"], 32);
    assert!(record["media"]["thumbnail"].is_object());
    assert_eq!(response["asset"]["provider"]["id"], "stub-image-v0");
    assert!(response["asset"]["provider"]["metadata"]["prompt_digest"].is_string());

    let stored = store_dir
        .path()
        .join(response["asset"]["relative_path"].as_str().unwrap());
    assert!(stored.is_file(), "provider bytes should be stored");
}

#[test]
fn generate_asset_rejects_unknown_providers() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let response = helper(json!({
        "action": "generate_asset",
        "store_root": store_dir.path().to_string_lossy(),
        "provider": "imaginary-model-v9",
        "asset_id": "asset_nope",
        "request": {
            "request_id": "req_nope",
            "prompt": "anything",
            "output_kind": "raster_image",
            "target_node_id": null,
            "target_slot_id": null,
            "constraints": {
                "width": null,
                "height": null,
                "mime_type": null,
                "transparent_background": null,
                "brand_notes": []
            }
        }
    }));

    assert_eq!(response["ok"], false);
    assert_eq!(response["error"]["code"], "provider.unknown");
}

// ---------------------------------------------------------------------------
// Phase G: derive_instance / validate_binding_set (slice G5)
// ---------------------------------------------------------------------------

const MAILER_REVISION: &str =
    include_str!("../../lumen-core/fixtures/conformance/phase_g_mailer_revision.json");
const NOMINAL_BINDING: &str = include_str!("../../lumen-core/fixtures/binding/nominal.json");

fn mailer_revision() -> Value {
    serde_json::from_str(MAILER_REVISION).unwrap()
}

fn nominal_binding() -> Value {
    serde_json::from_str(NOMINAL_BINDING).unwrap()
}

fn binding_logo_record() -> Value {
    json!({
        "id": "asset_acme_logo",
        "label": "Acme logo",
        "kind": "logo",
        "status": "ready",
        "source": { "kind": "uploaded", "asset_id": null, "filename": "acme.png", "uploaded_by": "ops" },
        "media": {
            "mime_type": "image/png",
            "filename": "acme.png",
            "byte_length": 2048,
            "digest": { "algorithm": "sha256", "value": "ab".repeat(32) },
            "location": null
        },
        "raster": {
            "pixel_width": 1200, "pixel_height": 400,
            "dpi_x": 300.0, "dpi_y": 300.0,
            "has_alpha": true, "color_profile": "srgb", "aspect_ratio": 3.0
        },
        "vector": null,
        "font": null,
        "logo": {
            "pixel_width": 1200, "pixel_height": 400,
            "width": 36.0, "height": 12.0,
            "dpi_x": 300.0, "dpi_y": 300.0,
            "has_transparency": true, "color_mode": "full_color", "clearspace": 2.0
        },
        "license": null,
        "provenance": { "created_by": null, "created_at": null, "source_label": null, "confidence": null, "notes": [] },
        "tags": ["logo"]
    })
}

fn derive_request(store_root: &str) -> Value {
    json!({
        "action": "derive_instance",
        "scene": mailer_revision(),
        "binding_set": nominal_binding(),
        "asset_records": [binding_logo_record()],
        "store_root": store_root
    })
}

#[test]
fn validate_binding_set_action_reports_precise_codes() {
    let response = helper(json!({
        "action": "validate_binding_set",
        "scene": mailer_revision(),
        "binding_set": nominal_binding(),
    }));
    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["instance"]["valid"], true);

    let mut invalid = nominal_binding();
    invalid["values"]
        .as_object_mut()
        .unwrap()
        .remove("contact.full_name");
    let response = helper(json!({
        "action": "validate_binding_set",
        "scene": mailer_revision(),
        "binding_set": invalid,
    }));
    assert_eq!(response["ok"], false, "{response:#?}");
    let codes: Vec<&str> = response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|d| d["code"].as_str())
        .collect();
    assert!(codes.contains(&"LUMG0012"), "{codes:?}");
}

#[test]
fn derive_instance_executes_the_qr_chain_with_digest_stability() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let first = helper(derive_request(&store_root));
    assert_eq!(first["ok"], true, "{first:#?}");
    assert_eq!(first["instance"]["has_errors"], false, "{first:#?}");

    let generated = &first["instance"]["generated"]["qr_landing"];
    assert_eq!(
        generated["record"]["id"], "asset_gen_bind_acme_dr_sharma_qr_landing",
        "generated asset ids are a pure function of (binding_set_id, entry)"
    );
    let digest = generated["digest_value"].as_str().expect("digest");
    let notes = generated["record"]["provenance"]["notes"]
        .as_array()
        .expect("notes");
    assert!(
        notes
            .iter()
            .any(|note| note.as_str() == Some("binding_set:bind_acme_dr_sharma")),
        "provenance must record the binding set: {notes:?}"
    );

    // The derived scene binds the generated QR to the UrlQr slot's node.
    let qr_node = &first["scene"]["nodes"]["node_qr"];
    assert_eq!(
        qr_node["kind"]["asset_id"], "asset_gen_bind_acme_dr_sharma_qr_landing",
        "{qr_node:#?}"
    );

    // Re-derivation: byte-identical derived scene and the same QR digest
    // (content-addressed store deduplicates the bytes).
    let second = helper(derive_request(&store_root));
    assert_eq!(
        serde_json::to_string(&first["scene"]).unwrap(),
        serde_json::to_string(&second["scene"]).unwrap(),
        "re-derivation must be byte-identical"
    );
    assert_eq!(
        second["instance"]["generated"]["qr_landing"]["digest_value"]
            .as_str()
            .unwrap(),
        digest,
        "same URL must produce the same QR digest"
    );
    assert_eq!(
        second["instance"]["generated"]["qr_landing"]["deduplicated"], true,
        "second run must hit the content-addressed store"
    );
}

#[test]
fn derive_instance_refuses_invalid_bindings_before_provider_execution() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = derive_request(&store_root);
    request["binding_set"]["values"]["campaign.cta"] = json!({
        "kind": "text",
        "value": "X".repeat(61)
    });
    let response = helper(request);
    assert_eq!(response["ok"], false, "{response:#?}");
    assert_eq!(response["error"]["code"], "instance.binding_invalid");
    let codes: Vec<&str> = response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|d| d["code"].as_str())
        .collect();
    assert!(codes.contains(&"LUMG0014"), "{codes:?}");
    // No provider executed: the store stays empty.
    assert!(
        std::fs::read_dir(store_dir.path())
            .unwrap()
            .next()
            .is_none(),
        "no bytes may be stored for refused derivations"
    );
}

#[test]
fn derive_instance_returns_fit_report_with_skia_truth() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    // Nominal content fits cleanly under real shaping.
    let nominal = helper(derive_request(&store_root));
    assert_eq!(nominal["ok"], true, "{nominal:#?}");
    let report = &nominal["instance"]["fit_report"];
    assert_eq!(report["status"], "fits", "{report:#?}");
    assert_eq!(report["binding_set_id"], "bind_acme_dr_sharma");

    // The worst-case headline overflows even at min font under Skia
    // measurement: the fit report surfaces it (zero silent overflows).
    let mut request = derive_request(&store_root);
    request["binding_set"] = serde_json::from_str::<Value>(include_str!(
        "../../lumen-core/fixtures/binding/worst_case.json"
    ))
    .unwrap();
    request["asset_records"][0]["id"] = json!("asset_meridian_logo");
    let worst = helper(request);
    assert_eq!(worst["ok"], true, "{worst:#?}");
    let report = &worst["instance"]["fit_report"];
    assert_eq!(report["status"], "overflow", "{report:#?}");
    let headline = report["slots"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["slot_key"] == "contact.full_name")
        .expect("headline entry");
    assert_eq!(headline["verdict"]["kind"], "overflow", "{headline:#?}");
    assert_eq!(headline["verdict"]["policy"], "shrink_font");
    assert_eq!(headline["beyond_worst_case"], true);
}
