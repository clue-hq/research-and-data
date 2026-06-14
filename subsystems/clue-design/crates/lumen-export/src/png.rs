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
    is_canonical_page_size, page_geometry, physical_page_size_inches, unit_to_inches,
    ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportRequest, ExportResult, Page,
    Scene,
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
    let scale = request
        .profile
        .raster
        .as_ref()
        .map(|raster| raster.scale)
        .unwrap_or(1.0);

    let geometry = page_geometry(page);
    if is_canonical_page_size(&page.size) {
        if request.profile.raster.is_none() {
            if let Some(raster) = geometry.raster {
                return (raster.width_px.max(1), raster.height_px.max(1));
            }
        }

        if let (Some(physical), Some(dpi)) = (
            geometry.physical.as_ref(),
            request
                .profile
                .raster
                .as_ref()
                .and_then(|raster| raster.dpi),
        ) {
            let dpi = f64::from(dpi);
            let (width_in, height_in) = physical_page_size_inches(physical);
            return (
                (width_in * dpi * scale).round().max(1.0) as u32,
                (height_in * dpi * scale).round().max(1.0) as u32,
            );
        }

        return (
            (geometry.layout.width * scale).round().max(1.0) as u32,
            (geometry.layout.height * scale).round().max(1.0) as u32,
        );
    }

    let dpi = request
        .profile
        .raster
        .as_ref()
        .and_then(|raster| raster.dpi)
        .unwrap_or(96) as f64;
    let width_in = unit_to_inches(page.size.width, &page.size.unit, dpi);
    let height_in = unit_to_inches(page.size.height, &page.size.unit, dpi);

    (
        (width_in * dpi * scale).round().max(1.0) as u32,
        (height_in * dpi * scale).round().max(1.0) as u32,
    )
}

#[cfg(test)]
mod tests {
    use super::page_pixel_size;
    use lumen_core::{
        normalize_page_size, ExportFormat, ExportProfile, ExportPurpose, ExportRequest,
        Orientation, Page, PageId, PagePreset, PageSizeInput, RasterScale, Unit,
    };

    fn page(width: f64, height: f64, unit: Unit) -> Page {
        Page {
            id: PageId::from("page"),
            name: "Page".to_owned(),
            size: normalize_page_size(PageSizeInput::new(
                width,
                height,
                unit,
                Some(PagePreset::Custom),
                Orientation::Landscape,
            )),
            children: Vec::new(),
            bleed: None,
            safe_area: None,
            background: Vec::new(),
        }
    }

    fn request(raster: Option<RasterScale>) -> ExportRequest {
        ExportRequest {
            profile: ExportProfile {
                name: "png_test".to_owned(),
                format: ExportFormat::Png,
                pdf_intent: None,
                raster,
                include_bleed: false,
                embed_fonts: false,
            },
            page_ids: vec![PageId::from("page")],
            purpose: ExportPurpose::UserDownload,
        }
    }

    #[test]
    fn canonical_px_page_uses_raster_default_without_profile_override() {
        let page = page(1080.0, 1080.0, Unit::Px);

        assert_eq!(page_pixel_size(&page, &request(None)), (1080, 1080));
    }

    #[test]
    fn canonical_physical_page_uses_dpi_from_profile() {
        let page = page(210.0, 297.0, Unit::Mm);

        assert_eq!(
            page_pixel_size(
                &page,
                &request(Some(RasterScale {
                    scale: 1.0,
                    dpi: Some(300),
                })),
            ),
            (2480, 3508)
        );
    }
}
