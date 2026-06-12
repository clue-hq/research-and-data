use lumen_core::validation::validate_scene;
use lumen_core::{
    build_clone_subtree, build_modify_operations, build_move_after, build_move_before,
    build_move_to_parent, build_replace_node, build_safe_delete, compare_brand_kit_compatibility,
    compile_dsl_into_scene_with_session, compile_styles_brand_kit, generate_brand_kit,
    layout_scene, platform_default_brand_kit, preflight_scene, summarize_brand_kit_for_authoring,
    validate_brand_kit, validate_brand_kit_product_ready, validate_scene_brand_governance,
    BrandGovernanceStrictness, BrandKit, BrandKitId, BrandMode, BrandSeed, CloneSubtreeRequest,
    Diagnostic, DiagnosticSeverity, DocumentId, DslCompileSessionSnapshot, EditBatch, EditPatch,
    EditTargetRef, ExportAdapter, ExportFormat, ExportProfile, ExportPurpose, ExportRequest,
    Medium, NodeId, Operation, PageId, ParentRef, PdfIntent, PreflightOptions, RasterScale,
    ReplaceNodeRequest, Scene, TemplateRevisionId,
};
use lumen_export::LumenExportAdapter;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::io::{self, Read};
use std::time::Instant;

#[derive(Debug, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
enum CoreRequest {
    NewScene {
        document_id: String,
        title: String,
        artifact_type: Option<String>,
        medium: Option<Value>,
    },
    ValidateScene {
        scene: Value,
    },
    ApplyOperations {
        scene: Value,
        operations: Vec<Value>,
    },
    ApplyStructuredEdit {
        scene: Value,
        edit: StructuredEditInstruction,
    },
    CompileDslIntoScene {
        scene: Value,
        source: String,
        #[serde(default)]
        dsl_session: Option<Value>,
    },
    PreflightScene {
        scene: Value,
        brand_kit: Option<Value>,
        #[serde(default)]
        mode: Option<Value>,
    },
    ExportPreview {
        scene: Value,
        format: ExportFormat,
        page_ids: Vec<String>,
        #[serde(default)]
        profile: Option<Value>,
    },
    FinalizeTemplate {
        scene: Value,
        template_revision_id: String,
    },
    PlatformDefaultBrandKit,
    ValidateBrandKit {
        brand_kit: Value,
        #[serde(default)]
        product_ready: bool,
    },
    CompileStylesBrandKit {
        source: String,
        brand_kit_id: String,
        version: u32,
        name: String,
    },
    GenerateBrandKit {
        seed: Value,
    },
    SummarizeBrandKit {
        brand_kit: Value,
    },
    ValidateSceneBrandGovernance {
        scene: Value,
        brand_kit: Value,
        strictness: BrandGovernanceStrictness,
    },
    CompareBrandKitCompatibility {
        from: Value,
        to: Value,
    },
    LayoutGeometry {
        scene: Value,
    },
}

#[derive(Debug, Serialize)]
struct CoreResponse {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    scene: Option<Value>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    diagnostics: Vec<Diagnostic>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<CoreError>,
    #[serde(skip_serializing_if = "Option::is_none")]
    applied_operations: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    preflight: Option<PreflightSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_kit: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_summary: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_generation: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    brand_compatibility: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    geometry: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    operations: Option<Vec<Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    edit: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    dsl: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    export: Option<Value>,
}

#[derive(Debug, Serialize)]
struct CoreError {
    code: String,
    message: String,
}

#[derive(Debug, Serialize)]
struct PreflightSummary {
    has_errors: bool,
    brand_ref_operations: Vec<Value>,
    token_operations: Vec<Value>,
    layout_operations: Vec<Value>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
enum StructuredEditInstruction {
    Modify {
        target: EditTargetRef,
        patch: EditPatch,
    },
    Delete {
        target: EditTargetRef,
    },
    MoveBefore {
        node_id: NodeId,
        anchor: NodeId,
    },
    MoveAfter {
        node_id: NodeId,
        anchor: NodeId,
    },
    MoveToParent {
        node_id: NodeId,
        parent: ParentRef,
        index: usize,
    },
    CloneSubtree {
        request: CloneSubtreeRequest,
    },
    ReplaceNode {
        request: ReplaceNodeRequest,
    },
}

fn main() {
    let start = Instant::now();
    let response = match read_request() {
        Ok(request) => {
            let action = request.action_name();
            helper_log(
                "core_helper_started",
                "info",
                Some(action),
                request_log_fields(&request),
            );
            let response = match handle_request(request) {
                Ok(response) => response,
                Err(error) => CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: Vec::new(),
                    error: Some(error),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                },
            };
            helper_log(
                "core_helper_completed",
                if response.ok { "info" } else { "warning" },
                Some(action),
                response_log_fields(&response, start),
            );
            response
        }
        Err(error) => {
            helper_log(
                "core_helper_completed",
                "error",
                None,
                json!({
                    "ok": false,
                    "duration_ms": elapsed_ms(start),
                    "diagnostic_count": 0,
                    "error_code": error.code.as_str(),
                }),
            );
            CoreResponse {
                ok: false,
                scene: None,
                diagnostics: Vec::new(),
                error: Some(error),
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            }
        }
    };

    println!(
        "{}",
        serde_json::to_string(&response).expect("helper response should serialize")
    );
}

impl CoreRequest {
    fn action_name(&self) -> &'static str {
        match self {
            CoreRequest::NewScene { .. } => "new_scene",
            CoreRequest::ValidateScene { .. } => "validate_scene",
            CoreRequest::ApplyOperations { .. } => "apply_operations",
            CoreRequest::ApplyStructuredEdit { .. } => "apply_structured_edit",
            CoreRequest::CompileDslIntoScene { .. } => "compile_dsl_into_scene",
            CoreRequest::PreflightScene { .. } => "preflight_scene",
            CoreRequest::ExportPreview { .. } => "export_preview",
            CoreRequest::FinalizeTemplate { .. } => "finalize_template",
            CoreRequest::PlatformDefaultBrandKit => "platform_default_brand_kit",
            CoreRequest::ValidateBrandKit { .. } => "validate_brand_kit",
            CoreRequest::CompileStylesBrandKit { .. } => "compile_styles_brand_kit",
            CoreRequest::GenerateBrandKit { .. } => "generate_brand_kit",
            CoreRequest::SummarizeBrandKit { .. } => "summarize_brand_kit",
            CoreRequest::ValidateSceneBrandGovernance { .. } => "validate_scene_brand_governance",
            CoreRequest::CompareBrandKitCompatibility { .. } => "compare_brand_kit_compatibility",
            CoreRequest::LayoutGeometry { .. } => "layout_geometry",
        }
    }
}

fn request_log_fields(request: &CoreRequest) -> Value {
    match request {
        CoreRequest::NewScene {
            artifact_type,
            medium,
            ..
        } => json!({
            "has_artifact_type": artifact_type.is_some(),
            "has_medium": medium.is_some(),
        }),
        CoreRequest::ValidateScene { .. } => json!({}),
        CoreRequest::ApplyOperations { operations, .. } => json!({
            "operation_count": operations.len(),
        }),
        CoreRequest::ApplyStructuredEdit { edit, .. } => json!({
            "edit_kind": structured_edit_kind(edit),
        }),
        CoreRequest::CompileDslIntoScene {
            source,
            dsl_session,
            ..
        } => json!({
            "source_line_count": source.lines().count(),
            "has_dsl_session": dsl_session.is_some(),
        }),
        CoreRequest::PreflightScene {
            brand_kit, mode, ..
        } => json!({
            "has_brand_kit": brand_kit.is_some(),
            "has_mode": mode.is_some(),
        }),
        CoreRequest::ExportPreview {
            format,
            page_ids,
            profile,
            ..
        } => json!({
            "format": format,
            "page_id_count": page_ids.len(),
            "has_profile": profile.is_some(),
        }),
        CoreRequest::FinalizeTemplate { .. } => json!({}),
        CoreRequest::PlatformDefaultBrandKit => json!({}),
        CoreRequest::ValidateBrandKit { product_ready, .. } => json!({
            "product_ready": product_ready,
        }),
        CoreRequest::CompileStylesBrandKit {
            source,
            brand_kit_id,
            version,
            ..
        } => json!({
            "source_line_count": source.lines().count(),
            "brand_kit_id": brand_kit_id,
            "version": version,
        }),
        CoreRequest::GenerateBrandKit { .. } => json!({}),
        CoreRequest::SummarizeBrandKit { .. } => json!({}),
        CoreRequest::ValidateSceneBrandGovernance { strictness, .. } => json!({
            "strictness": strictness,
        }),
        CoreRequest::CompareBrandKitCompatibility { .. } => json!({}),
        CoreRequest::LayoutGeometry { .. } => json!({}),
    }
}

fn response_log_fields(response: &CoreResponse, start: Instant) -> Value {
    json!({
        "ok": response.ok,
        "duration_ms": elapsed_ms(start),
        "diagnostic_count": response.diagnostics.len(),
        "has_error_diagnostics": has_error(&response.diagnostics),
        "applied_operations": response.applied_operations,
        "has_scene": response.scene.is_some(),
        "has_geometry": response.geometry.is_some(),
        "artifact_count": export_artifact_count(response.export.as_ref()),
        "error_code": response.error.as_ref().map(|error| error.code.as_str()),
    })
}

fn export_artifact_count(export: Option<&Value>) -> usize {
    export
        .and_then(|export| export.get("artifacts"))
        .and_then(Value::as_array)
        .map_or(0, Vec::len)
}

fn elapsed_ms(start: Instant) -> f64 {
    let elapsed = start.elapsed();
    (elapsed.as_secs_f64() * 1000.0 * 1000.0).round() / 1000.0
}

fn helper_log(event: &str, level: &str, action: Option<&str>, fields: Value) {
    if !helper_logging_enabled() {
        return;
    }
    let mut payload = serde_json::Map::new();
    payload.insert("source".to_owned(), json!("lumen-api-helper"));
    payload.insert("event".to_owned(), json!(event));
    payload.insert("level".to_owned(), json!(level));
    if let Some(action) = action {
        payload.insert("action".to_owned(), json!(action));
    }
    if let Ok(request_id) = env::var("LUMEN_REQUEST_ID") {
        if !request_id.is_empty() {
            payload.insert("request_id".to_owned(), json!(request_id));
        }
    }
    if let Ok(helper_call_id) = env::var("LUMEN_CORE_CALL_ID") {
        if !helper_call_id.is_empty() {
            payload.insert("helper_call_id".to_owned(), json!(helper_call_id));
        }
    }
    if let Some(fields) = fields.as_object() {
        for (key, value) in fields {
            payload.insert(key.clone(), value.clone());
        }
    }
    if let Ok(line) = serde_json::to_string(&Value::Object(payload)) {
        eprintln!("{line}");
    }
}

fn helper_logging_enabled() -> bool {
    env::var("LUMEN_CORE_HELPER_LOG").is_ok_and(|value| value != "0")
}

fn read_request() -> Result<CoreRequest, CoreError> {
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .map_err(|error| core_error("helper.stdin", error.to_string()))?;
    serde_json::from_str(&input).map_err(|error| core_error("helper.request", error.to_string()))
}

fn handle_request(request: CoreRequest) -> Result<CoreResponse, CoreError> {
    match request {
        CoreRequest::NewScene {
            document_id,
            title,
            artifact_type,
            medium,
        } => {
            let mut scene = Scene::new(DocumentId::from(document_id), title);
            scene.meta.artifact_type = artifact_type;
            scene.meta.medium = medium
                .map(serde_json::from_value::<Medium>)
                .transpose()
                .map_err(|error| core_error("helper.medium", error.to_string()))?;
            Ok(ok_scene(scene, Vec::new(), None))
        }
        CoreRequest::ValidateScene { scene } => {
            let scene = parse_scene(scene)?;
            let diagnostics = validate_scene(&scene);
            Ok(ok_scene(scene, diagnostics, None))
        }
        CoreRequest::ApplyOperations { scene, operations } => {
            let mut scene = parse_scene(scene)?;
            let operations = parse_operations(operations)?;
            match scene.apply_operations_checked(operations) {
                Ok(report) => Ok(ok_scene(
                    scene,
                    report.diagnostics,
                    Some(report.applied_operations),
                )),
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: error.diagnostics,
                    error: Some(core_error(error.code, error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                }),
            }
        }
        CoreRequest::ApplyStructuredEdit { scene, edit } => {
            let mut scene = parse_scene(scene)?;
            let batch = structured_edit_batch(&scene, &edit).map_err(|error| CoreResponse {
                ok: false,
                scene: None,
                diagnostics: vec![error.diagnostic()],
                error: Some(core_error(error.kind.code(), error.message)),
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: Some(
                    to_value(&edit)
                        .unwrap_or_else(|_| json!({"kind": structured_edit_kind(&edit)})),
                ),
                dsl: None,
                export: None,
            });
            let batch = match batch {
                Ok(batch) => batch,
                Err(response) => return Ok(response),
            };
            let operations = batch.operations.clone();
            match batch.apply_checked(&mut scene) {
                Ok(report) => Ok(CoreResponse {
                    ok: true,
                    scene: Some(to_value(scene)?),
                    diagnostics: report.diagnostics,
                    error: None,
                    applied_operations: Some(report.applied_operations),
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: Some(values(operations)?),
                    edit: Some(json!({
                        "kind": structured_edit_kind(&edit),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                        "checkpoint_label": batch.checkpoint_label,
                    })),
                    dsl: None,
                    export: None,
                }),
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: vec![error.diagnostic()],
                    error: Some(core_error(error.kind.code(), error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: Some(values(operations)?),
                    edit: Some(json!({
                        "kind": structured_edit_kind(&edit),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                        "checkpoint_label": batch.checkpoint_label,
                    })),
                    dsl: None,
                    export: None,
                }),
            }
        }
        CoreRequest::CompileDslIntoScene {
            scene,
            source,
            dsl_session,
        } => {
            let mut scene = parse_scene(scene)?;
            let session = dsl_session
                .map(serde_json::from_value::<DslCompileSessionSnapshot>)
                .transpose()
                .map_err(|error| core_error("helper.dsl_session", error.to_string()))?;
            let result = compile_dsl_into_scene_with_session(&source, &mut scene, session);
            let applied_operations = result
                .operation_report
                .as_ref()
                .map(|report| report.applied_operations);
            Ok(CoreResponse {
                ok: true,
                scene: Some(to_value(scene)?),
                diagnostics: Vec::new(),
                error: None,
                applied_operations,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: Some(json!({
                    "compile_output": dsl_compile_output_value(&result.compile_output)?,
                    "operation_report": operation_report_value(&result.operation_report),
                    "operation_error": operation_error_value(&result.operation_error),
                    "session_snapshot": to_value(result.session_snapshot)?,
                })),
                export: None,
            })
        }
        CoreRequest::PreflightScene {
            scene,
            brand_kit,
            mode,
        } => {
            let scene = parse_scene(scene)?;
            let brand_kit = brand_kit.map(parse_brand_kit).transpose()?;
            let mut options = PreflightOptions::default();
            if let Some(mode) = mode {
                options.token_resolution.mode = parse_brand_mode(mode)?;
            }
            let result = preflight_scene(scene, brand_kit.as_ref(), options);
            let summary = PreflightSummary {
                has_errors: result.has_errors(),
                brand_ref_operations: values(result.brand_ref_operations)?,
                token_operations: values(result.token_operations)?,
                layout_operations: values(result.layout_operations)?,
            };
            Ok(CoreResponse {
                ok: true,
                scene: Some(to_value(result.scene)?),
                diagnostics: result.diagnostics,
                error: None,
                applied_operations: None,
                preflight: Some(summary),
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
        CoreRequest::ExportPreview {
            scene,
            format,
            page_ids,
            profile,
        } => {
            let scene = parse_scene(scene)?;
            let profile = match profile {
                Some(profile) => {
                    serde_json::from_value::<ExportProfile>(profile).map_err(|error| {
                        core_error(
                            "profile.invalid",
                            format!("invalid export profile payload: {error}"),
                        )
                    })?
                }
                None => ExportProfile {
                    name: "agent_critique_preview".to_owned(),
                    format,
                    pdf_intent: Some(PdfIntent::Preview),
                    raster: Some(RasterScale {
                        scale: 1.0,
                        dpi: Some(96),
                    }),
                    include_bleed: false,
                    embed_fonts: true,
                },
            };
            let request = ExportRequest {
                profile,
                page_ids: page_ids.into_iter().map(PageId::from).collect(),
                purpose: ExportPurpose::AgentCritique,
            };
            match LumenExportAdapter::new().export(&scene, &request) {
                Ok(result) => Ok(CoreResponse {
                    ok: true,
                    scene: None,
                    diagnostics: result.diagnostics.clone(),
                    error: None,
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: Some(to_value(result)?),
                }),
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: error.diagnostics,
                    error: Some(core_error(error.code, error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                }),
            }
        }
        CoreRequest::FinalizeTemplate {
            scene,
            template_revision_id,
        } => {
            let mut scene = parse_scene(scene)?;
            let operation = Operation::FinalizeTemplate {
                template_revision_id: TemplateRevisionId::from(template_revision_id),
            };
            match scene.apply_operation_checked(operation) {
                Ok(report) => Ok(ok_scene(
                    scene,
                    report.diagnostics,
                    Some(report.applied_operations),
                )),
                Err(error) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics: error.diagnostics,
                    error: Some(core_error(error.code, error.message)),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                }),
            }
        }
        CoreRequest::PlatformDefaultBrandKit => {
            let brand_kit = platform_default_brand_kit().map_err(|error| {
                core_error("helper.platform_default_brand_kit", error.to_string())
            })?;
            Ok(CoreResponse {
                ok: true,
                scene: None,
                diagnostics: Vec::new(),
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
        CoreRequest::ValidateBrandKit {
            brand_kit,
            product_ready,
        } => {
            let brand_kit = parse_brand_kit(brand_kit)?;
            let diagnostics = if product_ready {
                validate_brand_kit_product_ready(&brand_kit)
            } else {
                validate_brand_kit(&brand_kit)
            };
            Ok(CoreResponse {
                ok: !has_error(&diagnostics),
                scene: None,
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
        CoreRequest::CompileStylesBrandKit {
            source,
            brand_kit_id,
            version,
            name,
        } => {
            match compile_styles_brand_kit(&source, BrandKitId::from(brand_kit_id), version, name) {
                Ok(brand_kit) => {
                    let summary = summarize_brand_kit_for_authoring(&brand_kit);
                    Ok(CoreResponse {
                        ok: true,
                        scene: None,
                        diagnostics: Vec::new(),
                        error: None,
                        applied_operations: None,
                        preflight: None,
                        brand_kit: Some(to_value(&brand_kit)?),
                        brand_summary: Some(to_value(summary)?),
                        brand_generation: None,
                        brand_compatibility: None,
                        geometry: None,
                        operations: None,
                        edit: None,
                        dsl: None,
                        export: None,
                    })
                }
                Err(diagnostics) => Ok(CoreResponse {
                    ok: false,
                    scene: None,
                    diagnostics,
                    error: Some(core_error(
                        "helper.brand_styles",
                        "styles source did not compile into a product-ready Brand Kit",
                    )),
                    applied_operations: None,
                    preflight: None,
                    brand_kit: None,
                    brand_summary: None,
                    brand_generation: None,
                    brand_compatibility: None,
                    geometry: None,
                    operations: None,
                    edit: None,
                    dsl: None,
                    export: None,
                }),
            }
        }
        CoreRequest::GenerateBrandKit { seed } => {
            let seed = parse_brand_seed(seed)?;
            let report = generate_brand_kit(&seed);
            let diagnostics = report.diagnostics.clone();
            let brand_kit = report.brand_kit.as_ref().map(to_value).transpose()?;
            let brand_summary = report
                .brand_kit
                .as_ref()
                .map(summarize_brand_kit_for_authoring)
                .map(to_value)
                .transpose()?;
            let ok = report.brand_kit.is_some() && !has_error(&diagnostics);
            Ok(CoreResponse {
                ok,
                scene: None,
                diagnostics,
                error: if ok {
                    None
                } else {
                    Some(core_error(
                        "helper.brand_seed",
                        "brand seed did not generate a usable Brand Kit",
                    ))
                },
                applied_operations: None,
                preflight: None,
                brand_kit,
                brand_summary,
                brand_generation: Some(to_value(report)?),
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
        CoreRequest::SummarizeBrandKit { brand_kit } => {
            let brand_kit = parse_brand_kit(brand_kit)?;
            let summary = summarize_brand_kit_for_authoring(&brand_kit);
            Ok(CoreResponse {
                ok: summary.product_ready,
                scene: None,
                diagnostics: summary.diagnostics.clone(),
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: Some(to_value(summary)?),
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
        CoreRequest::ValidateSceneBrandGovernance {
            scene,
            brand_kit,
            strictness,
        } => {
            let scene = parse_scene(scene)?;
            let brand_kit = parse_brand_kit(brand_kit)?;
            let diagnostics = validate_scene_brand_governance(&scene, &brand_kit, strictness);
            Ok(CoreResponse {
                ok: !has_error(&diagnostics),
                scene: Some(to_value(scene)?),
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: Some(to_value(brand_kit)?),
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
        CoreRequest::CompareBrandKitCompatibility { from, to } => {
            let from = parse_brand_kit(from)?;
            let to = parse_brand_kit(to)?;
            let report = compare_brand_kit_compatibility(&from, &to);
            let diagnostics = report.diagnostics.clone();
            Ok(CoreResponse {
                ok: !has_error(&diagnostics),
                scene: None,
                diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: Some(to_value(report)?),
                geometry: None,
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
        CoreRequest::LayoutGeometry { scene } => {
            let scene = parse_scene(scene)?;
            let result = layout_scene(&scene, Default::default());
            Ok(CoreResponse {
                ok: true,
                scene: None,
                diagnostics: result.diagnostics,
                error: None,
                applied_operations: None,
                preflight: None,
                brand_kit: None,
                brand_summary: None,
                brand_generation: None,
                brand_compatibility: None,
                geometry: Some(json!(result.geometry)),
                operations: None,
                edit: None,
                dsl: None,
                export: None,
            })
        }
    }
}

fn ok_scene(
    scene: Scene,
    diagnostics: Vec<Diagnostic>,
    applied_operations: Option<usize>,
) -> CoreResponse {
    CoreResponse {
        ok: true,
        scene: Some(to_value(scene).expect("scene should serialize")),
        diagnostics,
        error: None,
        applied_operations,
        preflight: None,
        brand_kit: None,
        brand_summary: None,
        brand_generation: None,
        brand_compatibility: None,
        geometry: None,
        operations: None,
        edit: None,
        dsl: None,
        export: None,
    }
}

fn parse_scene(value: Value) -> Result<Scene, CoreError> {
    serde_json::from_value(value).map_err(|error| core_error("helper.scene", error.to_string()))
}

fn parse_brand_kit(value: Value) -> Result<BrandKit, CoreError> {
    serde_json::from_value(value).map_err(|error| core_error("helper.brand_kit", error.to_string()))
}

fn parse_brand_mode(value: Value) -> Result<BrandMode, CoreError> {
    serde_json::from_value(value)
        .map_err(|error| core_error("helper.brand_mode", error.to_string()))
}

fn parse_brand_seed(value: Value) -> Result<BrandSeed, CoreError> {
    serde_json::from_value(value)
        .map_err(|error| core_error("helper.brand_seed", error.to_string()))
}

fn parse_operations(values: Vec<Value>) -> Result<Vec<Operation>, CoreError> {
    values
        .into_iter()
        .map(|value| {
            serde_json::from_value(value)
                .map_err(|error| core_error("helper.operation", error.to_string()))
        })
        .collect()
}

fn structured_edit_kind(edit: &StructuredEditInstruction) -> &'static str {
    match edit {
        StructuredEditInstruction::Modify { .. } => "modify",
        StructuredEditInstruction::Delete { .. } => "delete",
        StructuredEditInstruction::MoveBefore { .. } => "move_before",
        StructuredEditInstruction::MoveAfter { .. } => "move_after",
        StructuredEditInstruction::MoveToParent { .. } => "move_to_parent",
        StructuredEditInstruction::CloneSubtree { .. } => "clone_subtree",
        StructuredEditInstruction::ReplaceNode { .. } => "replace_node",
    }
}

fn structured_edit_batch(
    scene: &Scene,
    edit: &StructuredEditInstruction,
) -> Result<EditBatch, lumen_core::EditError> {
    match edit {
        StructuredEditInstruction::Modify { target, patch } => {
            build_modify_operations(scene, target.clone(), patch.clone())
        }
        StructuredEditInstruction::Delete { target } => match target {
            EditTargetRef::Node(node_id) => build_safe_delete(scene, node_id.clone()),
            _ => Err(lumen_core::EditError::new(
                lumen_core::EditErrorKind::UnsupportedTarget,
                "safe delete currently supports node targets only; use canonical remove operations for other target types",
            )
            .with_target(target.clone())),
        },
        StructuredEditInstruction::MoveBefore { node_id, anchor } => {
            build_move_before(scene, node_id.clone(), anchor.clone())
        }
        StructuredEditInstruction::MoveAfter { node_id, anchor } => {
            build_move_after(scene, node_id.clone(), anchor.clone())
        }
        StructuredEditInstruction::MoveToParent {
            node_id,
            parent,
            index,
        } => build_move_to_parent(scene, node_id.clone(), parent.clone(), *index),
        StructuredEditInstruction::CloneSubtree { request } => {
            build_clone_subtree(scene, request.clone())
        }
        StructuredEditInstruction::ReplaceNode { request } => {
            build_replace_node(scene, request.clone())
        }
    }
}

fn values<T: Serialize>(items: Vec<T>) -> Result<Vec<Value>, CoreError> {
    items.into_iter().map(to_value).collect()
}

fn dsl_compile_output_value(output: &lumen_core::DslCompileOutput) -> Result<Value, CoreError> {
    Ok(json!({
        "operations": values(output.operations.clone())?,
        "diagnostics": output
            .diagnostics
            .iter()
            .map(|diagnostic| json!({
                "diagnostic": diagnostic.diagnostic,
                "span": {
                    "line": diagnostic.span.line,
                    "column": diagnostic.span.column,
                    "length": diagnostic.span.length,
                }
            }))
            .collect::<Vec<_>>(),
        "halted_at": output.halted_at.as_ref().map(|halt| json!({
            "line": halt.line,
            "code": halt.code,
        })),
    }))
}

fn operation_report_value(report: &Option<lumen_core::OperationReport>) -> Option<Value> {
    report.as_ref().map(|report| {
        json!({
            "applied_operations": report.applied_operations,
            "diagnostics": report.diagnostics,
        })
    })
}

fn operation_error_value(error: &Option<lumen_core::OperationError>) -> Option<Value> {
    error.as_ref().map(|error| {
        json!({
            "code": error.code,
            "message": error.message,
            "diagnostics": error.diagnostics,
        })
    })
}

fn to_value<T: Serialize>(value: T) -> Result<Value, CoreError> {
    serde_json::to_value(value).map_err(|error| core_error("helper.serialize", error.to_string()))
}

fn has_error(diagnostics: &[Diagnostic]) -> bool {
    diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
}

fn core_error(code: impl Into<String>, message: impl Into<String>) -> CoreError {
    CoreError {
        code: code.into(),
        message: message.into(),
    }
}
