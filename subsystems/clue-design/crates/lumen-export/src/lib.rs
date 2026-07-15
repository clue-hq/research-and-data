//! Export adapters for the ABM Design Engine scene contract.
//!
//! This crate consumes `lumen-core` scene/export contracts. It intentionally
//! does not own design semantics, editor behavior, persistence, or asset
//! storage.

pub mod checks;
pub mod cmyk;
pub mod fonts;
pub mod imposition;
pub mod pdf;
pub mod pdf_boxes;
pub mod png;
pub mod print_ready;
pub mod raster;
pub mod resolver;
pub mod sidecar;
pub mod svg;

pub use checks::{asset_export_checks, license_enforced, MIN_EFFECTIVE_PRINT_DPI};
pub use cmyk::{cmyk_target_for, convert_pdf_to_cmyk, CmykTarget};
pub use fonts::{EmbeddedFontFace, FontEmbedError, FontFaceResolver, FontUsage};
pub use pdf::PdfExportAdapter;
pub use pdf_boxes::{
    apply_print_boxes, finalize_print_pdf, page_boxes_for,
    page_boxes_with_margin, print_margin_for_page, PageBoxes, PdfxDeclarations,
    MARK_GAP_PT, MARK_MARGIN_PT,
};
pub use imposition::{booklet_sheet_sides, BookletSheetSide};
pub use print_ready::{is_print_ready_scope, print_ready_report};
pub use png::PngExportAdapter;
pub use raster::{
    ensure_raster_within_budget, PageRasterizer, PdfRenderOptions, RasterizeError, RasterizedPage,
    RenderedPdf, RenderedPdfPage, ScenePdfRenderer, MAX_RASTER_PIXELS,
};
pub use resolver::{
    AssetByteResolver, AssetResolveError, FixtureAssetResolver, ResolvedAssetBytes,
};
pub use svg::{
    focal_crop_geometry, page_background_token_diagnostics, unresolved_brand_token_diagnostics,
    FocalCropGeometry, SvgExportAdapter,
};

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

    /// Build an export adapter whose SVG, PNG, and flattened-PDF paths
    /// embed real asset bytes through the given resolver.
    pub fn with_resolver(resolver: Arc<dyn AssetByteResolver>) -> Self {
        Self {
            svg: SvgExportAdapter::with_resolver(Arc::clone(&resolver)),
            png: PngExportAdapter::with_resolver(Arc::clone(&resolver)),
            pdf: PdfExportAdapter::new().with_resolver(resolver),
        }
    }

    /// Inject a shaping text measurer into the SVG path (Wave 1 Track A):
    /// SVG line breaks share one source of truth with the layout engine.
    /// PNG and PDF shape text inside their injected Skia renderers (same
    /// SkParagraph construction) and need no measurer.
    pub fn with_measurer(self, measurer: SharedTextMeasurer) -> Self {
        Self {
            svg: self.svg.with_measurer(measurer),
            ..self
        }
    }

    /// Inject a direct scene rasterizer for the PNG path (slice A3).
    pub fn with_rasterizer(self, rasterizer: Arc<dyn PageRasterizer>) -> Self {
        Self {
            png: self.png.with_rasterizer(rasterizer),
            ..self
        }
    }

    /// Inject a scene PDF renderer (print W0 raster-flattened or W2 vector
    /// Skia-PDF). With one injected, PDF export produces the full-fidelity
    /// document instead of the early vector writer, which stays as the
    /// un-injected (wasm-portable) fallback / D5 comparison baseline.
    pub fn with_pdf_renderer(self, renderer: Arc<dyn ScenePdfRenderer>) -> Self {
        Self {
            pdf: self.pdf.with_pdf_renderer(renderer),
            ..self
        }
    }

    /// Inject a font-face resolver into the SVG path: `embed_fonts`
    /// profiles then embed the exact face bytes the raster painted with as
    /// `@font-face` data URIs (subset to the used characters), so the SVG
    /// renders identically on machines without the fonts installed. PNG and
    /// PDF embed inside their injected Skia renderers and need none.
    pub fn with_font_resolver(self, resolver: Arc<dyn FontFaceResolver>) -> Self {
        Self {
            svg: self.svg.with_font_resolver(resolver),
            ..self
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
        print_ready: None,
    })
}
