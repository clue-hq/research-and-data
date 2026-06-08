use lumen_core::validation::validate_scene;
use lumen_core::{
    layout_scene, platform_default_brand_kit, preflight_scene, BrandKit, Diagnostic, DocumentId,
    Medium, Operation, PreflightOptions, Scene, TemplateRevisionId,
};
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
    PreflightScene {
        scene: Value,
        brand_kit: Option<Value>,
    },
    FinalizeTemplate {
        scene: Value,
        template_revision_id: String,
    },
    PlatformDefaultBrandKit,
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
    geometry: Option<Value>,
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
            geometry: None,
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
                    geometry: None,
                }),
            }
        }
        CoreRequest::PreflightScene { scene, brand_kit } => {
            let scene = parse_scene(scene)?;
            let brand_kit = brand_kit.map(parse_brand_kit).transpose()?;
            let result = preflight_scene(scene, brand_kit.as_ref(), PreflightOptions::default());
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
                geometry: None,
            })
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
                    geometry: None,
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
                geometry: None,
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
                geometry: Some(json!(result.geometry)),
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
        geometry: None,
    }
}

fn parse_scene(value: Value) -> Result<Scene, CoreError> {
    serde_json::from_value(value).map_err(|error| core_error("helper.scene", error.to_string()))
}

fn parse_brand_kit(value: Value) -> Result<BrandKit, CoreError> {
    serde_json::from_value(value).map_err(|error| core_error("helper.brand_kit", error.to_string()))
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

fn to_value<T: Serialize>(value: T) -> Result<Value, CoreError> {
    serde_json::to_value(value).map_err(|error| core_error("helper.serialize", error.to_string()))
}

fn core_error(code: impl Into<String>, message: impl Into<String>) -> CoreError {
    CoreError {
        code: code.into(),
        message: message.into(),
    }
}
