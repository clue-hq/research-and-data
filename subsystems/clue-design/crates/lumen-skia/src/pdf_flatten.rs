//! Raster-flattened PDF (Phase G slice G7; print W0 wired it into
//! interactive export through the `ScenePdfRenderer` seam).
//!
//! Originally the BINDING B3 verdict (2026-06-13): bulk print V0 is
//! Skia-300dpi-raster flattened into PDF pages, because the early vector
//! writer couldn't be relied on. Since print W2 the DEFAULT server PDF is
//! the true vector renderer (`pdf_vector`); this module remains as the D5
//! comparison baseline (`LUMEN_PDF_RENDERER=flattened`) and the bulk
//! instance-export path. It renders each page through the A3
//! `SkiaSceneRenderer` at the requested DPI and embeds the raster into PDF
//! pages sized in points — never native PDF text, fonts, or vector content.
//!
//! With `include_bleed`, each page's bleed rect becomes the rendered region
//! and the PDF page box (the same MediaBox-expansion contract as the vector
//! writer's `PdfPageBox::for_page`), so full-bleed backgrounds and
//! edge-touching art survive the trim.

use crate::render::SkiaSceneRenderer;
use lumen_core::{
    unit_to_points, Diagnostic, DiagnosticSubject, Page, PageId, Phase, Rect, Scene,
};
use lumen_export::{
    AssetByteResolver, RasterizeError, RenderedPdf, RenderedPdfPage, ScenePdfRenderer,
};
use skia_safe::{pdf, Data, Image, Paint as SkPaint, Rect as SkRect};

/// The rendered region for one page in layout units: the bleed rect when
/// requested and present, the trim (page) rect otherwise. Mirrors the
/// exact-box contract in `lumen_export::pdf_boxes`.
pub(crate) fn page_region(page: &Page, include_bleed: bool) -> Rect {
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

/// Everything a PDF page render needs: the full render region (bleed,
/// plus the marks margin when marks apply), the crop-mark geometry, and
/// the page box in points. Shared by the flattened and vector renderers so
/// their geometry can never drift — and it MUST agree with
/// `lumen_export::pdf_boxes::page_boxes_with_margin`.
pub(crate) struct PageRenderGeometry {
    pub region: Rect,
    pub marks: Option<crate::render::CropMarks>,
    pub width_pt: f64,
    pub height_pt: f64,
}

pub(crate) fn page_render_geometry(
    page: &Page,
    include_bleed: bool,
    include_marks: bool,
) -> PageRenderGeometry {
    let scale_pt = unit_to_points(1.0, &page.size.unit);
    let base = page_region(page, include_bleed);
    let marks_active = include_marks && include_bleed && page.bleed.is_some();
    let (region, marks) = if marks_active {
        let margin = lumen_export::MARK_MARGIN_PT / scale_pt;
        let gap = lumen_export::MARK_GAP_PT / scale_pt;
        let region = Rect {
            x: base.x - margin,
            y: base.y - margin,
            width: base.width + 2.0 * margin,
            height: base.height + 2.0 * margin,
        };
        let marks = crate::render::CropMarks {
            trim: Rect {
                x: 0.0,
                y: 0.0,
                width: page.size.width,
                height: page.size.height,
            },
            bleed: base.clone(),
            margin,
            gap,
            stroke_width: 0.5 / scale_pt,
        };
        (region, Some(marks))
    } else {
        (base, None)
    };
    PageRenderGeometry {
        width_pt: (region.width * scale_pt).max(1.0),
        height_pt: (region.height * scale_pt).max(1.0),
        region,
        marks,
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
    include_marks: bool,
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
            "raster-flattened PDF export requires at least one page",
        ));
    }

    let dpi = f64::from(dpi.max(1));
    let mut bytes: Vec<u8> = Vec::new();
    // The renderer owns its mode declaration: raster-flattened is honest
    // about the one caveat (no live text). The vector renderer declares
    // LUME0427 instead; the adapter emits neither.
    let mut diagnostics = vec![Diagnostic::advice(
        Phase::Export,
        "LUME0426",
        format!(
            "PDF export is raster-flattened at {dpi} dpi: pages paint through the Skia scene renderer and embed as images, so output matches PNG exactly but text is not selectable"
        ),
        Some(DiagnosticSubject::Document),
    )
    .with_hint(
        "The vector Skia-PDF renderer (embedded fonts, live text) is available via LUMEN_PDF_RENDERER=vector.",
    )];
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
            let geometry = page_render_geometry(page, include_bleed, include_marks);
            let width_pt = geometry.width_pt;
            let height_pt = geometry.height_pt;
            let width_px = (width_pt / 72.0 * dpi).round().max(1.0) as u32;
            let height_px = (height_pt / 72.0 * dpi).round().max(1.0) as u32;

            let raster = renderer.rasterize_page_region_with(
                scene,
                page_id,
                &geometry.region,
                width_px,
                height_px,
                resolver,
                geometry.marks.as_ref(),
            )?;
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

            pages.push(RenderedPdfPage {
                page_id: page_id.clone(),
                width_pt: width_pt as f32,
                height_pt: height_pt as f32,
                width_px,
                height_px,
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

impl ScenePdfRenderer for SkiaSceneRenderer {
    fn render_pdf(
        &self,
        scene: &Scene,
        page_ids: &[PageId],
        dpi: u16,
        include_bleed: bool,
        include_marks: bool,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<RenderedPdf, RasterizeError> {
        raster_flattened_pdf(
            self,
            scene,
            page_ids,
            dpi,
            include_bleed,
            include_marks,
            resolver,
        )
    }
}
