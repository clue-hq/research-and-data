//! PNG export through an injected direct scene rasterizer (Wave 1 Track A).
//!
//! Since slice A4 there is no SVG-string rasterization path: PNG pixels come
//! from a [`PageRasterizer`] (the Skia scene renderer composed in
//! `lumen-api-helper`) painting the scene directly from computed geometry.
//! An adapter without a rasterizer fails closed with
//! `export.png_rasterizer_missing` instead of silently degrading.

use crate::raster::PageRasterizer;
use crate::resolver::AssetByteResolver;
use crate::sidecar::build_sidecar;
use crate::svg::resolve_page_ids;
use lumen_core::{
    ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportRequest, ExportResult, Page,
    Scene, Unit,
};
use std::sync::Arc;

#[derive(Clone, Debug, Default)]
pub struct PngExportAdapter {
    resolver: Option<Arc<dyn AssetByteResolver>>,
    rasterizer: Option<Arc<dyn PageRasterizer>>,
}

impl PngExportAdapter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_resolver(resolver: Arc<dyn AssetByteResolver>) -> Self {
        Self {
            resolver: Some(resolver),
            rasterizer: None,
        }
    }

    /// Inject the direct scene rasterizer. Required for PNG export: the
    /// native renderer lives outside this portable crate (lumen-skia) and
    /// is composed at the application boundary (lumen-api-helper).
    pub fn with_rasterizer(mut self, rasterizer: Arc<dyn PageRasterizer>) -> Self {
        self.rasterizer = Some(rasterizer);
        self
    }
}

impl ExportAdapter for PngExportAdapter {
    fn export(&self, scene: &Scene, request: &ExportRequest) -> Result<ExportResult, ExportError> {
        let resolved = resolve_page_ids(scene, &request.page_ids);
        if resolved
            .diagnostics
            .iter()
            .any(|diagnostic| matches!(diagnostic.severity, lumen_core::DiagnosticSeverity::Error))
        {
            return Err(ExportError::new(
                "export.invalid_pages",
                "export request references missing pages",
            )
            .with_diagnostics(resolved.diagnostics));
        }

        let Some(rasterizer) = &self.rasterizer else {
            return Err(ExportError::new(
                "export.png_rasterizer_missing",
                "PNG export requires a scene rasterizer; compose one (e.g. lumen-skia's SkiaSceneRenderer) via with_rasterizer",
            ));
        };

        let mut diagnostics = resolved.diagnostics;
        let mut artifacts = Vec::new();
        for page_id in &resolved.page_ids {
            let Some(page) = scene.pages.get(page_id) else {
                continue;
            };

            let (width, height) = page_pixel_size(page, request);
            let rasterized = rasterizer
                .rasterize_page(scene, page_id, width, height, self.resolver.as_deref())
                .map_err(|error| {
                    ExportError::new(
                        "export.png_raster_failed",
                        format!("PNG export could not rasterize page {}: {}", page_id, error),
                    )
                })?;
            diagnostics.extend(rasterized.diagnostics);

            let sidecar =
                build_sidecar(scene, std::slice::from_ref(page_id), &request.profile.name);
            let sidecar_json = serde_json::to_string_pretty(&sidecar).ok();

            artifacts.push(ExportArtifact {
                format: ExportFormat::Png,
                page_id: Some(page_id.clone()),
                asset_id: None,
                mime_type: "image/png".to_owned(),
                bytes: rasterized.png,
                sidecar_json,
            });
        }

        Ok(ExportResult {
            artifacts,
            diagnostics,
        })
    }
}

pub(crate) fn page_pixel_size(page: &Page, request: &ExportRequest) -> (u32, u32) {
    let dpi = request
        .profile
        .raster
        .as_ref()
        .and_then(|raster| raster.dpi)
        .unwrap_or(96) as f64;
    let scale = request
        .profile
        .raster
        .as_ref()
        .map(|raster| raster.scale)
        .unwrap_or(1.0);

    let (width_in, height_in) = match page.size.unit {
        Unit::Px => (page.size.width / dpi, page.size.height / dpi),
        Unit::Mm => (page.size.width / 25.4, page.size.height / 25.4),
        Unit::In => (page.size.width, page.size.height),
    };

    (
        (width_in * dpi * scale).round().max(1.0) as u32,
        (height_in * dpi * scale).round().max(1.0) as u32,
    )
}
