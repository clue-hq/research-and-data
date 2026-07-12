//! Vector Skia-PDF renderer (print W2) — the keystone of the export-parity
//! plan: the SAME `render.rs` paint that produces PNG rasters draws into
//! `skia_safe::pdf`'s document canvas, so the PDF carries live text with
//! embedded subset fonts, vector shapes, real gradients, and images —
//! pixel-consistent with PNG by construction. Effects that PDF cannot
//! express natively (blurs, shadows) are rasterized locally by Skia at the
//! metadata `raster_dpi`, never dropped.
//!
//! With `include_bleed`, each page's bleed rect becomes the page canvas and
//! box — the L2 render-clips-at-bleed contract, identical geometry to the
//! flattened renderer (`pdf_flatten::page_region`).
//!
//! Deterministic: metadata carries no creation date and a pinned producer
//! string, so identical scenes yield identical bytes (byte-compared in
//! tests). PDF/X boxes (TrimBox/BleedBox) are added by the portable
//! post-process in `lumen-export`, not here.

use crate::fonts::FontManager;
use crate::pdf_flatten::page_region;
use crate::render::SkiaSceneRenderer;
use lumen_core::{
    unit_to_points, Diagnostic, DiagnosticSubject, PageId, Phase, Scene,
};
use lumen_export::{
    AssetByteResolver, RasterizeError, RenderedPdf, RenderedPdfPage, ScenePdfRenderer,
};
use skia_safe::pdf;
use std::sync::Arc;

/// The injected W2 implementation of the `ScenePdfRenderer` seam. Wraps the
/// scene renderer (same `FontManager`, same paint) rather than implementing
/// the trait on `SkiaSceneRenderer` itself — that impl is taken by the W0
/// raster-flattened mode, which stays available as the fallback baseline.
#[derive(Clone, Debug)]
pub struct SkiaVectorPdfRenderer {
    renderer: SkiaSceneRenderer,
}

impl SkiaVectorPdfRenderer {
    pub fn new(fonts: Arc<FontManager>) -> Self {
        Self {
            renderer: SkiaSceneRenderer::new(fonts),
        }
    }

    pub fn from_renderer(renderer: SkiaSceneRenderer) -> Self {
        Self { renderer }
    }
}

/// Render the requested pages as a vector PDF document. `dpi` is the local
/// rasterization density for effects PDF cannot express (Skia's
/// `raster_dpi` metadata), NOT a page raster density — text and shapes stay
/// vector at any dpi.
pub fn vector_pdf(
    renderer: &SkiaSceneRenderer,
    scene: &Scene,
    page_ids: &[PageId],
    dpi: u16,
    include_bleed: bool,
    resolver: Option<&dyn AssetByteResolver>,
) -> Result<RenderedPdf, RasterizeError> {
    let ids: Vec<PageId> = if page_ids.is_empty() {
        scene.pages.keys().cloned().collect()
    } else {
        page_ids.to_vec()
    };
    if ids.is_empty() {
        return Err(RasterizeError::new(
            "raster.pdf_no_pages",
            "vector PDF export requires at least one page",
        ));
    }

    let dpi = dpi.max(1);
    let mut bytes: Vec<u8> = Vec::new();
    let mut diagnostics = vec![Diagnostic::advice(
        Phase::Export,
        "LUME0427",
        format!(
            "PDF export is vector (Skia PDF backend): live text with embedded subset fonts, vector shapes and gradients; effects PDF cannot express rasterize locally at {dpi} dpi"
        ),
        Some(DiagnosticSubject::Document),
    )];
    let mut pages = Vec::new();

    {
        // raster_dpi trades geometry for effect quality: Skia quantizes the
        // page box to the dpi pixel grid (218pt at 300dpi → 908.33px →
        // rounds to 908 → 217.92pt), an error ≤ 72/(2·dpi) pt (0.12pt =
        // 0.04mm at 300) — while effects it must rasterize (blur, shadow)
        // render crisply at that density instead of the 72dpi default.
        // Content coordinates stay float-precise; only the page box
        // quantizes. The portable box post-process in lumen-export
        // rewrites MediaBox/TrimBox/BleedBox to the EXACT scene geometry,
        // so the shipped boxes are authoritative and the residual is an
        // invisible unpainted sliver (< 0.04mm) at the outer bleed edge.
        let metadata = pdf::Metadata {
            producer: "Lumen/Skia-PDF".to_owned(),
            raster_dpi: Some(f32::from(dpi)),
            ..Default::default()
        };
        let mut document = pdf::new_document(&mut bytes, Some(&metadata));
        for page_id in &ids {
            let page = scene.pages.get(page_id).ok_or_else(|| {
                RasterizeError::new(
                    "raster.page_missing",
                    format!("page {page_id} is not in the scene"),
                )
            })?;
            let region = page_region(page, include_bleed);
            let scale_pt = unit_to_points(1.0, &page.size.unit);
            let width_pt = (region.width * scale_pt).max(1.0) as f32;
            let height_pt = (region.height * scale_pt).max(1.0) as f32;

            let mut on_page = document.begin_page((width_pt, height_pt), None);
            let canvas = on_page.canvas();
            diagnostics.extend(renderer.paint_page_region_onto(
                scene, page, &region, canvas, width_pt, height_pt, resolver,
            ));
            document = on_page.end_page();

            pages.push(RenderedPdfPage {
                page_id: page_id.clone(),
                width_pt,
                height_pt,
                // Nominal dpi-scaled dimensions for accounting parity with
                // the flattened renderer; no page-sized raster exists here.
                width_px: (f64::from(width_pt) / 72.0 * f64::from(dpi)).round().max(1.0) as u32,
                height_px: (f64::from(height_pt) / 72.0 * f64::from(dpi)).round().max(1.0) as u32,
            });
        }
        document.close();
    }

    Ok(RenderedPdf {
        bytes,
        diagnostics,
        pages,
    })
}

impl ScenePdfRenderer for SkiaVectorPdfRenderer {
    fn render_pdf(
        &self,
        scene: &Scene,
        page_ids: &[PageId],
        dpi: u16,
        include_bleed: bool,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<RenderedPdf, RasterizeError> {
        vector_pdf(&self.renderer, scene, page_ids, dpi, include_bleed, resolver)
    }
}
