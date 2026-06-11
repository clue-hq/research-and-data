use lumen_core::validation::validate_scene;
use lumen_core::{
    compare_brand_kit_compatibility, compile_dsl_into_scene_with_session, compile_styles_brand_kit,
    generate_brand_kit, layout_scene, platform_default_brand_kit, preflight_scene,
    summarize_brand_kit_for_authoring, validate_brand_kit, validate_brand_kit_product_ready,
    validate_scene_brand_governance, BrandGovernanceStrictness, BrandKit, BrandKitId, BrandMode,
    BrandSeed, Diagnostic, DiagnosticSeverity, DocumentId, DslCompileSessionSnapshot,
    ExportAdapter, ExportFormat, ExportProfile, ExportPurpose, ExportRequest, Medium, Operation,
    PageId, PdfIntent, PreflightOptions, RasterScale, Scene, TemplateRevisionId,
};
use lumen_export::LumenExportAdapter;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{self, Read};

#[derive(Debug, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
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

fn main() {
    let response = match read_request().and_then(handle_request) {
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
            dsl: None,
            export: None,
        },
    };

    println!(
        "{}",
        serde_json::to_string(&response).expect("helper response should serialize")
    );
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
