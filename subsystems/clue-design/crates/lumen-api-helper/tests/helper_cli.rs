use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Stdio};

const MINIMAL_SCENE: &str = include_str!("../../lumen-core/fixtures/minimal_scene.json");
const GENERATED_RASTER: &str =
    include_str!("../../lumen-core/fixtures/assets/generated_raster_asset.json");
const VALID_INSIGHT_HEALTH_STYLES: &str =
    include_str!("../../lumen-core/fixtures/styles/valid_insight_health.styles");
const INVALID_DUPLICATE_TOKEN_STYLES: &str =
    include_str!("../../lumen-core/fixtures/styles/invalid_duplicate_token.styles");

fn helper(request: Value) -> Value {
    let mut child = Command::new(env!("CARGO_BIN_EXE_lumen-api-helper"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("helper binary should spawn");

    child
        .stdin
        .as_mut()
        .expect("stdin should be available")
        .write_all(request.to_string().as_bytes())
        .expect("request should write");

    let output = child.wait_with_output().expect("helper should exit");
    assert!(output.status.success(), "{output:?}");
    serde_json::from_slice(&output.stdout).expect("helper response should be JSON")
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
