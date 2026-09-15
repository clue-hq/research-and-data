use lumen_core::{platform_default_brand_kit, preflight_scene, PreflightOptions, Scene};
use lumen_wasm::Engine;
use serde_json::{json, Value};

fn scene() -> Value {
    let mut scene: Value =
        serde_json::from_str(include_str!("../../lumen-core/fixtures/minimal_scene.json")).unwrap();
    scene["slots"] = json!({});
    scene["export_profiles"] = json!([]);
    scene["meta"]["medium"] = json!("digital");
    let mut frame = scene["nodes"]["node_contact_name"].clone();
    frame["id"] = json!("frame");
    frame["kind"] = json!({"kind":"auto_layout", "direction":"column", "wrap":false});
    frame["transform"]["x"] = json!(0);
    frame["transform"]["y"] = json!(0);
    frame["size"] =
        json!({"width":{"kind":"fixed","value":500},"height":{"kind":"fixed","value":500}});
    frame["children"] = json!(["node_contact_name"]);
    frame["layout"] = json!({"padding":[72,72,72,72],"padding_token":"space.8","gap":72,"gap_token":"space.8","grow":0});
    scene["nodes"]["frame"] = frame;
    scene["pages"]["page_a4"]["children"] = json!(["frame"]);
    scene
}

#[test]
fn native_token_padding_matches_canonical_geometry_without_baking_authoring() {
    let source = scene();
    let kit = platform_default_brand_kit().unwrap();
    let canonical = preflight_scene(
        serde_json::from_str::<Scene>(&source.to_string()).unwrap(),
        Some(&kit),
        PreflightOptions::default(),
    );
    assert!(
        canonical.layout_result.is_some(),
        "{:?}",
        canonical.diagnostics
    );
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    engine.set_render_context(
        &json!({"context_key":"test", "document_id": source["meta"]["id"],
        "scene_brand_ref": null, "scene_medium":"digital", "brand_kit":kit,"mode":null})
        .to_string(),
    );
    let native: Value = serde_json::from_str(&engine.scene_json()).unwrap();
    assert_eq!(
        native["nodes"]["node_contact_name"]["computed"]["layout_bounds"]["x"],
        json!(32.0)
    );
    let exported = parse(serde_json::to_string(&canonical.scene).unwrap());
    assert_eq!(
        native["nodes"]["node_contact_name"]["computed"],
        exported["nodes"]["node_contact_name"]["computed"]
    );
    assert_eq!(
        native["nodes"]["frame"]["layout"]["padding"],
        json!([72.0, 72.0, 72.0, 72.0])
    );
}

fn context(source: &Value) -> Value {
    json!({"context_key":"test", "document_id":source["meta"]["id"],
        "scene_brand_ref":source["meta"]["brand_kit"], "scene_medium":source["meta"]["medium"],
        "brand_kit":platform_default_brand_kit().unwrap(), "mode":null})
}
fn parse(text: String) -> Value {
    serde_json::from_str(&text).unwrap()
}
fn inset(engine: &Engine) -> Value {
    parse(engine.scene_json())["nodes"]["node_contact_name"]["computed"]["layout_bounds"]["x"]
        .clone()
}

#[test]
fn aliases_declared_modes_and_mode_only_switch_use_canonical_inputs() {
    let mut source = scene();
    source["nodes"]["frame"]["layout"]["padding_token"] = json!("space.alias");
    let mut ctx = context(&source);
    ctx["brand_kit"]["tokens"]["aliases"]["space.alias"] = json!({"token":"space.8"});
    ctx["mode"] = json!({"values":{"density":"compact"}});
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    engine.set_render_context(&ctx.to_string());
    assert_eq!(parse(engine.presentation_json())["status"], "ready");
    assert_eq!(inset(&engine), 28.0);
    ctx["context_key"] = json!("mode-change");
    ctx["mode"] = json!({"values":{"density":"comfortable"}});
    engine.set_render_context(&ctx.to_string());
    assert_eq!(inset(&engine), 32.0);
    let presentation = parse(engine.presentation_json());
    assert!(presentation["scene"]["nodes"]["frame"]["layout"]
        .get("padding_token")
        .is_none());
    let geometry = parse(engine.layout_geometry());
    assert_eq!(
        geometry["geometry"]["node_contact_name"],
        presentation["scene"]["nodes"]["node_contact_name"]["computed"]
    );
    assert_eq!(
        parse(engine.hit_test("page_a4", 35.0, 35.0))["hit"],
        "node_contact_name"
    );
}

#[test]
fn missing_unknown_mismatched_and_unsupported_contexts_never_claim_ready() {
    let source = scene();
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    assert_eq!(inset(&engine), 72.0); // preserved legacy no-context call
    for mutation in ["missing", "unknown", "mismatch", "mode", "axis"] {
        let mut ctx = context(&source);
        match mutation {
            "missing" => ctx["brand_kit"] = Value::Null,
            "unknown" => ctx["brand_kit"]["tokens"]["spacing"]
                .as_object_mut()
                .unwrap()
                .remove("space.8")
                .map(|_| ())
                .unwrap(),
            "mismatch" => ctx["scene_brand_ref"] = json!({"id":"other", "version":1}),
            "mode" => ctx["mode"] = json!({"values":{"density":"not-declared"}}),
            _ => ctx["mode"] = json!({"values":{"unknown":"value"}}),
        }
        engine.set_render_context(&ctx.to_string());
        let state = parse(engine.presentation_json());
        assert_ne!(state["status"], "ready", "{mutation}: {state}");
        assert!(!state["diagnostics"].as_array().unwrap().is_empty());
        assert_eq!(inset(&engine), 72.0);
    }
    engine.set_render_context(&context(&source).to_string());
    assert_eq!(inset(&engine), 32.0);
    engine.set_render_context("{malformed");
    assert_eq!(parse(engine.presentation_json())["status"], "invalid");
    assert_eq!(inset(&engine), 72.0);
    engine.set_render_context("null");
    assert_eq!(parse(engine.presentation_json())["status"], "pending");
}

#[test]
fn authored_operations_inverse_reload_and_paired_deltas_preserve_bindings() {
    use lumen_core::{NodePatch, Operation, OptionalFieldPatch};
    let source = scene();
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    engine.set_render_context(&context(&source).to_string());
    let original: Scene = serde_json::from_str(&engine.scene_json()).unwrap();
    let mut layout = original.nodes[&"frame".into()].layout.clone().unwrap();
    layout.padding = [40.0, 32.0, 32.0, 32.0];
    layout.padding_token = None;
    let op = Operation::UpdateNode {
        node_id: "frame".into(),
        patch: NodePatch {
            layout: OptionalFieldPatch::Set(layout),
            ..NodePatch::default()
        },
    };
    let result = parse(engine.apply_operations(&serde_json::to_string(&vec![op]).unwrap()));
    assert_eq!(result["ok"], true);
    assert_eq!(
        result["presentation_delta"]["nodes"]["frame"]["layout"]["padding"],
        json!([40.0, 32.0, 32.0, 32.0])
    );
    assert_eq!(
        result["delta"]["nodes"]["frame"]["layout"]["gap_token"],
        "space.8"
    );
    let undo = parse(engine.apply_operations(&result["inverse_operations"].to_string()));
    assert_eq!(undo["ok"], true);
    assert_eq!(inset(&engine), 32.0);
    assert_eq!(
        parse(engine.scene_json())["nodes"]["frame"]["layout"]["padding"],
        json!([72.0, 72.0, 72.0, 72.0])
    );
    engine.load_scene(&source.to_string()).unwrap();
    assert_eq!(inset(&engine), 32.0);
    let mut switched = source.clone();
    switched["meta"]["brand_kit"] = json!({"id":"new", "version":2});
    engine.load_scene(&switched.to_string()).unwrap();
    assert_eq!(parse(engine.presentation_json())["status"], "pending");
    let mut next = context(&switched);
    next["brand_kit"]["id"] = json!("new");
    next["brand_kit"]["version"] = json!(2);
    engine.set_render_context(&next.to_string());
    assert_eq!(parse(engine.presentation_json())["status"], "ready");
}

#[test]
fn unbound_literals_stay_72_and_extra_declared_axis_uses_legitimate_default() {
    let mut source = scene();
    source["nodes"]["frame"]["layout"]
        .as_object_mut()
        .unwrap()
        .remove("padding_token");
    let mut ctx = context(&source);
    ctx["brand_kit"]["modes"]["axes"]["campaign"] = json!(["one", "two"]);
    ctx["brand_kit"]["modes"]["defaults"]["campaign"] = json!("one");
    ctx["mode"] = json!({"values":{"campaign":"two"}});
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    engine.set_render_context(&ctx.to_string());
    assert_eq!(parse(engine.presentation_json())["status"], "ready");
    assert_eq!(inset(&engine), 72.0);
}

#[test]
fn measurement_keys_use_resolved_text_and_context_replacement_clears_metrics() {
    let mut source = scene();
    source["nodes"]["node_contact_name"]["size"]["height"] = json!({"kind":"hug"});
    source["nodes"]["node_contact_name"]["kind"]["font_size_token"] = json!("type.size.xl");
    let mut ctx = context(&source);
    // Exact kit number, independent of the role catalog's values.
    ctx["brand_kit"]["tokens"]["numbers"]["type.size.xl"] = json!({"value":{"default":{"kind":"number","value":36,"unit":"px"},"modes":{}},"role":"type"});
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    engine.set_render_context(&ctx.to_string());
    assert_eq!(parse(engine.presentation_json())["status"], "ready");
    let mut metric =
        parse(engine.presentation_json())["scene"]["nodes"]["node_contact_name"]["kind"].clone();
    metric["max_width"] = json!(160);
    metric["width"] = json!(100);
    metric["height"] = json!(99);
    let input_revision = parse(engine.presentation_json())["input_revision"].clone();
    let measurements = json!([metric]).to_string();
    let ack = parse(engine.set_measurements(&measurements));
    assert_eq!(
        parse(engine.presentation_json())["input_revision"],
        input_revision,
        "measurement relayout must not change the authored/context revision"
    );
    assert_eq!(ack["ok"], true);
    assert_eq!(
        parse(engine.scene_json())["nodes"]["node_contact_name"]["computed"]["layout_bounds"]
            ["height"],
        99.0
    );
    assert_eq!(
        parse(engine.scene_json())["nodes"]["node_contact_name"]["kind"]["font_size"],
        18.0
    );
    engine.set_render_context(&ctx.to_string());
    assert_ne!(
        parse(engine.scene_json())["nodes"]["node_contact_name"]["computed"]["layout_bounds"]
            ["height"],
        99.0
    );
    engine.set_measurements(&measurements);
    assert_eq!(
        parse(engine.scene_json())["nodes"]["node_contact_name"]["computed"]["layout_bounds"]
            ["height"],
        99.0
    );
    engine.load_scene(&source.to_string()).unwrap();
    assert_eq!(parse(engine.presentation_json())["status"], "ready");
    assert_ne!(
        parse(engine.scene_json())["nodes"]["node_contact_name"]["computed"]["layout_bounds"]
            ["height"],
        99.0,
        "canonical-context reset must still invalidate prior measurements"
    );
}

#[test]
fn dsl_and_structured_edits_rederive_and_scene_medium_matches_canonical_preflight() {
    let mut source = scene();
    source["meta"]["medium"] = json!("direct_mail");
    let mut ctx = context(&source);
    ctx["brand_kit"]["tokens"]["spacing"]["space.8"]["value"]["modes"]["medium.print"] =
        json!({"kind":"number","value":44,"unit":"px"});
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    engine.set_render_context(&ctx.to_string());
    assert_eq!(inset(&engine), 44.0);
    let result =
        parse(engine.compile_dsl_block("#node_contact_name text(\"Context survives DSL\")"));
    assert_eq!(result["ok"], true);
    assert_eq!(result["derivation"]["status"], "ready");
    assert_eq!(inset(&engine), 44.0);
    let result = parse(engine.apply_structured_edit(
        &json!({"kind":"delete","target":{"kind":"node","id":"node_contact_name"}}).to_string(),
    ));
    assert_eq!(result["ok"], true, "{result}");
    assert_eq!(
        result["presentation_delta"]["nodes"]["node_contact_name"],
        Value::Null
    );
    assert_eq!(result["derivation"]["status"], "ready");
    let result = parse(engine.apply_operations(&result["edit"]["inverse_operations"].to_string()));
    assert_eq!(result["ok"], true);
    assert_eq!(inset(&engine), 44.0);
}

#[test]
fn implicit_medium_on_legacy_kits_matches_canonical_export_without_rebinding() {
    for medium in ["digital", "ad", "email", "web", "print", "direct_mail"] {
        for explicit_mode in [false, true] {
            let mut source = scene();
            source["meta"]["medium"] = json!(medium);
            let mut ctx = context(&source);
            // Persisted kits may declare only theme/density/accessibility.
            // Export still supplies its normalized scene-medium selector.
            ctx["brand_kit"]["modes"]["axes"]
                .as_object_mut()
                .unwrap()
                .remove("medium");
            ctx["brand_kit"]["modes"]["defaults"]
                .as_object_mut()
                .unwrap()
                .remove("medium");
            let mut options = PreflightOptions::default();
            if explicit_mode {
                let normalized = if ["print", "direct_mail"].contains(&medium) {
                    "print"
                } else {
                    "digital"
                };
                ctx["mode"] = json!({"values":{"medium":normalized}});
                options.token_resolution.mode =
                    serde_json::from_value(ctx["mode"].clone()).unwrap();
            }
            let kit = serde_json::from_value(ctx["brand_kit"].clone()).unwrap();
            let canonical = preflight_scene(
                serde_json::from_str::<Scene>(&source.to_string()).unwrap(),
                Some(&kit),
                options,
            );
            assert!(
                canonical.layout_result.is_some(),
                "{medium}: {:?}",
                canonical.diagnostics
            );
            let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
            engine.set_render_context(&ctx.to_string());
            let presentation = parse(engine.presentation_json());
            assert_eq!(
                presentation["status"], "ready",
                "{medium} explicit={explicit_mode}: {}",
                presentation["diagnostics"]
            );
            let exported = parse(serde_json::to_string(&canonical.scene).unwrap());
            assert_eq!(
                presentation["scene"]["nodes"]["node_contact_name"]["computed"],
                exported["nodes"]["node_contact_name"]["computed"]
            );
            assert_eq!(
                parse(engine.scene_json())["nodes"]["frame"]["layout"]["padding"],
                json!([72.0, 72.0, 72.0, 72.0])
            );
            assert!(ctx["brand_kit"]["modes"]["axes"].get("medium").is_none());
        }
    }
}

#[test]
fn implicit_medium_support_does_not_allow_invalid_or_declared_unsupported_modes() {
    let source = scene();
    let mut ctx = context(&source);
    ctx["brand_kit"]["modes"]["axes"]
        .as_object_mut()
        .unwrap()
        .remove("medium");
    ctx["brand_kit"]["modes"]["defaults"]
        .as_object_mut()
        .unwrap()
        .remove("medium");
    let mut engine = Engine::from_scene_json(&source.to_string()).unwrap();
    for mode in [
        json!({"medium":"holographic"}),
        json!({"theme":"undeclared"}),
        json!({"unknown":"digital"}),
    ] {
        ctx["mode"] = json!({"values":mode});
        engine.set_render_context(&ctx.to_string());
        let state = parse(engine.presentation_json());
        assert_eq!(state["status"], "invalid");
        assert!(state["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|d| d["code"] == "EDITOR_RENDER_MODE_UNSUPPORTED"));
    }
    ctx["brand_kit"]["modes"]["axes"]["medium"] = json!(["print"]);
    ctx["brand_kit"]["modes"]["defaults"]["medium"] = json!("print");
    ctx["mode"] = json!({"values":{"medium":"digital"}});
    engine.set_render_context(&ctx.to_string());
    assert_eq!(parse(engine.presentation_json())["status"], "invalid");
}
