//! Raster-flattened PDF for print export (Phase G slice G7; print W0 wires
//! it into interactive export through the `PdfFlattener` seam).
//!
//! BINDING B3 verdict (engine/skia-text-raster-v0 memory, 2026-06-13):
//! bulk print V0 is Skia-300dpi-raster flattened into PDF pages. The
//! native vector PDF path cannot be relied on today (no font embedding,
//! image nodes unrendered, no TrimBox/BleedBox); native-PDF fidelity is
//! the print workstream's follow-up. This module therefore renders each
//! page through the A3 `SkiaSceneRenderer` at the requested DPI and embeds
//! the raster into PDF pages sized in points — never native PDF text,
//! fonts, or vector content.
//!
//! With `include_bleed`, each page's bleed rect becomes the rendered region
//! and the PDF page box (the same MediaBox-expansion contract as the vector
//! writer's `PdfPageBox::for_page`), so full-bleed backgrounds and
//! edge-touching art survive the trim.

use crate::render::SkiaSceneRenderer;
use lumen_core::{unit_to_points, Page, PageId, Rect, Scene};
use lumen_export::{
    AssetByteResolver, FlattenedPdf, FlattenedPdfPage, PdfFlattener, RasterizeError,
};
use skia_safe::{pdf, Data, Image, Paint as SkPaint, Rect as SkRect};

/// The rendered region for one page in layout units: the bleed rect when
/// requested and present, the trim (page) rect otherwise. Mirrors the
/// vector writer's `PdfPageBox::for_page`.
fn page_region(page: &Page, include_bleed: bool) -> Rect {
    let trim = Rect {
        x: 0.0,
        y: 0.0,
        width: page.size.width,
        height: page.size.height,
    };
    if include_bleed {
        page.bleed.clone().unwrap_or(trim)
    } else {
        trim
    }
}

/// Render the requested pages at `dpi` through the scene rasterizer and
/// flatten them into a PDF document (one image XObject per page, page
/// boxes sized in points). Deterministic: no timestamps or random ids are
/// written (verified by byte-comparing repeated runs in tests).
pub fn raster_flattened_pdf(
    renderer: &SkiaSceneRenderer,
    scene: &Scene,
    page_ids: &[PageId],
    dpi: u16,
    include_bleed: bool,
    resolver: Option<&dyn AssetByteResolver>,
) -> Result<FlattenedPdf, RasterizeError> {
    let ids: Vec<PageId> = if page_ids.is_empty() {
        scene.pages.keys().cloned().collect()
    } else {
        page_ids.to_vec()
    };
    if ids.is_empty() {
        return Err(RasterizeError::new(
            "raster.pdf_no_pages",
            "raster-flattened PDF export requires at least one page",
        ));
    }

    let dpi = f64::from(dpi.max(1));
    let mut bytes: Vec<u8> = Vec::new();
    let mut diagnostics = Vec::new();
    let mut pages = Vec::new();

    {
        let mut document = pdf::new_document(&mut bytes, None);
        for page_id in &ids {
            let page = scene.pages.get(page_id).ok_or_else(|| {
                RasterizeError::new(
                    "raster.page_missing",
                    format!("page {page_id} is not in the scene"),
                )
            })?;
            let region = page_region(page, include_bleed);
            let scale_pt = unit_to_points(1.0, &page.size.unit);
            let width_pt = (region.width * scale_pt).max(1.0);
            let height_pt = (region.height * scale_pt).max(1.0);
            let width_px = (width_pt / 72.0 * dpi).round().max(1.0) as u32;
            let height_px = (height_pt / 72.0 * dpi).round().max(1.0) as u32;

            let raster = renderer
                .rasterize_page_region(scene, page_id, &region, width_px, height_px, resolver)?;
            diagnostics.extend(raster.diagnostics);

            let image = Image::from_encoded(Data::new_copy(&raster.png)).ok_or_else(|| {
                RasterizeError::new(
                    "raster.pdf_image_decode_failed",
                    format!("rasterized page {page_id} could not be decoded for PDF embedding"),
                )
            })?;

            let mut on_page = document.begin_page((width_pt as f32, height_pt as f32), None);
            let canvas = on_page.canvas();
            canvas.draw_image_rect(
                &image,
                None,
                SkRect::from_wh(width_pt as f32, height_pt as f32),
                &SkPaint::default(),
            );
            document = on_page.end_page();

            pages.push(FlattenedPdfPage {
                page_id: page_id.clone(),
                width_pt: width_pt as f32,
                height_pt: height_pt as f32,
                width_px,
                height_px,
            });
        }
        document.close();
    }

    Ok(FlattenedPdf {
        bytes,
        diagnostics,
        pages,
    })
}

impl PdfFlattener for SkiaSceneRenderer {
    fn flatten_pdf(
        &self,
        scene: &Scene,
        page_ids: &[PageId],
        dpi: u16,
        include_bleed: bool,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<FlattenedPdf, RasterizeError> {
        raster_flattened_pdf(self, scene, page_ids, dpi, include_bleed, resolver)
    }
}
