//! Booklet imposition rendering (print W4): 2-up duplex saddle-stitch
//! sheets, imposed at RENDER time — each sheet side is one PDF page onto
//! which two reader pages paint through the same shared paint as every
//! other target. No PDF-level page surgery, fonts embedded once per
//! document, parity with reader-order output by construction.
//!
//! Sheet geometry is DERIVED in v1: sheet = 2× page width, same height
//! (6×8in pages → the classic 8×12 folded sheet; A4 → A3 landscape).
//! Trim-only: no bleed, no marks, creep 0 — declared by the adapter
//! (LUME0430). Order math lives portable in `lumen_export::imposition`.

use crate::render::SkiaSceneRenderer;
use lumen_core::{unit_to_points, Diagnostic, DiagnosticSubject, Page, PageId, Phase, Scene};
use lumen_export::{
    booklet_sheet_sides, AssetByteResolver, RasterizeError, RenderedPdf, RenderedPdfPage,
};
use skia_safe::{pdf, surfaces, Canvas, Data, EncodedImageFormat, Image, Paint as SkPaint, Rect as SkRect};

struct BookletLayout<'a> {
    pages: Vec<&'a Page>,
    sides: Vec<lumen_export::BookletSheetSide>,
    sheet_width_pt: f64,
    sheet_height_pt: f64,
}

fn booklet_layout<'a>(
    scene: &'a Scene,
    page_ids: &[PageId],
) -> Result<BookletLayout<'a>, RasterizeError> {
    let ids: Vec<PageId> = if page_ids.is_empty() {
        scene.pages.keys().cloned().collect()
    } else {
        page_ids.to_vec()
    };
    if ids.is_empty() {
        return Err(RasterizeError::new(
            "raster.pdf_no_pages",
            "booklet imposition requires at least one page",
        ));
    }
    let mut pages = Vec::with_capacity(ids.len());
    for page_id in &ids {
        pages.push(scene.pages.get(page_id).ok_or_else(|| {
            RasterizeError::new(
                "raster.page_missing",
                format!("page {page_id} is not in the scene"),
            )
        })?);
    }
    let first = pages[0];
    let scale_pt = unit_to_points(1.0, &first.size.unit);
    let page_width_pt = (first.size.width * scale_pt).max(1.0);
    let page_height_pt = (first.size.height * scale_pt).max(1.0);
    let (sides, _) = booklet_sheet_sides(pages.len());
    Ok(BookletLayout {
        pages,
        sides,
        sheet_width_pt: page_width_pt * 2.0,
        sheet_height_pt: page_height_pt,
    })
}

/// Paint one sheet side onto a canvas of `target_width`×`target_height`
/// (canvas units — points for vector, pixels for raster): white paper,
/// then each occupied slot's page scaled into its half.
fn paint_sheet_side(
    renderer: &SkiaSceneRenderer,
    canvas: &Canvas,
    scene: &Scene,
    layout: &BookletLayout,
    side: &lumen_export::BookletSheetSide,
    target_width: f32,
    target_height: f32,
    resolver: Option<&dyn AssetByteResolver>,
) -> Vec<Diagnostic> {
    let mut paper = SkPaint::default();
    paper.set_color(skia_safe::Color::WHITE);
    canvas.draw_rect(SkRect::from_wh(target_width, target_height), &paper);

    let slot_width = target_width / 2.0;
    let mut diagnostics = Vec::new();
    for (slot_index, reader_index) in [(0u32, side.left), (1u32, side.right)] {
        let Some(reader_index) = reader_index else {
            continue; // padding blank stays paper-white
        };
        let page = layout.pages[reader_index];
        let slot = SkRect::from_xywh(slot_index as f32 * slot_width, 0.0, slot_width, target_height);
        diagnostics.extend(renderer.paint_page_in_slot(scene, page, canvas, slot, resolver));
    }
    diagnostics
}

/// Vector booklet: sheet sides as native vector PDF pages (live text,
/// embedded subset fonts), front/back interleaved for duplex printing.
pub fn vector_booklet_pdf(
    renderer: &SkiaSceneRenderer,
    scene: &Scene,
    page_ids: &[PageId],
    dpi: u16,
    resolver: Option<&dyn AssetByteResolver>,
) -> Result<RenderedPdf, RasterizeError> {
    let layout = booklet_layout(scene, page_ids)?;
    let dpi = dpi.max(1);
    let mut bytes: Vec<u8> = Vec::new();
    let mut diagnostics = vec![vector_mode_advice(dpi)];
    let mut pages = Vec::new();

    {
        let metadata = pdf::Metadata {
            producer: "Lumen/Skia-PDF".to_owned(),
            raster_dpi: Some(f32::from(dpi)),
            ..Default::default()
        };
        let mut document = pdf::new_document(&mut bytes, Some(&metadata));
        for side in &layout.sides {
            let width_pt = layout.sheet_width_pt as f32;
            let height_pt = layout.sheet_height_pt as f32;
            let mut on_page = document.begin_page((width_pt, height_pt), None);
            diagnostics.extend(paint_sheet_side(
                renderer,
                on_page.canvas(),
                scene,
                &layout,
                side,
                width_pt,
                height_pt,
                resolver,
            ));
            document = on_page.end_page();
            pages.push(sheet_accounting(&layout, side, dpi));
        }
        document.close();
    }

    Ok(RenderedPdf {
        bytes,
        diagnostics,
        pages,
    })
}

/// Flattened booklet (D5 baseline): each sheet side rasterized at `dpi`
/// and embedded image-per-page.
pub fn flattened_booklet_pdf(
    renderer: &SkiaSceneRenderer,
    scene: &Scene,
    page_ids: &[PageId],
    dpi: u16,
    resolver: Option<&dyn AssetByteResolver>,
) -> Result<RenderedPdf, RasterizeError> {
    let layout = booklet_layout(scene, page_ids)?;
    let dpi = dpi.max(1);
    let dpi_f = f64::from(dpi);
    let mut bytes: Vec<u8> = Vec::new();
    let mut diagnostics = vec![flattened_mode_advice(dpi_f)];
    let mut pages = Vec::new();

    {
        let mut document = pdf::new_document(&mut bytes, None);
        for side in &layout.sides {
            let width_pt = layout.sheet_width_pt;
            let height_pt = layout.sheet_height_pt;
            let width_px = (width_pt / 72.0 * dpi_f).round().max(1.0) as i32;
            let height_px = (height_pt / 72.0 * dpi_f).round().max(1.0) as i32;
            lumen_export::ensure_raster_within_budget(
                width_px as u32,
                height_px as u32,
                "rasterizing imposed booklet sheet",
            )?;
            let mut surface =
                surfaces::raster_n32_premul((width_px, height_px)).ok_or_else(|| {
                    RasterizeError::new(
                        "raster.surface_alloc_failed",
                        format!("could not allocate {width_px}x{height_px} sheet surface"),
                    )
                })?;
            diagnostics.extend(paint_sheet_side(
                renderer,
                surface.canvas(),
                scene,
                &layout,
                side,
                width_px as f32,
                height_px as f32,
                resolver,
            ));
            let png = surface
                .image_snapshot()
                .encode(None, EncodedImageFormat::PNG, Some(100))
                .ok_or_else(|| {
                    RasterizeError::new("raster.png_encode_failed", "sheet PNG encoding failed")
                })?;
            let image = Image::from_encoded(Data::new_copy(png.as_bytes())).ok_or_else(|| {
                RasterizeError::new(
                    "raster.pdf_image_decode_failed",
                    "sheet raster could not be decoded for PDF embedding",
                )
            })?;
            let mut on_page =
                document.begin_page((width_pt as f32, height_pt as f32), None);
            on_page.canvas().draw_image_rect(
                &image,
                None,
                SkRect::from_wh(width_pt as f32, height_pt as f32),
                &SkPaint::default(),
            );
            document = on_page.end_page();
            pages.push(sheet_accounting(&layout, side, dpi));
        }
        document.close();
    }

    Ok(RenderedPdf {
        bytes,
        diagnostics,
        pages,
    })
}

fn sheet_accounting(
    layout: &BookletLayout,
    side: &lumen_export::BookletSheetSide,
    dpi: u16,
) -> RenderedPdfPage {
    RenderedPdfPage {
        page_id: PageId::from(format!(
            "sheet_{}_{}",
            side.sheet + 1,
            if side.front { "front" } else { "back" }
        )),
        width_pt: layout.sheet_width_pt as f32,
        height_pt: layout.sheet_height_pt as f32,
        width_px: (layout.sheet_width_pt / 72.0 * f64::from(dpi)).round().max(1.0) as u32,
        height_px: (layout.sheet_height_pt / 72.0 * f64::from(dpi)).round().max(1.0) as u32,
    }
}

fn vector_mode_advice(dpi: u16) -> Diagnostic {
    Diagnostic::advice(
        Phase::Export,
        "LUME0427",
        format!(
            "PDF export is vector (Skia PDF backend): live text with embedded subset fonts, vector shapes and gradients; effects PDF cannot express rasterize locally at {dpi} dpi"
        ),
        Some(DiagnosticSubject::Document),
    )
}

fn flattened_mode_advice(dpi: f64) -> Diagnostic {
    Diagnostic::advice(
        Phase::Export,
        "LUME0426",
        format!(
            "PDF export is raster-flattened at {dpi} dpi: pages paint through the Skia scene renderer and embed as images, so output matches PNG exactly but text is not selectable"
        ),
        Some(DiagnosticSubject::Document),
    )
    .with_hint(
        "The vector Skia-PDF renderer (embedded fonts, live text) is available via LUMEN_PDF_RENDERER=vector.",
    )
}
