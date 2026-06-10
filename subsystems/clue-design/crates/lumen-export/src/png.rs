use crate::sidecar::build_sidecar;
use crate::svg::{render_page_svg, resolve_page_ids};
use lumen_core::{
    Diagnostic, DiagnosticSubject, ExportAdapter, ExportArtifact, ExportError, ExportFormat,
    ExportRequest, ExportResult, Page, PageId, Phase, Scene, Unit,
};
use resvg::{tiny_skia, usvg};

#[derive(Clone, Debug, Default)]
pub struct PngExportAdapter;

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

        let mut diagnostics = resolved.diagnostics;
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0301",
                "PNG export rasterized the canonical SVG page output",
                Some(DiagnosticSubject::Document),
            )
            .with_hint(
                "SVG and PNG export now share text layout, paint, transform, and computed-geometry semantics.",
            ),
        );

        let mut artifacts = Vec::new();
        for page_id in &resolved.page_ids {
            let Some(page) = scene.pages.get(page_id) else {
                continue;
            };

            let (svg, page_diagnostics) = render_page_svg(scene, page);
            diagnostics.extend(page_diagnostics);
            let png = rasterize_svg_page(&svg, page, request, page_id)?;

            let sidecar =
                build_sidecar(scene, std::slice::from_ref(page_id), &request.profile.name);
            let sidecar_json = serde_json::to_string_pretty(&sidecar).ok();

            artifacts.push(ExportArtifact {
                format: ExportFormat::Png,
                page_id: Some(page_id.clone()),
                asset_id: None,
                mime_type: "image/png".to_owned(),
                bytes: png,
                sidecar_json,
            });
        }

        Ok(ExportResult {
            artifacts,
            diagnostics,
        })
    }
}

fn rasterize_svg_page(
    svg: &str,
    page: &Page,
    request: &ExportRequest,
    page_id: &PageId,
) -> Result<Vec<u8>, ExportError> {
    let mut options = usvg::Options::default();
    options.fontdb_mut().load_system_fonts();

    let tree = usvg::Tree::from_str(svg, &options).map_err(|error| {
        ExportError::new(
            "export.png_svg_parse_failed",
            format!(
                "PNG export could not parse SVG for page {}: {}",
                page_id, error
            ),
        )
    })?;

    let (target_width, target_height) = page_pixel_size(page, request);
    let mut pixmap = tiny_skia::Pixmap::new(target_width, target_height).ok_or_else(|| {
        ExportError::new(
            "export.png_pixmap_alloc_failed",
            format!(
                "PNG export could not allocate {}x{} raster surface for page {}",
                target_width, target_height, page_id
            ),
        )
    })?;

    let intrinsic = tree.size();
    let scale_x = target_width as f32 / intrinsic.width().max(1.0);
    let scale_y = target_height as f32 / intrinsic.height().max(1.0);
    let transform = tiny_skia::Transform::from_scale(scale_x, scale_y);
    resvg::render(&tree, transform, &mut pixmap.as_mut());

    pixmap.encode_png().map_err(|error| {
        ExportError::new(
            "export.png_encode_failed",
            format!(
                "PNG export could not encode raster output for page {}: {}",
                page_id, error
            ),
        )
    })
}

fn page_pixel_size(page: &Page, request: &ExportRequest) -> (u32, u32) {
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
