//! Export adapters for the ABM Design Engine scene contract.
//!
//! This crate consumes `lumen-core` scene/export contracts. It intentionally
//! does not own design semantics, editor behavior, persistence, or asset
//! storage.

pub mod checks;
pub mod pdf;
pub mod png;
pub mod resolver;
pub mod sidecar;
pub mod svg;

pub use checks::{asset_export_checks, license_enforced, MIN_EFFECTIVE_PRINT_DPI};
pub use pdf::PdfExportAdapter;
pub use png::PngExportAdapter;
pub use resolver::{
    AssetByteResolver, AssetResolveError, FixtureAssetResolver, ResolvedAssetBytes,
};
pub use svg::SvgExportAdapter;

use lumen_core::{
    DiagnosticSeverity, ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportRequest,
    ExportResult, Scene, SharedTextMeasurer,
};
use std::sync::Arc;

#[derive(Clone, Debug, Default)]
pub struct LumenExportAdapter {
    svg: SvgExportAdapter,
    png: PngExportAdapter,
    pdf: PdfExportAdapter,
}

impl LumenExportAdapter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Build an export adapter whose SVG and PNG paths embed real asset
    /// bytes through the given resolver. PDF asset embedding is a
    /// follow-up; its print preflight already validates asset metadata.
    pub fn with_resolver(resolver: Arc<dyn AssetByteResolver>) -> Self {
        Self {
            svg: SvgExportAdapter::with_resolver(Arc::clone(&resolver)),
            png: PngExportAdapter::with_resolver(resolver),
            pdf: PdfExportAdapter::new(),
        }
    }

    /// Inject a shaping text measurer into every format path (Wave 1
    /// Track A): SVG markup, PNG raster, and PDF then share one source of
    /// truth for text line breaks with the layout engine.
    pub fn with_measurer(self, measurer: SharedTextMeasurer) -> Self {
        Self {
            svg: self.svg.with_measurer(Arc::clone(&measurer)),
            png: self.png.with_measurer(Arc::clone(&measurer)),
            pdf: self.pdf.with_measurer(measurer),
        }
    }
}

impl ExportAdapter for LumenExportAdapter {
    fn export(&self, scene: &Scene, request: &ExportRequest) -> Result<ExportResult, ExportError> {
        // Asset export checks run once at the composition point:
        // licensing rejection (LUME0212) blocks enforced exports before
        // any rendering; advisory findings ride along as warnings.
        let resolved = svg::resolve_page_ids(scene, &request.page_ids);
        let check_diagnostics = checks::asset_export_checks(scene, request, &resolved.page_ids);
        if check_diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
        {
            return Err(ExportError::new(
                "export.license_forbidden",
                "export blocked: an embedded asset's license forbids this export",
            )
            .with_diagnostics(check_diagnostics));
        }

        let mut result = match request.profile.format {
            ExportFormat::Svg => self.svg.export(scene, request),
            ExportFormat::Pdf => self.pdf.export(scene, request),
            ExportFormat::Png => self.png.export(scene, request),
            ExportFormat::FigmaManifest => figma_manifest_export(scene, request),
        }?;
        result.diagnostics.extend(check_diagnostics);
        Ok(result)
    }
}

fn figma_manifest_export(
    scene: &Scene,
    request: &ExportRequest,
) -> Result<ExportResult, ExportError> {
    let page_ids = svg::resolve_page_ids(scene, &request.page_ids);
    if page_ids
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error)
    {
        return Err(ExportError::new(
            "export.invalid_pages",
            "export request references missing pages",
        )
        .with_diagnostics(page_ids.diagnostics));
    }

    let diagnostics = page_ids.diagnostics;
    let sidecar = sidecar::build_sidecar(scene, &page_ids.page_ids, &request.profile.name);
    let bytes = serde_json::to_vec_pretty(&sidecar).unwrap_or_default();

    Ok(ExportResult {
        artifacts: vec![ExportArtifact {
            format: ExportFormat::FigmaManifest,
            page_id: None,
            asset_id: None,
            mime_type: "application/json".to_owned(),
            bytes,
            sidecar_json: None,
        }],
        diagnostics,
    })
}
