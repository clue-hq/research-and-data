use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use lumen_assets::{AssetStore, IngestRequest, LocalAssetStore, DEFAULT_MAX_BYTES};
use lumen_core::validation::validate_scene;
use lumen_core::SharedTextMeasurer;
use lumen_core::{
    batch_scope_violations, build_structured_edit_batch, compare_brand_kit_compatibility,
    compile_dsl_into_scene_with_session, compile_styles_brand_kit, generate_brand_kit,
    layout_scene, platform_default_brand_kit, preflight_scene, summarize_brand_kit_for_authoring,
    validate_brand_kit, validate_brand_kit_product_ready, validate_scene_brand_governance,
    AssetDigest, AssetId, AssetKind, AssetLicense, AssetLocation, AssetMediaMetadata,
    AssetProvenance, AssetRecord, AssetSource, AssetStatus, AssetThumbnail,
    BrandGovernanceStrictness, BrandKit, BrandKitId, BrandMode, BrandSeed, Diagnostic,
    DiagnosticSeverity, DocumentId, DslCompileSessionSnapshot, EditScope, EditScopeMode,
    ExportAdapter, ExportFormat, ExportProfile, ExportPurpose, ExportRequest, Medium, Operation,
    PageId, PdfIntent, PreflightOptions, RasterScale, Scene, ScopeViolation,
    StructuredEditInstruction, TemplateRevisionId,
};
use lumen_export::LumenExportAdapter;
use lumen_skia::{FontManager, SkiaSceneRenderer, SkiaTextMeasurer};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::io::{self, Read};
use std::sync::Arc;
use std::time::Instant;

mod store_resolver;

use store_resolver::{StoreBackedResolver, LOCAL_STORE_PROVIDER};

/// The server-side text measurer: SkParagraph shaping over the bundled
/// deterministic font set (Wave 1 Track A, Decision 5). Every helper path
/// that measures text — preflight, layout geometry, export — injects this;
/// the heuristic remains only as the wasm fallback inside lumen-core.
fn server_measurer() -> SharedTextMeasurer {
    Arc::new(SkiaTextMeasurer::bundled())
}

/// Export adapter composition for every server export path (slice A4):
/// Skia text measurement for SVG/PDF line breaks and the direct Skia scene
/// rasterizer for PNG — measurer and renderer share one FontManager, so
/// critic previews and artifacts shape text identically to preflight.
fn server_export_adapter(adapter: LumenExportAdapter) -> LumenExportAdapter {
    let fonts = Arc::new(FontManager::bundled());
    adapter
        .with_measurer(Arc::new(SkiaTextMeasurer::new(Arc::clone(&fonts))))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::new(fonts)))
}

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
        #[serde(default)]
        scope: Option<EditScope>,
    },
    ApplyStructuredEdit {
        scene: Value,
        edit: StructuredEditInstruction,
        #[serde(default)]
        scope: Option<EditScope>,
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
        #[serde(default)]
        asset_store_root: Option<String>,
    },
    IngestAsset {
        store_root: String,
        bytes_base64: String,
        asset_id: String,
        label: String,
        #[serde(default)]
        declared_mime_type: Option<String>,
        #[serde(default)]
        filename: Option<String>,
        #[serde(default)]
        kind: Option<Value>,
        #[serde(default)]
        uploaded_by: Option<String>,
        #[serde(default)]
        license: Option<Value>,
        #[serde(default)]
        provenance: Option<Value>,
        #[serde(default)]
        source: Option<Value>,
        #[serde(default)]
        tags: Option<Vec<String>>,
        #[serde(default)]
        max_bytes: Option<u64>,
    },
    GenerateQr {
        store_root: String,
        data: String,
        asset_id: String,
        #[serde(default)]
        label: Option<String>,
        #[serde(default)]
        ec_level: Option<String>,
        #[serde(default)]
        print: bool,
        #[serde(default)]
        target_width_mm: Option<f64>,
    },
    GenerateAsset {
        store_root: String,
        provider: String,
        request: Value,
        asset_id: String,
        #[serde(default)]
        label: Option<String>,
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
    BuildInfo,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    asset: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    build_info: Option<Value>,
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
                    asset: None,
                    build_info: None,
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
                asset: None,
                build_info: None,
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
            CoreRequest::IngestAsset { .. } => "ingest_asset",
            CoreRequest::GenerateQr { .. } => "generate_qr",
            CoreRequest::GenerateAsset { .. } => "generate_asset",
            CoreRequest::FinalizeTemplate { .. } => "finalize_template",
            CoreRequest::PlatformDefaultBrandKit => "platform_default_brand_kit",
            CoreRequest::ValidateBrandKit { .. } => "validate_brand_kit",
            CoreRequest::CompileStylesBrandKit { .. } => "compile_styles_brand_kit",
            CoreRequest::GenerateBrandKit { .. } => "generate_brand_kit",
            CoreRequest::SummarizeBrandKit { .. } => "summarize_brand_kit",
            CoreRequest::ValidateSceneBrandGovernance { .. } => "validate_scene_brand_governance",
            CoreRequest::CompareBrandKitCompatibility { .. } => "compare_brand_kit_compatibility",
            CoreRequest::LayoutGeometry { .. } => "layout_geometry",
            CoreRequest::BuildInfo => "build_info",
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
            "edit_kind": edit.kind(),
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
            asset_store_root,
            ..
        } => json!({
            "format": format,
            "page_id_count": page_ids.len(),
            "has_profile": profile.is_some(),
            "has_asset_store_root": asset_store_root.is_some(),
        }),
        CoreRequest::IngestAsset {
            bytes_base64,
            declared_mime_type,
            kind,
            ..
        } => json!({
            "base64_length": bytes_base64.len(),
            "declared_mime_type": declared_mime_type,
            "has_kind": kind.is_some(),
        }),
        CoreRequest::GenerateQr {
            data,
            ec_level,
            print,
            target_width_mm,
            ..
        } => json!({
            "data_length": data.len(),
            "ec_level": ec_level,
            "print": print,
            "has_target_width_mm": target_width_mm.is_some(),
        }),
        CoreRequest::GenerateAsset { provider, .. } => json!({
            "provider": provider,
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
        CoreRequest::BuildInfo => json!({}),
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

fn error_response(error: CoreError, diagnostics: Vec<Diagnostic>) -> CoreResponse {
    CoreResponse {
        ok: false,
        scene: None,
        diagnostics,
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
        asset: None,
        build_info: None,
    }
}

/// Enforce a declared edit scope before mutation. Strict violations and
/// unresolvable declared targets fail closed with an error response; in
/// advisory mode violations become warning diagnostics that ride along with
/// the applied batch.
fn check_scope(
    scene: &Scene,
    operations: &[Operation],
    scope: Option<&EditScope>,
) -> Result<Vec<Diagnostic>, Box<CoreResponse>> {
    let Some(scope) = scope else {
        return Ok(Vec::new());
    };
    let violations = match batch_scope_violations(scene, operations, &scope.allowed) {
        Ok(violations) => violations,
        Err(error) => {
            return Err(Box::new(error_response(
                core_error(error.kind.code(), error.message.clone()),
                vec![error.diagnostic()],
            )));
        }
    };
    if violations.is_empty() {
        return Ok(Vec::new());
    }
    match scope.mode {
        EditScopeMode::Strict => Err(Box::new(error_response(
            core_error(
                "edit.scope_violation",
                format!(
                    "{} operation(s) touch targets outside the declared scope",
                    violations.len()
                ),
            ),
            violations.iter().map(ScopeViolation::diagnostic).collect(),
        ))),
        EditScopeMode::Advisory => Ok(violations
            .iter()
            .map(ScopeViolation::advisory_diagnostic)
            .collect()),
    }
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
        CoreRequest::ApplyOperations {
            scene,
            operations,
            scope,
        } => {
            let mut scene = parse_scene(scene)?;
            let operations = parse_operations(operations)?;
            let scope_diagnostics = match check_scope(&scene, &operations, scope.as_ref()) {
                Ok(diagnostics) => diagnostics,
                Err(response) => return Ok(*response),
            };
            let inverse_operations = scene
                .invert_operations(&operations)
                .ok()
                .flatten()
                .map(values)
                .transpose()?;
            match scene.apply_operations_checked(operations) {
                Ok(report) => {
                    let mut response =
                        ok_scene(scene, report.diagnostics, Some(report.applied_operations));
                    response.diagnostics.extend(scope_diagnostics);
                    response.edit = Some(json!({
                        "kind": "apply_operations",
                        "inverse_operations": inverse_operations,
                    }));
                    Ok(response)
                }
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
                    asset: None,
                    build_info: None,
                }),
            }
        }
        CoreRequest::ApplyStructuredEdit { scene, edit, scope } => {
            let mut scene = parse_scene(scene)?;
            let batch = build_structured_edit_batch(&scene, &edit).map_err(|error| CoreResponse {
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
                edit: Some(to_value(&edit).unwrap_or_else(|_| json!({"kind": edit.kind()}))),
                dsl: None,
                export: None,
                asset: None,
                build_info: None,
            });
            let batch = match batch {
                Ok(batch) => batch,
                Err(response) => return Ok(response),
            };
            let operations = batch.operations.clone();
            let scope_diagnostics = match check_scope(&scene, &operations, scope.as_ref()) {
                Ok(diagnostics) => diagnostics,
                Err(mut response) => {
                    response.edit = Some(json!({
                        "kind": edit.kind(),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                    }));
                    return Ok(*response);
                }
            };
            match batch.apply_checked(&mut scene) {
                Ok(report) => Ok(CoreResponse {
                    ok: true,
                    scene: Some(to_value(scene)?),
                    diagnostics: {
                        let mut diagnostics = report.diagnostics;
                        diagnostics.extend(scope_diagnostics);
                        diagnostics
                    },
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
                        "kind": edit.kind(),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                        "checkpoint_label": batch.checkpoint_label,
                        "inverse_operations": batch.inverse_operations,
                        "lineage": batch.lineage,
                    })),
                    dsl: None,
                    export: None,
                    asset: None,
                    build_info: None,
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
                        "kind": edit.kind(),
                        "touched_targets": batch.touched_targets,
                        "intent": batch.intent,
                        "checkpoint_label": batch.checkpoint_label,
                        "inverse_operations": batch.inverse_operations,
                        "lineage": batch.lineage,
                    })),
                    dsl: None,
                    export: None,
                    asset: None,
                    build_info: None,
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
                asset: None,
                build_info: None,
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
            options.layout.measurer = Some(server_measurer());
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
                asset: None,
                build_info: None,
            })
        }
        CoreRequest::ExportPreview {
            scene,
            format,
            page_ids,
            profile,
            asset_store_root,
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
            let adapter = server_export_adapter(match asset_store_root {
                Some(root) => {
                    LumenExportAdapter::with_resolver(Arc::new(StoreBackedResolver::new(root)))
                }
                None => LumenExportAdapter::new(),
            });
            match adapter.export(&scene, &request) {
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
                    asset: None,
                    build_info: None,
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
                    asset: None,
                    build_info: None,
                }),
            }
        }
        CoreRequest::IngestAsset {
            store_root,
            bytes_base64,
            asset_id,
            label,
            declared_mime_type,
            filename,
            kind,
            uploaded_by,
            license,
            provenance,
            source,
            tags,
            max_bytes,
        } => {
            let bytes = BASE64
                .decode(bytes_base64.as_bytes())
                .map_err(|error| core_error("helper.asset_bytes", error.to_string()))?;
            let kind_hint = kind
                .map(serde_json::from_value::<AssetKind>)
                .transpose()
                .map_err(|error| core_error("helper.asset_kind", error.to_string()))?;
            let license = license
                .map(serde_json::from_value::<AssetLicense>)
                .transpose()
                .map_err(|error| core_error("helper.asset_license", error.to_string()))?;
            let provenance = provenance
                .map(serde_json::from_value::<AssetProvenance>)
                .transpose()
                .map_err(|error| core_error("helper.asset_provenance", error.to_string()))?;
            let source = source
                .map(serde_json::from_value::<AssetSource>)
                .transpose()
                .map_err(|error| core_error("helper.asset_source", error.to_string()))?;

            let ingest_request = IngestRequest {
                bytes: &bytes,
                declared_mime: declared_mime_type.as_deref(),
                filename: filename.as_deref(),
                kind_hint,
                max_bytes: max_bytes.unwrap_or(DEFAULT_MAX_BYTES),
            };
            let output = match lumen_assets::ingest(&ingest_request) {
                Ok(output) => output,
                Err(error) => {
                    return Ok(error_response(
                        core_error(error.code, error.message.clone()),
                        vec![error.diagnostic],
                    ))
                }
            };

            let store = LocalAssetStore::new(&store_root);
            let stored = store
                .put(&output.bytes)
                .map_err(|error| core_error(error.code, error.message))?;

            let thumbnail = match &output.thumbnail {
                Some(artifact) => {
                    let stored_thumbnail = store
                        .put(&artifact.bytes)
                        .map_err(|error| core_error(error.code, error.message))?;
                    Some(AssetThumbnail {
                        location: AssetLocation {
                            provider: LOCAL_STORE_PROVIDER.to_owned(),
                            opaque_ref: stored_thumbnail.relative_path,
                            url: None,
                        },
                        mime_type: artifact.mime_type.clone(),
                        pixel_width: Some(artifact.pixel_width),
                        pixel_height: Some(artifact.pixel_height),
                    })
                }
                // Vector assets are their own thumbnail: the sanitized SVG
                // scales without derivation.
                None if output.sniffed_mime == "image/svg+xml" => Some(AssetThumbnail {
                    location: AssetLocation {
                        provider: LOCAL_STORE_PROVIDER.to_owned(),
                        opaque_ref: stored.relative_path.clone(),
                        url: None,
                    },
                    mime_type: output.sniffed_mime.clone(),
                    pixel_width: None,
                    pixel_height: None,
                }),
                None => None,
            };

            let record = AssetRecord {
                id: AssetId::from(asset_id),
                label,
                kind: output.kind.clone(),
                status: AssetStatus::Ready,
                source: source.unwrap_or(AssetSource::Uploaded {
                    asset_id: None,
                    filename: filename.clone(),
                    uploaded_by,
                }),
                media: AssetMediaMetadata {
                    mime_type: Some(output.sniffed_mime.clone()),
                    filename,
                    byte_length: Some(stored.byte_length),
                    digest: Some(AssetDigest {
                        algorithm: "sha256".to_owned(),
                        value: stored.digest_value.clone(),
                    }),
                    location: Some(AssetLocation {
                        provider: LOCAL_STORE_PROVIDER.to_owned(),
                        opaque_ref: stored.relative_path.clone(),
                        url: None,
                    }),
                    thumbnail,
                },
                raster: output.raster.clone(),
                vector: output.vector.clone(),
                font: None,
                logo: None,
                license,
                provenance: provenance.unwrap_or_default(),
                tags: tags.unwrap_or_default(),
            };

            Ok(CoreResponse {
                ok: true,
                scene: None,
                diagnostics: output.diagnostics,
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
                export: None,
                asset: Some(json!({
                    "record": to_value(record)?,
                    "deduplicated": stored.deduplicated,
                    "sniffed_mime": output.sniffed_mime,
                    "relative_path": stored.relative_path,
                    "digest_value": stored.digest_value,
                    "byte_length": stored.byte_length,
                })),
                build_info: None,
            })
        }
        CoreRequest::GenerateQr {
            store_root,
            data,
            asset_id,
            label,
            ec_level,
            print,
            target_width_mm,
        } => {
            let ec_level = ec_level
                .as_deref()
                .map(lumen_assets::QrEcLevel::parse)
                .transpose()
                .map_err(|message| core_error("helper.qr_ec_level", message))?;
            let qr_request = lumen_assets::QrRequest {
                data: data.clone(),
                ec_level,
                print,
                target_width_mm,
            };
            let output = match lumen_assets::generate_qr(&qr_request) {
                Ok(output) => output,
                Err(error) => {
                    return Ok(error_response(
                        core_error(error.code, error.message.clone()),
                        vec![error.diagnostic],
                    ))
                }
            };
            let qr_diagnostics = output.diagnostics.clone();

            // Normalize through the shared ingest path (sanitize, store,
            // record assembly) so generated assets are first-class assets.
            let mut response = handle_request(CoreRequest::IngestAsset {
                store_root,
                bytes_base64: BASE64.encode(output.svg.as_bytes()),
                asset_id: asset_id.clone(),
                label: label.unwrap_or_else(|| format!("QR code ({data})")),
                declared_mime_type: Some("image/svg+xml".to_owned()),
                filename: Some(format!("{asset_id}.svg")),
                kind: Some(json!("vector")),
                uploaded_by: None,
                license: Some(json!({
                    "name": "generated_qr",
                    "allow_export": true,
                    "allow_modification": true,
                    "allow_embedding": true,
                    "allow_subsetting": true,
                    "source_url": null,
                    "restrictions": []
                })),
                provenance: Some(json!({
                    "created_by": "qr-v1",
                    "created_at": null,
                    "source_label": "generated:qr",
                    "confidence": 1.0,
                    "notes": [format!(
                        "deterministic QR encode: {} data bytes, ec level {}, {} modules",
                        data.len(),
                        output.ec_level.as_str(),
                        output.module_count
                    )]
                })),
                source: Some(json!({
                    "kind": "generated",
                    "request_id": asset_id,
                    "model": "qr-v1"
                })),
                tags: Some(vec!["qr".to_owned(), "generated".to_owned()]),
                max_bytes: None,
            })?;

            if response.ok {
                if let Some(asset) = response.asset.as_mut() {
                    asset["qr"] = json!({
                        "ec_level": output.ec_level.as_str(),
                        "module_count": output.module_count,
                        "quiet_zone_modules": output.quiet_zone_modules,
                    });
                }
                response.diagnostics.extend(qr_diagnostics);
            }
            Ok(response)
        }
        CoreRequest::GenerateAsset {
            store_root,
            provider,
            request,
            asset_id,
            label,
        } => {
            let generation_request =
                serde_json::from_value::<lumen_core::AssetGenerationRequest>(request)
                    .map_err(|error| core_error("helper.generation_request", error.to_string()))?;
            let registry = lumen_assets::ProviderRegistry::with_default_providers();
            let artifact = match registry.generate(&provider, &generation_request) {
                Ok(artifact) => artifact,
                Err(error) => {
                    return Ok(error_response(
                        core_error(error.code, error.message.clone()),
                        vec![error.diagnostic],
                    ))
                }
            };
            let provider_diagnostics = artifact.diagnostics.clone();
            let provider_metadata = artifact.provider_metadata.clone();

            let mut response = handle_request(CoreRequest::IngestAsset {
                store_root,
                bytes_base64: BASE64.encode(&artifact.bytes),
                asset_id: asset_id.clone(),
                label: label.unwrap_or_else(|| format!("Generated asset ({provider})")),
                declared_mime_type: Some(artifact.mime_type.clone()),
                filename: None,
                kind: Some(to_value(&artifact.kind)?),
                uploaded_by: None,
                license: Some(to_value(&artifact.license)?),
                provenance: Some(json!({
                    "created_by": provider,
                    "created_at": null,
                    "source_label": format!("generated:{provider}"),
                    "confidence": 1.0,
                    "notes": artifact.provenance_notes,
                })),
                source: Some(json!({
                    "kind": "generated",
                    "request_id": generation_request.request_id,
                    "model": provider,
                })),
                tags: Some(vec!["generated".to_owned()]),
                max_bytes: None,
            })?;

            if response.ok {
                if let Some(asset) = response.asset.as_mut() {
                    asset["provider"] = json!({
                        "id": provider,
                        "metadata": provider_metadata,
                    });
                }
                response.diagnostics.extend(provider_diagnostics);
            }
            Ok(response)
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
                    asset: None,
                    build_info: None,
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
                asset: None,
                build_info: None,
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
                asset: None,
                build_info: None,
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
                        asset: None,
                        build_info: None,
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
                    asset: None,
                    build_info: None,
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
                asset: None,
                build_info: None,
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
                asset: None,
                build_info: None,
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
                asset: None,
                build_info: None,
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
                asset: None,
                build_info: None,
            })
        }
        CoreRequest::LayoutGeometry { scene } => {
            let scene = parse_scene(scene)?;
            let result = layout_scene(
                &scene,
                lumen_core::LayoutOptions {
                    measurer: Some(server_measurer()),
                    ..Default::default()
                },
            );
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
                asset: None,
                build_info: None,
            })
        }
        // W5 version handshake: the editor compares this against the WASM
        // module's version() and downgrades to server-only mode on any
        // mismatch — never mixed-version optimistic editing.
        CoreRequest::BuildInfo => Ok(CoreResponse {
            ok: true,
            scene: None,
            diagnostics: Vec::new(),
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
            export: None,
            asset: None,
            build_info: Some(json!({
                "schema_version": lumen_core::SCHEMA_VERSION,
                "engine_commit": env!("LUMEN_ENGINE_COMMIT"),
            })),
        }),
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
        asset: None,
        build_info: None,
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

fn values<T: Serialize>(items: Vec<T>) -> Result<Vec<Value>, CoreError> {
    items.into_iter().map(to_value).collect()
}

fn dsl_compile_output_value(output: &lumen_core::DslCompileOutput) -> Result<Value, CoreError> {
    Ok(json!({
        "operations": values(output.operations.clone())?,
        "checkpoint_label": output.checkpoint_label,
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
