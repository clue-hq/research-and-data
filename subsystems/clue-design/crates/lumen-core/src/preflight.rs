use crate::brand::{
    collect_scene_token_references, resolve_scene_tokens, validate_brand_kit, BrandKit,
    SceneTokenReference, TokenResolutionOptions,
};
use crate::diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
use crate::export_contract::ExportFormat;
use crate::layout::{layout_scene, LayoutOptions, LayoutResult};
use crate::operations::{NodePatch, Operation, OperationError, OptionalFieldPatch};
use crate::render_contract::{effect_support_diagnostics, RenderTarget};
use crate::scene::{Medium, Scene};
use crate::validation::validate_scene;
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq)]
pub struct PreflightOptions {
    pub token_resolution: TokenResolutionOptions,
    pub layout: LayoutOptions,
    pub attach_brand_ref_if_missing: bool,
}

impl Default for PreflightOptions {
    fn default() -> Self {
        Self {
            token_resolution: TokenResolutionOptions::default(),
            layout: LayoutOptions::default(),
            attach_brand_ref_if_missing: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct PreflightResult {
    pub scene: Scene,
    pub diagnostics: Vec<Diagnostic>,
    pub brand_report: Option<crate::brand::TokenResolutionReport>,
    pub layout_result: Option<LayoutResult>,
    pub brand_ref_operations: Vec<Operation>,
    pub token_operations: Vec<Operation>,
    pub layout_operations: Vec<Operation>,
}

impl PreflightResult {
    pub fn has_errors(&self) -> bool {
        has_errors(&self.diagnostics)
    }
}

pub fn preflight_scene(
    mut scene: Scene,
    brand_kit: Option<&BrandKit>,
    options: PreflightOptions,
) -> PreflightResult {
    let mut diagnostics = validate_scene(&scene);
    let mut brand_report = None;
    let mut layout_result = None;
    let mut brand_ref_operations = Vec::new();
    let mut token_operations = Vec::new();
    let mut layout_operations = Vec::new();

    if has_errors(&diagnostics) {
        return PreflightResult {
            scene,
            diagnostics,
            brand_report,
            layout_result,
            brand_ref_operations,
            token_operations,
            layout_operations,
        };
    }

    // Renderer support matrix verdicts (Effects Contract V0): surface the
    // Approximate/Unsupported effect features per export profile before
    // export, so degradation is never a surprise at download time.
    for profile in &scene.export_profiles {
        let target = render_target_for_format(&profile.format);
        extend_unique_diagnostics(
            &mut diagnostics,
            effect_support_diagnostics(&scene, &[], &target),
        );
    }

    if brand_kit.is_none() {
        let token_references = collect_scene_token_references(&scene);
        if !token_references.is_empty() {
            diagnostics.push(missing_brand_kit_diagnostic(&token_references));
            return PreflightResult {
                scene,
                diagnostics,
                brand_report,
                layout_result,
                brand_ref_operations,
                token_operations,
                layout_operations,
            };
        }
    }

    if let Some(brand_kit) = brand_kit {
        let brand_diagnostics = validate_brand_kit(brand_kit);
        extend_unique_diagnostics(&mut diagnostics, brand_diagnostics.clone());
        if has_errors(&brand_diagnostics) {
            return PreflightResult {
                scene,
                diagnostics,
                brand_report,
                layout_result,
                brand_ref_operations,
                token_operations,
                layout_operations,
            };
        }

        if scene.meta.brand_kit.is_none() && options.attach_brand_ref_if_missing {
            let operation = Operation::SetBrandKitRef {
                brand_kit_id: brand_kit.id.clone(),
                version: brand_kit.version,
            };
            match scene.apply_operation_checked(operation.clone()) {
                Ok(report) => {
                    extend_unique_diagnostics(&mut diagnostics, report.diagnostics);
                    brand_ref_operations.push(operation);
                }
                Err(error) => {
                    diagnostics.push(operation_error_diagnostic(
                        Phase::Operation,
                        "LUMP0100",
                        "failed to attach brand kit reference before token resolution",
                        error,
                    ));
                    return PreflightResult {
                        scene,
                        diagnostics,
                        brand_report,
                        layout_result,
                        brand_ref_operations,
                        token_operations,
                        layout_operations,
                    };
                }
            }
        }

        let token_options = token_options_for_scene_medium(&scene, &options.token_resolution);
        let report = resolve_scene_tokens(&scene, brand_kit, &token_options);
        extend_unique_diagnostics(&mut diagnostics, report.diagnostics.clone());
        token_operations = report.operations.clone();
        if has_errors(&report.diagnostics) {
            brand_report = Some(report);
            return PreflightResult {
                scene,
                diagnostics,
                brand_report,
                layout_result,
                brand_ref_operations,
                token_operations,
                layout_operations,
            };
        }
        scene = report.scene.clone();
        brand_report = Some(report);
    }

    let result = layout_scene(&scene, options.layout.clone());
    extend_unique_diagnostics(&mut diagnostics, result.diagnostics.clone());

    layout_operations = result
        .geometry
        .iter()
        .map(|(node_id, computed)| Operation::UpdateNode {
            node_id: node_id.clone(),
            patch: NodePatch {
                computed: OptionalFieldPatch::Set(computed.clone()),
                ..NodePatch::default()
            },
        })
        .collect();

    // Layout diagnostics can include text-fit and slot-fit errors even when
    // the solver produced useful geometry. Apply that geometry before
    // returning so debug previews and repair agents inspect the computed
    // layout, while `has_errors()` still blocks final acceptance.
    if !layout_operations.is_empty() {
        match scene.apply_operations_checked(layout_operations.clone()) {
            Ok(report) => extend_unique_diagnostics(&mut diagnostics, report.diagnostics),
            Err(error) => {
                diagnostics.push(operation_error_diagnostic(
                    Phase::Layout,
                    "LUMP0200",
                    "failed to apply computed layout geometry",
                    error,
                ));
            }
        }
    }

    layout_result = Some(result);

    PreflightResult {
        scene,
        diagnostics,
        brand_report,
        layout_result,
        brand_ref_operations,
        token_operations,
        layout_operations,
    }
}

fn render_target_for_format(format: &ExportFormat) -> RenderTarget {
    match format {
        ExportFormat::Svg => RenderTarget::Svg,
        ExportFormat::Png => RenderTarget::Png { scale: 1.0 },
        ExportFormat::Pdf => RenderTarget::Pdf,
        ExportFormat::FigmaManifest => RenderTarget::FigmaManifest,
    }
}

fn has_errors(diagnostics: &[Diagnostic]) -> bool {
    diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
}

pub fn token_options_for_scene_medium(
    scene: &Scene,
    options: &TokenResolutionOptions,
) -> TokenResolutionOptions {
    let mut options = options.clone();
    if !options.mode.values.contains_key("medium") {
        if let Some(medium) = &scene.meta.medium {
            options.mode.values.insert(
                "medium".to_owned(),
                brand_medium_for_scene_medium(medium).to_owned(),
            );
        }
    }
    options
}

fn brand_medium_for_scene_medium(medium: &Medium) -> &'static str {
    match medium {
        Medium::Print | Medium::DirectMail => "print",
        Medium::Digital | Medium::Email | Medium::Ad | Medium::Web => "digital",
    }
}

fn extend_unique_diagnostics(target: &mut Vec<Diagnostic>, diagnostics: Vec<Diagnostic>) {
    for diagnostic in diagnostics {
        if !target.contains(&diagnostic) {
            target.push(diagnostic);
        }
    }
}

fn missing_brand_kit_diagnostic(token_references: &[SceneTokenReference]) -> Diagnostic {
    let tokens = token_references
        .iter()
        .map(|reference| reference.token.as_str())
        .collect::<BTreeSet<_>>();
    let token_list = tokens
        .iter()
        .copied()
        .take(8)
        .collect::<Vec<_>>()
        .join(", ");
    let suffix = if tokens.len() > 8 {
        format!(", and {} more", tokens.len() - 8)
    } else {
        String::new()
    };

    Diagnostic::error(
        Phase::Brand,
        "LUMP0300",
        format!(
            "scene contains brand token references but no brand kit was provided: {}{}",
            token_list, suffix
        ),
        Some(DiagnosticSubject::Document),
    )
    .with_hint(
        "Choose, upload, generate, or pass the platform default brand kit before preflight; concrete non-token scenes may preflight without a brand kit.",
    )
}

fn operation_error_diagnostic(
    phase: Phase,
    code: &'static str,
    context: &'static str,
    error: OperationError,
) -> Diagnostic {
    let mut diagnostic = Diagnostic::error(
        phase,
        code,
        format!("{context}: {} {}", error.code, error.message),
        Some(DiagnosticSubject::Document),
    );
    if !error.diagnostics.is_empty() {
        diagnostic = diagnostic.with_hint(format!(
            "The failed operation reported {} validation diagnostic(s); inspect the operation error in logs when running a debug build.",
            error.diagnostics.len()
        ));
    }
    diagnostic
}
