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
    assert_eq!(events[1]["diagnostic_count"].as_u64(), Some(1));
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

// Print W2: interactive PDF export renders VECTOR by default through the
// Skia PDF backend — live text, embedded subset fonts (LUME0427), print
// boxes written — instead of the early Helvetica-only vector writer
// (whose LUME0401 warning must be gone).
#[test]
fn exports_vector_pdf_preview_through_core_bridge() {
    let response = helper(json!({
        "action": "export_preview",
        "scene": minimal_scene(),
        "format": "pdf",
        "page_ids": ["page_a4"]
    }));

    assert_eq!(response["ok"], true, "{response:#?}");
    let artifact = &response["export"]["artifacts"][0];
    assert_eq!(artifact["format"], "pdf");
    assert_eq!(artifact["mime_type"], "application/pdf");
    let bytes: Vec<u8> = artifact["bytes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_u64().unwrap() as u8)
        .collect();
    assert!(bytes.starts_with(b"%PDF"), "not a PDF header");
    let raw = String::from_utf8_lossy(&bytes);
    assert!(raw.contains("FontFile2"), "vector PDF must embed fonts");
    assert!(raw.contains("/TrimBox"), "print boxes must be written");

    let codes: Vec<&str> = response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|diagnostic| diagnostic["code"].as_str())
        .collect();
    assert!(codes.contains(&"LUME0427"), "missing vector advice: {codes:?}");
    assert!(
        !codes.contains(&"LUME0401") && !codes.contains(&"LUME0402"),
        "stub-only fidelity warnings leaked into the seam path: {codes:?}"
    );
}

// D5 baseline: LUMEN_PDF_RENDERER=flattened selects the W0 raster-flattened
// renderer (LUME0426) for comparison runs.
#[test]
fn flattened_pdf_baseline_selectable_via_env() {
    let output = helper_output(
        json!({
            "action": "export_preview",
            "scene": minimal_scene(),
            "format": "pdf",
            "page_ids": ["page_a4"]
        }),
        &[("LUMEN_PDF_RENDERER", "flattened")],
    );
    assert!(output.status.success(), "{output:?}");
    let response: Value =
        serde_json::from_slice(&output.stdout).expect("helper response should be JSON");

    assert_eq!(response["ok"], true, "{response:#?}");
    let codes: Vec<&str> = response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|diagnostic| diagnostic["code"].as_str())
        .collect();
    assert!(codes.contains(&"LUME0426"), "missing flatten advice: {codes:?}");
    assert!(!codes.contains(&"LUME0427"), "vector advice on flattened path: {codes:?}");
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
    let diagnostic = response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .find(|diagnostic| diagnostic["code"] == "LUMB0805")
        .expect("strict governance must reject the missing typography role binding");
    assert_eq!(diagnostic["severity"], "error");
    assert_eq!(diagnostic["phase"], "brand");
    assert_eq!(
        diagnostic["subject"],
        json!({"kind": "node", "id": "node_contact_name"})
    );
    assert_eq!(
        diagnostic["message"],
        "node node_contact_name text has no Brand Kit typography role binding"
    );
    let hint = diagnostic["hint"].as_str().expect("actionable governance hint");
    assert!(hint.contains("preserves the intended family, weight, size, leading, tracking and color"));
    assert!(hint.contains("a size token alone does not make a whole role equivalent"));
    assert!(hint.contains("Intentional literals may remain under advisory governance"));
    assert!(hint.contains("Under strict governance, use an equivalent existing role"));
    assert!(hint.contains("do not substitute an unrelated role"));
    assert!(!hint.contains("style($type."));
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

// --- W1.2: vectors get a real raster thumbnail ------------------------------
//
// `lumen-assets` derives no thumbnail for a vector ("the sanitized SVG itself
// scales") — true on the canvas, false for every consumer that can only read
// pixels: the agent's `view("asset:<id>")`, the describe stage, the vision
// APIs. The helper is the composition point that has both `lumen-assets` and
// `lumen-skia`, so it is where an SVG earns a PNG thumbnail.

const WORDMARK_SVG: &[u8] = br##"<svg xmlns="http://www.w3.org/2000/svg" width="240" height="48" viewBox="0 0 240 48"><rect x="0" y="0" width="240" height="48" fill="#ff0000"/></svg>"##;

/// Sanitizes cleanly (quick-xml is event-based and happily passes trailing
/// text through) but is not well-formed XML, so Skia's parser refuses it —
/// the shape that proves the fallback arm.
const UNPARSEABLE_SVG: &[u8] = br##"<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>junk"##;

/// Parses cleanly and paints NOTHING: `skia_safe::svg::Dom` is a minimal
/// renderer, so an SVG whose artwork sits in `<defs>` (like one leaning on an
/// unsupported filter, mask, or embedded `<image href>`) renders a fully
/// transparent surface. Storing that would serve a blank PNG as the asset's
/// look — the shape that proves the second fallback arm.
const BLANK_PAINTING_SVG: &[u8] = br##"<svg xmlns="http://www.w3.org/2000/svg" width="240" height="48" viewBox="0 0 240 48"><defs><rect x="0" y="0" width="240" height="48" fill="#ff0000"/></defs></svg>"##;

fn ingest_svg_request(store_root: &str, asset_id: &str, bytes: &[u8]) -> Value {
    use base64::Engine;
    json!({
        "action": "ingest_asset",
        "store_root": store_root,
        "bytes_base64": base64::engine::general_purpose::STANDARD.encode(bytes),
        "asset_id": asset_id,
        "label": "Acme wordmark",
        "declared_mime_type": "image/svg+xml",
        "filename": "wordmark.svg",
        "kind": "logo",
        "tags": ["logo"]
    })
}

#[test]
fn ingest_asset_gives_a_vector_a_png_thumbnail_it_can_actually_be_looked_at_through() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let ingested = helper(ingest_svg_request(
        &store_root,
        "asset_logo_svg",
        WORDMARK_SVG,
    ));
    assert_eq!(ingested["ok"], true, "{ingested:#?}");

    let record = &ingested["asset"]["record"];
    assert_eq!(record["media"]["mime_type"], "image/svg+xml");
    let thumbnail = &record["media"]["thumbnail"];
    assert_eq!(thumbnail["mime_type"], "image/png");
    // The lumen-assets thumbnail policy, applied to the vector's own units:
    // 240x48 fits the 256 box, so the short side is lifted to the 512 floor.
    assert_eq!(thumbnail["pixel_width"], 2560);
    assert_eq!(thumbnail["pixel_height"], 512);

    // The thumbnail is its OWN stored object — never the SVG bytes again.
    let thumb_ref = thumbnail["location"]["opaque_ref"]
        .as_str()
        .expect("thumbnail ref");
    assert_ne!(
        thumb_ref,
        ingested["asset"]["relative_path"].as_str().unwrap(),
        "a self-referential SVG 'thumbnail' is what W1.2 replaces"
    );
    let thumb_bytes = std::fs::read(store_dir.path().join(thumb_ref)).expect("stored thumbnail");
    assert_eq!(&thumb_bytes[..8], b"\x89PNG\r\n\x1a\n", "PNG magic");

    // Sanitizer output is untouched: the PRIMARY media is still the sanitized
    // SVG, byte-identical to what ingest produced before this slice.
    let primary = std::fs::read(
        store_dir
            .path()
            .join(ingested["asset"]["relative_path"].as_str().unwrap()),
    )
    .expect("stored svg");
    assert_eq!(primary, WORDMARK_SVG, "sanitized SVG bytes unchanged");

    // Ingest stayed silent: no new diagnostic rides on the happy path.
    assert!(
        ingested["diagnostics"]
            .as_array()
            .map(|entries| entries.is_empty())
            .unwrap_or(true),
        "{ingested:#?}"
    );
}

#[test]
fn ingest_asset_falls_back_to_the_self_referential_thumbnail_when_a_vector_cannot_rasterize() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let ingested = helper(ingest_svg_request(
        &store_root,
        "asset_logo_broken",
        UNPARSEABLE_SVG,
    ));

    assert_legacy_self_referential_thumbnail(&ingested);
}

#[test]
fn ingest_asset_falls_back_to_the_self_referential_thumbnail_when_a_vector_paints_nothing() {
    // Parsing is not painting. Skia's SVG renderer accepts far more than it
    // draws, and a transparent surface encodes into a perfectly valid PNG —
    // which would then be served as the asset's LOOK. The honest outcome is
    // the legacy arm, which the Python resolver degrades to "no raster
    // preview" (W1.1) instead of showing the trio a blank rectangle.
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let ingested = helper(ingest_svg_request(
        &store_root,
        "asset_logo_blank",
        BLANK_PAINTING_SVG,
    ));

    assert_eq!(ingested["ok"], true, "{ingested:#?}");
    assert_legacy_self_referential_thumbnail(&ingested);

    // Nothing but the sanitized SVG itself was written: no blank PNG lingers
    // in the store.
    let stored: Vec<_> = walk_store(store_dir.path());
    assert_eq!(stored.len(), 1, "only the SVG bytes: {stored:#?}");
}

#[test]
fn ingest_asset_falls_back_to_the_self_referential_thumbnail_when_the_png_cannot_be_stored() {
    // Thumbnail derivation may never fail an ingest — that contract covers the
    // STORE too, not only the rasterizer. The store is content-addressed, so
    // the failure is induced by parking a directory where the thumbnail's own
    // digest path must go: `put` writes a temp file and renames it into place,
    // and renaming a file onto a directory fails.
    let first_dir = tempfile::tempdir().expect("tempdir");
    let first = helper(ingest_svg_request(
        &first_dir.path().to_string_lossy(),
        "asset_logo_svg",
        WORDMARK_SVG,
    ));
    let thumb_ref = first["asset"]["record"]["media"]["thumbnail"]["location"]["opaque_ref"]
        .as_str()
        .expect("thumbnail ref")
        .to_owned();

    let store_dir = tempfile::tempdir().expect("tempdir");
    std::fs::create_dir_all(store_dir.path().join(&thumb_ref)).expect("block the digest path");

    let ingested = helper(ingest_svg_request(
        &store_dir.path().to_string_lossy(),
        "asset_logo_svg",
        WORDMARK_SVG,
    ));

    assert_eq!(
        ingested["ok"], true,
        "a store failure on the THUMBNAIL must not fail the ingest: {ingested:#?}"
    );
    assert_legacy_self_referential_thumbnail(&ingested);
}

/// The pre-W1.2 arm: the vector is its own thumbnail, dimensionless, silent.
fn assert_legacy_self_referential_thumbnail(ingested: &Value) {
    let thumbnail = &ingested["asset"]["record"]["media"]["thumbnail"];
    assert_eq!(thumbnail["mime_type"], "image/svg+xml");
    assert_eq!(thumbnail["pixel_width"], Value::Null);
    assert_eq!(thumbnail["pixel_height"], Value::Null);
    assert_eq!(
        thumbnail["location"]["opaque_ref"], ingested["asset"]["relative_path"],
        "the legacy arm points the thumbnail back at the SVG itself"
    );
    assert!(
        ingested["diagnostics"]
            .as_array()
            .map(|entries| entries.is_empty())
            .unwrap_or(true),
        "the fallback stays silent — this slice adds no diagnostic: {ingested:#?}"
    );
}

#[test]
fn the_vector_and_raster_thumbnail_size_policies_agree() {
    // The size policy is written TWICE — `lumen_assets::derive_raster_thumbnail`
    // for pixels, `lumen_skia::rasterize_svg_thumbnail` for vectors (lumen-skia
    // may not depend on lumen-assets, so it mirrors the rules rather than
    // calling them). Nothing but this test stops the two from drifting, and
    // drift is exactly what would make one logo delivered as SVG and the same
    // logo delivered as PNG arrive at different sizes. This crate is the only
    // one that can see both.
    //
    // The raster of a given source size is synthesized through the vector
    // rasterizer itself under IDENTITY bounds (a max nothing reaches, a floor
    // of zero), which is the one call shape that paints at exactly the source
    // dimensions — so no fixture files and no extra image dependency are
    // needed to obtain "a raster of those dims".
    const IDENTITY_MAX: u32 = 100_000;
    const IDENTITY_FLOOR: u32 = 0;

    let fixture = |width: u32, height: u32| {
        format!(
            r##"<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect x="0" y="0" width="{width}" height="{height}" fill="#336699"/></svg>"##
        )
        .into_bytes()
    };

    let cases: &[(u32, u32, u32, u32)] = &[
        // (max, min_short, source width, source height) — production bounds…
        (256, 512, 1000, 500), // large: fits into the max box
        (256, 512, 300, 300),  // large and square
        (256, 512, 1000, 1),   // a 1px sliver never rounds to zero
        (256, 512, 240, 48),   // small: short side lifted to the vision floor
        (256, 512, 8, 8),      // the tiny-icon case the floor exists for
        // …and bounds where the "already over the floor" branch is reachable
        // at all (with 256/512 it cannot be: a small source is ≤256 < 512).
        (256, 64, 200, 100), // small, short side already over the floor
        (256, 64, 128, 64),  // small, short side exactly AT the floor
    ];

    for &(max_dimension, min_short_dimension, width, height) in cases {
        let case = format!("{width}x{height} under {max_dimension}/{min_short_dimension}");

        let (raster_png, raster_width, raster_height) = lumen_skia::rasterize_svg_thumbnail(
            &fixture(width, height),
            IDENTITY_MAX,
            IDENTITY_FLOOR,
        )
        .unwrap_or_else(|| panic!("identity raster for {case}"));
        assert_eq!(
            (raster_width, raster_height),
            (width, height),
            "the identity call must paint at the source size ({case})"
        );

        let from_raster =
            lumen_assets::derive_raster_thumbnail(&raster_png, max_dimension, min_short_dimension)
                .unwrap_or_else(|| panic!("raster thumbnail for {case}"));
        let (_png, vector_width, vector_height) = lumen_skia::rasterize_svg_thumbnail(
            &fixture(width, height),
            max_dimension,
            min_short_dimension,
        )
        .unwrap_or_else(|| panic!("vector thumbnail for {case}"));

        assert_eq!(
            (vector_width, vector_height),
            (from_raster.pixel_width, from_raster.pixel_height),
            "vector and raster thumbnail policies disagree for {case}"
        );
    }
}

/// Every stored object under a content-addressed store root.
fn walk_store(root: &std::path::Path) -> Vec<std::path::PathBuf> {
    let mut found = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("read dir").flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else {
                found.push(path);
            }
        }
    }
    found
}

#[test]
fn ingest_asset_leaves_the_raster_thumbnail_untouched() {
    // The no-regression guard for W1.2: a PNG ingest's derived thumbnail is
    // byte-identical to the `lumen-assets` derivation, which this slice does
    // not touch. The 8x8 fixture upscales to the 512 vision floor.
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let ingested = helper(ingest_request(&store_root));
    assert_eq!(ingested["ok"], true, "{ingested:#?}");

    let thumbnail = &ingested["asset"]["record"]["media"]["thumbnail"];
    assert_eq!(thumbnail["mime_type"], "image/png");
    assert_eq!(thumbnail["pixel_width"], 512);
    assert_eq!(thumbnail["pixel_height"], 512);

    let expected = lumen_assets::derive_raster_thumbnail(
        LOGO_PNG_BYTES,
        lumen_assets::THUMBNAIL_MAX_DIMENSION,
        lumen_assets::THUMBNAIL_MIN_SHORT_DIMENSION,
    )
    .expect("the fixture derives a thumbnail");
    let stored = std::fs::read(
        store_dir
            .path()
            .join(thumbnail["location"]["opaque_ref"].as_str().unwrap()),
    )
    .expect("stored thumbnail");
    assert_eq!(stored, expected.bytes, "raster thumbnail bytes are stable");

    // Comparing the ingest against the function that produced it pins the
    // WIRING, not the bytes: both sides would move together if the raster
    // thumbnail policy or the PNG encoder ever changed. This digest pins the
    // bytes themselves — the exact thumbnail derived from LOGO_PNG_BYTES under
    // the production bounds, captured from the verified-good W1.2 output. If
    // it fails, a raster thumbnail changed: prove the change is intended, then
    // regenerate by printing `lumen_assets::sha256_hex(&stored)`.
    const RASTER_THUMBNAIL_SHA256: &str =
        "5a6db811ca1b526aeb5367bfd5cc91d45891b29e80b2fe657d0817717a2d702d";
    assert_eq!(
        lumen_assets::sha256_hex(&stored),
        RASTER_THUMBNAIL_SHA256,
        "the derived raster thumbnail is no longer byte-identical"
    );
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

#[test]
fn derive_instance_bulk_export_stores_artifacts_per_the_b3_verdict() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = derive_request(&store_root);
    request["export_formats"] = json!(["svg", "png", "pdf"]);
    request["export_dpi"] = json!(300);

    let first = helper(request.clone());
    assert_eq!(first["ok"], true, "{first:#?}");
    assert_eq!(first["instance"]["export_skipped"], false);
    let artifacts = first["instance"]["artifacts"]
        .as_array()
        .expect("artifacts");
    assert_eq!(artifacts.len(), 3, "{artifacts:#?}");

    for artifact in artifacts {
        assert!(
            artifact.get("error").is_none(),
            "no artifact may fail: {artifact:#?}"
        );
        assert!(
            artifact["digest_value"].as_str().is_some(),
            "content-addressed storage: {artifact:#?}"
        );
        let relative = artifact["relative_path"].as_str().expect("relative path");
        assert!(
            store_dir.path().join(relative).exists(),
            "artifact bytes must exist in the store: {relative}"
        );
    }

    // Bulk PDF = the SAME vector print-intent deliverable interactive
    // downloads produce (adapter pipeline: live text, embedded fonts, X-4,
    // print-ready report). The W0-era "B3" raster-flattened default is
    // superseded; flattened remains only as the LUMEN_PDF_RENDERER
    // comparison baseline.
    let pdf = artifacts
        .iter()
        .find(|artifact| artifact["format"] == "pdf")
        .expect("pdf artifact");
    assert_eq!(pdf["profile_name"], "instance_pdf", "{pdf:#?}");
    assert!(pdf["page_id"].is_null(), "one document artifact: {pdf:#?}");
    let report = &pdf["print_ready"];
    assert!(
        report["rules"].is_array(),
        "print-intent bulk PDF carries the print-ready report: {pdf:#?}"
    );
    assert_ne!(report["status"], "fail", "{report:#?}");
    let pdf_path = store_dir
        .path()
        .join(pdf["relative_path"].as_str().unwrap());
    let pdf_bytes = std::fs::read(&pdf_path).expect("pdf bytes");
    assert!(pdf_bytes.starts_with(b"%PDF-"), "stored bytes are a PDF");
    // Vector path with live text: subset fonts are embedded (FontFile2)
    // and the print finalize declared a TrimBox — neither existed in the
    // raster-flattened output.
    let haystack = String::from_utf8_lossy(&pdf_bytes);
    assert!(
        haystack.contains("FontFile2"),
        "embedded subset fonts expected in the vector bulk PDF"
    );
    assert!(haystack.contains("/TrimBox"), "print finalize expected");

    // Determinism: re-deriving and re-exporting produces identical digests
    // for every artifact (the store reports dedup hits).
    let second = helper(request);
    let second_artifacts = second["instance"]["artifacts"].as_array().unwrap();
    for (a, b) in artifacts.iter().zip(second_artifacts) {
        assert_eq!(a["format"], b["format"]);
        assert_eq!(
            a["digest_value"], b["digest_value"],
            "artifact digests must be idempotent: {} vs {}",
            a["digest_value"], b["digest_value"]
        );
        assert_eq!(b["deduplicated"], true, "{b:#?}");
    }
}

/// Read a PDF box from the first page (values in pt).
fn pdf_page_box(bytes: &[u8], key: &str) -> (f64, f64, f64, f64) {
    let document = lopdf::Document::load_mem(bytes).expect("artifact parses as PDF");
    let (_, page_id) = document.get_pages().into_iter().next().expect("a page");
    let page = document.get_dictionary(page_id).expect("page dict");
    let values: Vec<f64> = page
        .get(key.as_bytes())
        .unwrap_or_else(|_| panic!("page carries {key}"))
        .as_array()
        .expect("box array")
        .iter()
        .map(|value| value.as_float().expect("box number") as f64)
        .collect();
    (values[0], values[1], values[2], values[3])
}

#[test]
fn derive_instance_print_profile_drives_the_full_print_pipeline() {
    // The whole point of the bulk print slice: a saved/inline print profile
    // (bleed + marks) produces the SAME press-ready deliverable through the
    // same adapter pipeline as an interactive download — grown MediaBox for
    // the mark margin, BleedBox inside it, TrimBox at the finished size.
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = derive_request(&store_root);
    // export_formats requests a pdf too: the custom profile must OWN the
    // pdf artifact (exactly one, not a default duplicate).
    request["export_formats"] = json!(["pdf"]);
    request["export_profile"] = json!({
        "name": "print_run",
        "format": "pdf",
        "pdf_intent": "print",
        "raster": null,
        "include_bleed": true,
        "include_marks": true,
        "embed_fonts": true
    });

    let response = helper(request);
    assert_eq!(response["ok"], true, "{response:#?}");
    let artifacts = response["instance"]["artifacts"].as_array().unwrap();
    let pdfs: Vec<&Value> = artifacts
        .iter()
        .filter(|artifact| artifact["format"] == "pdf")
        .collect();
    assert_eq!(pdfs.len(), 1, "custom profile owns the pdf: {artifacts:#?}");
    let pdf = pdfs[0];
    assert_eq!(pdf["profile_name"], "print_run", "{pdf:#?}");
    assert!(pdf.get("error").is_none(), "{pdf:#?}");
    assert_ne!(pdf["print_ready"]["status"], "fail", "{pdf:#?}");

    let bytes = std::fs::read(
        store_dir
            .path()
            .join(pdf["relative_path"].as_str().unwrap()),
    )
    .expect("pdf bytes");

    // DL mailer: trim 210x105mm = 595.28x297.64pt, bleed 3mm, marks
    // margin 14pt. MediaBox = bleed + 2*14pt; boxes strictly nested.
    let media = pdf_page_box(&bytes, "MediaBox");
    let bleed = pdf_page_box(&bytes, "BleedBox");
    let trim = pdf_page_box(&bytes, "TrimBox");
    let width = |b: (f64, f64, f64, f64)| b.2 - b.0;
    let height = |b: (f64, f64, f64, f64)| b.3 - b.1;
    assert!((width(trim) - 595.28).abs() < 0.1, "trim width {trim:?}");
    assert!((height(trim) - 297.64).abs() < 0.1, "trim height {trim:?}");
    let mm3 = 3.0 * 72.0 / 25.4;
    assert!(
        (width(bleed) - (width(trim) + 2.0 * mm3)).abs() < 0.1,
        "bleed box = trim + 3mm each side: {bleed:?}"
    );
    assert!(
        (width(media) - (width(bleed) + 28.0)).abs() < 0.1,
        "media box = bleed + 14pt mark margin each side: {media:?}"
    );
    assert!(
        (height(media) - (height(bleed) + 28.0)).abs() < 0.1,
        "media box = bleed + 14pt mark margin each side: {media:?}"
    );
}

#[test]
fn derive_instance_print_profile_gate_blocks_unready_templates() {
    // include_bleed requested against a bleed-less template: bleed_present
    // FAILs and the bulk gate must block the artifact — one bad template
    // fails loudly instead of printing a 400-copy run with no cutting
    // tolerance.
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = derive_request(&store_root);
    request["scene"]["pages"]["page_mailer"]["bleed"] = Value::Null;
    request["export_profile"] = json!({
        "name": "print_run",
        "format": "pdf",
        "pdf_intent": "print",
        "raster": null,
        "include_bleed": true,
        "include_marks": true,
        "embed_fonts": true
    });

    let response = helper(request);
    assert_eq!(response["ok"], true, "{response:#?}");
    let artifacts = response["instance"]["artifacts"].as_array().unwrap();
    let pdf = artifacts
        .iter()
        .find(|artifact| artifact["format"] == "pdf")
        .expect("pdf row");
    assert_eq!(pdf["error"]["code"], "export.print_not_ready", "{pdf:#?}");
    assert_eq!(pdf["print_ready"]["status"], "fail", "{pdf:#?}");
    assert!(
        pdf.get("relative_path").is_none(),
        "gated artifacts must not be stored: {pdf:#?}"
    );
}

#[test]
fn derive_instance_png_profile_controls_resolution() {
    // "Various PNG export resolutions" for bulk: a custom png profile's
    // raster scale/dpi drives the artifact pixels. DL mailer at 150dpi
    // scale 2 => 210mm = 8.2677in * 150 * 2 = 2480px wide, 1240px tall.
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = derive_request(&store_root);
    request["export_profile"] = json!({
        "name": "instance_png_2x",
        "format": "png",
        "pdf_intent": null,
        "raster": { "scale": 2.0, "dpi": 150 },
        "include_bleed": false,
        "embed_fonts": false
    });

    let response = helper(request);
    assert_eq!(response["ok"], true, "{response:#?}");
    let artifacts = response["instance"]["artifacts"].as_array().unwrap();
    let png = artifacts
        .iter()
        .find(|artifact| artifact["format"] == "png")
        .expect("png row");
    assert_eq!(png["profile_name"], "instance_png_2x");
    let bytes = std::fs::read(
        store_dir
            .path()
            .join(png["relative_path"].as_str().unwrap()),
    )
    .expect("png bytes");
    // IHDR: width/height as big-endian u32 at offsets 16/20.
    let dimension = |offset: usize| {
        u32::from_be_bytes([
            bytes[offset],
            bytes[offset + 1],
            bytes[offset + 2],
            bytes[offset + 3],
        ])
    };
    assert_eq!(dimension(16), 2480, "png width");
    assert_eq!(dimension(20), 1240, "png height");
}

#[test]
fn derive_instance_rejects_malformed_export_profiles() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = derive_request(&store_root);
    request["export_profile"] = json!({ "format": "pdf", "name": 7 });

    let response = helper(request);
    assert_eq!(response["ok"], false, "{response:#?}");
    assert_eq!(response["error"]["code"], "profile.invalid", "{response:#?}");
}

#[test]
fn derive_instance_export_skips_failed_instances() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();

    let mut request = derive_request(&store_root);
    // Worst-case headline cannot fit even at min font => error => no export.
    request["binding_set"] = serde_json::from_str::<Value>(include_str!(
        "../../lumen-core/fixtures/binding/worst_case.json"
    ))
    .unwrap();
    request["asset_records"][0]["id"] = json!("asset_meridian_logo");
    request["export_formats"] = json!(["png"]);

    let response = helper(request);
    assert_eq!(response["ok"], true, "{response:#?}");
    assert_eq!(response["instance"]["has_errors"], true);
    assert_eq!(response["instance"]["export_skipped"], true);
    assert_eq!(
        response["instance"]["artifacts"].as_array().unwrap().len(),
        0,
        "failed instances never produce artifacts"
    );
}

// --- Font library (Track B) -------------------------------------------------
//
// The library rides the same {store_root, faces:[{digest, family}]} spec as
// brand fonts but loads LAZILY: a face's bytes are read only when its declared
// family appears in the request's scene/kit JSON. These tests pin both halves
// of that contract end-to-end through the binary: a referenced family shapes
// without the LUMS0100 fallback, and an unreferenced face is never touched
// (observable because a bogus digest only raises LUMS0101 once referenced).

const LIBRARY_FONT_BYTES: &[u8] = include_bytes!("../../../fonts/Inter-SemiBold.ttf");
const BOGUS_DIGEST: &str = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef";

fn ingest_library_font(store_root: &str) -> String {
    use base64::Engine as _;
    let response = helper(json!({
        "action": "ingest_asset",
        "store_root": store_root,
        "bytes_base64": base64::engine::general_purpose::STANDARD.encode(LIBRARY_FONT_BYTES),
        "asset_id": "asset_font_lib_test_w600",
        "label": "Test Grotesk SemiBold (font library)"
    }));
    assert_eq!(response["ok"], true, "{response:#?}");
    response["asset"]["digest_value"]
        .as_str()
        .expect("ingest returns the digest")
        .to_owned()
}

fn scene_with_family(family: &str) -> Value {
    let mut scene = minimal_scene();
    scene["nodes"]["node_contact_name"]["kind"]["font_family"] = json!(family);
    scene
}

fn diagnostic_codes(response: &Value) -> Vec<String> {
    response["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .map(|diagnostic| diagnostic["code"].as_str().unwrap_or_default().to_owned())
        .collect()
}

#[test]
fn preflight_loads_scene_referenced_library_faces_cleanly() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();
    let digest = ingest_library_font(&store_root);

    // NOTE: preflight cannot prove family RESOLUTION — the measurer seam
    // drops FamilyResolution::diagnostic() today (the loud-text-measurer
    // slice owns that). This pins what preflight can show: the referenced
    // face's bytes load without LUMS0101. Resolution is proven by the PNG
    // export test below, whose rasterizer does surface LUMS0100.
    let with_library = helper(json!({
        "action": "preflight_scene",
        "scene": scene_with_family("Test Grotesk"),
        "brand_kit": Value::Null,
        "library_fonts": {
            "store_root": store_root,
            "faces": [{ "digest": digest, "family": "Test Grotesk" }]
        }
    }));
    assert_eq!(with_library["ok"], true);
    assert!(
        !diagnostic_codes(&with_library).contains(&"LUMS0101".to_owned()),
        "library face bytes must load cleanly at preflight: {with_library:#?}"
    );
}

#[test]
fn library_faces_load_only_when_the_scene_references_their_family() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();
    let digest = ingest_library_font(&store_root);
    let library_fonts = json!({
        "store_root": store_root,
        "faces": [
            { "digest": digest, "family": "Test Grotesk" },
            { "digest": BOGUS_DIGEST, "family": "Unused Family" }
        ]
    });

    // The bogus face's family is not referenced: its digest must never be
    // read, so no LUMS0101 — the lazy filter is what this pins.
    let unreferenced = helper(json!({
        "action": "preflight_scene",
        "scene": scene_with_family("Test Grotesk"),
        "brand_kit": Value::Null,
        "library_fonts": library_fonts
    }));
    assert_eq!(unreferenced["ok"], true);
    assert!(
        !diagnostic_codes(&unreferenced).contains(&"LUMS0101".to_owned()),
        "unreferenced library face must not be loaded: {unreferenced:#?}"
    );

    // Once the scene references the family, the missing bytes surface loudly.
    let referenced = helper(json!({
        "action": "preflight_scene",
        "scene": scene_with_family("Unused Family"),
        "brand_kit": Value::Null,
        "library_fonts": library_fonts
    }));
    assert_eq!(referenced["ok"], true);
    assert!(
        diagnostic_codes(&referenced).contains(&"LUMS0101".to_owned()),
        "referenced-but-unreadable library face must warn: {referenced:#?}"
    );
}

#[test]
fn png_export_rasterizes_library_family_without_silent_fallback() {
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();
    let digest = ingest_library_font(&store_root);

    // Control: without the library the family is unknown and the rasterizer
    // reports the LUMS0100 fallback. The declared family deliberately
    // differs from the bytes' intrinsic name ("Inter") — the K3 alias
    // contract must hold for library faces too.
    let without_library = helper(json!({
        "action": "export_preview",
        "scene": scene_with_family("Test Grotesk"),
        "format": "png",
        "page_ids": ["page_a4"]
    }));
    assert_eq!(without_library["ok"], true, "{without_library:#?}");
    assert!(
        diagnostic_codes(&without_library).contains(&"LUMS0100".to_owned()),
        "unknown family must fall back loudly in raster export: {without_library:#?}"
    );

    let with_library = helper(json!({
        "action": "export_preview",
        "scene": scene_with_family("Test Grotesk"),
        "format": "png",
        "page_ids": ["page_a4"],
        "library_fonts": {
            "store_root": store_root,
            "faces": [{ "digest": digest, "family": "Test Grotesk" }]
        }
    }));
    assert_eq!(with_library["ok"], true, "{with_library:#?}");
    let codes = diagnostic_codes(&with_library);
    assert!(
        !codes.contains(&"LUMS0100".to_owned()) && !codes.contains(&"LUMS0101".to_owned()),
        "library family must rasterize without fallback: {with_library:#?}"
    );
}

#[test]
fn derive_instance_shapes_and_renders_with_request_fonts() {
    // The bulk/instance path was the one shaping action with NO font
    // fields: every personalized artifact silently rendered in bundled
    // Inter regardless of the template's typography. This pins the seam
    // end-to-end: derive + PNG artifact render must consume the request's
    // font spec exactly like preflight/export_preview do.
    let store_dir = tempfile::tempdir().expect("tempdir");
    let store_root = store_dir.path().to_string_lossy().to_string();
    let digest = ingest_library_font(&store_root);

    let mut scene = mailer_revision();
    scene["nodes"]["node_headline"]["kind"]["font_family"] = json!("Test Grotesk");

    // Control: without a font spec the artifact render falls back loudly.
    let mut request = derive_request(&store_root);
    request["scene"] = scene.clone();
    request["export_formats"] = json!(["png"]);
    let without_fonts = helper(request.clone());
    assert_eq!(without_fonts["ok"], true, "{without_fonts:#?}");
    assert!(
        diagnostic_codes(&without_fonts).contains(&"LUMS0100".to_owned()),
        "unknown family must fall back loudly in the instance artifact render: {without_fonts:#?}"
    );

    // With the library spec the same derivation renders the real face.
    request["library_fonts"] = json!({
        "store_root": store_root,
        "faces": [{ "digest": digest, "family": "Test Grotesk" }]
    });
    let with_fonts = helper(request);
    assert_eq!(with_fonts["ok"], true, "{with_fonts:#?}");
    let codes = diagnostic_codes(&with_fonts);
    assert!(
        !codes.contains(&"LUMS0100".to_owned()) && !codes.contains(&"LUMS0101".to_owned()),
        "instance artifacts must shape and render with the request fonts: {with_fonts:#?}"
    );
    assert!(
        with_fonts["instance"]["artifacts"]
            .as_array()
            .is_some_and(|artifacts| !artifacts.is_empty()),
        "the run must actually produce artifacts: {with_fonts:#?}"
    );
}

// --- Web derivation (Phase 5 personalization) -------------------------------

/// Build a real web document (through the ingest action) carrying inline
/// `data-var`, node `data-slot`, and a `data-slot-when` presence gate.
fn web_template_with_markers() -> Value {
    let base = helper(json!({
        "action": "web_new_doc",
        "document_id": "tmpl_1",
        "title": "Template",
    }));
    assert_eq!(base["ok"], true, "{base:#?}");
    let ingested = helper(json!({
        "action": "web_ingest_html",
        "doc": base["web_doc"].clone(),
        "page_id": "home",
        "html": r#"<section id="hero" data-slot-when="account.name">
                     <h1 id="head">Meet <span data-var="account.name">Acme Health</span></h1>
                     <p id="tag" data-slot="account.tagline">A better way to work</p>
                   </section>"#,
    }));
    assert_eq!(ingested["ok"], true, "{ingested:#?}");
    ingested["web_doc"].clone()
}

#[test]
fn web_derive_substitutes_reports_coverage_and_is_deterministic() {
    let doc = web_template_with_markers();
    let request = json!({
        "action": "web_derive",
        "doc": doc,
        "values": {
            "account.name": { "kind": "text", "value": "Privia Health" },
            "account.tagline": { "kind": "text", "value": "AI scribing that clinicians trust" },
            "account.unused": { "kind": "text", "value": "referenced nowhere" }
        },
        "new_doc_id": "derived_privia",
        "new_title": "Privia Health"
    });

    let first = helper(request.clone());
    assert_eq!(first["ok"], true, "{first:#?}");
    assert_eq!(first["web_doc"]["id"], "derived_privia");
    assert_eq!(first["web_doc"]["title"], "Privia Health");

    // The account name (inline var) and tagline (node slot) are substituted;
    // the template fallbacks are gone.
    let serialized = first["web_doc"].to_string();
    assert!(serialized.contains("Privia Health"), "{serialized}");
    assert!(serialized.contains("AI scribing that clinicians trust"), "{serialized}");
    assert!(!serialized.contains("Acme Health"), "fallback should be gone: {serialized}");

    // Coverage names applied keys and flags the unused value.
    let bound: Vec<&str> = first["coverage"]["bound"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|value| value.as_str())
        .collect();
    assert!(bound.contains(&"account.name"), "{bound:?}");
    assert!(bound.contains(&"account.tagline"), "{bound:?}");
    let unused: Vec<&str> = first["coverage"]["unused_values"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|value| value.as_str())
        .collect();
    assert!(unused.contains(&"account.unused"), "{unused:?}");

    // Determinism: identical inputs → byte-identical derived doc.
    let second = helper(request);
    assert_eq!(first["web_doc"], second["web_doc"], "derive must be deterministic");
}

#[test]
fn web_derive_rejects_atomically_on_missing_asset() {
    // Seed a logo asset, then ingest an image carrying a data-slot marker.
    let base = helper(json!({
        "action": "web_new_doc",
        "document_id": "tmpl_logo",
        "title": "Template",
    }));
    let mut doc = base["web_doc"].clone();
    doc["assets"]["asset_acme_logo"] = binding_logo_record();
    let ingested = helper(json!({
        "action": "web_ingest_html",
        "doc": doc,
        "page_id": "home",
        "html": r#"<section id="s"><img id="logo" data-slot="account.logo" data-asset="asset_acme_logo" alt="logo"></section>"#,
    }));
    assert_eq!(ingested["ok"], true, "{ingested:#?}");

    // Bind account.logo to an asset whose record is NOT supplied → LUMW0605.
    let response = helper(json!({
        "action": "web_derive",
        "doc": ingested["web_doc"].clone(),
        "values": {
            "account.logo": { "kind": "asset", "asset_id": "ghost_asset" }
        },
        "assets": [],
        "new_doc_id": "derived_x"
    }));
    assert_eq!(response["ok"], false, "{response:#?}");
    assert_eq!(response["error"]["code"], "web_derive.rejected");
    // The rejected derive returns no doc but still reports coverage.
    assert!(response["web_doc"].is_null(), "{response:#?}");
    assert!(response["coverage"].is_object(), "{response:#?}");
    let codes: Vec<String> = diagnostic_codes(&response);
    assert!(codes.contains(&"LUMW0605".to_owned()), "{codes:?}");
}

// --- Brand-geometry advice on a briefed kit (LUMW0306) -----------------------
//
// The one bit ingest needs about the Creative Brief is lifted off the RAW kit
// JSON in the helper (serde drops `brief` on the way into `BrandKit`). These
// prove the wire: the same markup and the same kit differ only by that key.

const RAW_GEOMETRY_SECTION: &str = r#"<section id="cards">
    <div id="card_a" class="rounded-2xl shadow-lg p-6"><p id="a">First.</p></div>
    <div id="card_b" class="rounded-2xl shadow-lg p-6"><p id="b">Second.</p></div>
  </section>"#;

fn briefed_brand_kit() -> Value {
    let mut kit = platform_brand_kit();
    kit["brief"] = json!({
        "schema_version": 1,
        "characterization": { "words": ["measured", "calm"] },
    });
    kit
}

fn geometry_advice(response: &Value) -> Vec<String> {
    response["diagnostics"]
        .as_array()
        .expect("diagnostics array")
        .iter()
        .filter(|diagnostic| diagnostic["code"] == "LUMW0306")
        .map(|diagnostic| {
            assert_eq!(diagnostic["severity"], "advice", "{diagnostic:#?}");
            diagnostic["message"].as_str().unwrap_or_default().to_owned()
        })
        .collect()
}

fn web_doc_with_raw_geometry(brand_kit: Value) -> Value {
    let base = helper(json!({
        "action": "web_new_doc",
        "document_id": "geo_doc",
        "title": "Geometry",
    }));
    let ingested = helper(json!({
        "action": "web_ingest_html",
        "doc": base["web_doc"].clone(),
        "page_id": "home",
        "html": RAW_GEOMETRY_SECTION,
        "brand_kit": brand_kit,
    }));
    assert_eq!(ingested["ok"], true, "{ingested:#?}");
    ingested
}

#[test]
fn briefed_ingest_advises_raw_geometry_once_and_still_installs() {
    let response = web_doc_with_raw_geometry(briefed_brand_kit());
    let advice = geometry_advice(&response);
    assert_eq!(
        advice.len(),
        2,
        "one line per raw class across both cards: {advice:?}"
    );
    assert!(advice.iter().any(|line| line.contains("`rounded-2xl`")), "{advice:?}");
    assert!(advice.iter().any(|line| line.contains("`shadow-lg`")), "{advice:?}");
    // Advice can never reject: the nodes are installed.
    assert!(
        response["applied_operations"].as_u64().unwrap_or_default() > 0,
        "{response:#?}"
    );
    let serialized = response["web_doc"].to_string();
    assert!(serialized.contains("card_a") && serialized.contains("card_b"), "{serialized}");
}

#[test]
fn an_unbriefed_kit_ingests_the_same_markup_silently() {
    let response = web_doc_with_raw_geometry(platform_brand_kit());
    assert!(geometry_advice(&response).is_empty(), "{response:#?}");
}

#[test]
fn web_validate_advises_raw_geometry_on_a_briefed_kit() {
    let doc = web_doc_with_raw_geometry(platform_brand_kit())["web_doc"].clone();

    let briefed = helper(json!({
        "action": "web_validate",
        "doc": doc.clone(),
        "brand_kit": briefed_brand_kit(),
    }));
    assert_eq!(briefed["ok"], true, "{briefed:#?}");
    let advice = geometry_advice(&briefed);
    assert_eq!(advice.len(), 2, "deduped across the whole doc walk: {advice:?}");

    let unbriefed = helper(json!({
        "action": "web_validate",
        "doc": doc,
        "brand_kit": platform_brand_kit(),
    }));
    assert!(geometry_advice(&unbriefed).is_empty(), "{unbriefed:#?}");
}
