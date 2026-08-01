//! Portable rasterization seam for PNG export (Wave 1 Track A, slice A3).
//!
//! `lumen-export` stays free of native renderer dependencies: this module
//! defines only the trait. The native implementation (`SkiaSceneRenderer`
//! in `lumen-skia`) is injected at the composition point
//! (`lumen-api-helper`), the same layering used for `AssetByteResolver`.

use crate::resolver::AssetByteResolver;
use lumen_core::{Diagnostic, PageId, Scene};
use std::error::Error;
use std::fmt;

/// One rasterized page: encoded PNG bytes plus the diagnostics the renderer
/// surfaced while painting (unresolved tokens, missing asset bytes, ...).
#[derive(Clone, Debug)]
pub struct RasterizedPage {
    pub png: Vec<u8>,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RasterizeError {
    pub code: &'static str,
    pub message: String,
}

impl RasterizeError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for RasterizeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for RasterizeError {}

/// Hard ceiling for any single raster surface an export may allocate.
/// 150 MP ≈ a 600 MB RGBA buffer — comfortably above every supported
/// preset combination (A2 @ 300 dpi ≈ 35 MP, A4 @ 300 dpi @ 4× ≈ 139 MP)
/// while keeping a runaway scale × dpi profile from OOMing the helper.
pub const MAX_RASTER_PIXELS: u64 = 150_000_000;

/// Fail closed when a requested raster exceeds [`MAX_RASTER_PIXELS`].
/// Every surface-allocating path (PNG export, flattened PDF pages,
/// imposed booklet sheets) checks this before allocating, so no profile
/// — UI-, agent-, or API-authored — can request an unbounded pixel
/// buffer.
pub fn ensure_raster_within_budget(
    width_px: u32,
    height_px: u32,
    context: &str,
) -> Result<(), RasterizeError> {
    let pixels = u64::from(width_px) * u64::from(height_px);
    if pixels > MAX_RASTER_PIXELS {
        return Err(RasterizeError::new(
            "raster.budget_exceeded",
            format!(
                "{context} would rasterize {width_px}x{height_px} px (~{} MP), above the {} MP export ceiling — lower the profile's raster scale or dpi",
                pixels / 1_000_000,
                MAX_RASTER_PIXELS / 1_000_000
            ),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{ensure_raster_within_budget, MAX_RASTER_PIXELS};

    #[test]
    fn budget_allows_up_to_the_ceiling() {
        // 12247^2 = 149,988,... just under 150 MP.
        assert!(ensure_raster_within_budget(12_247, 12_247, "test").is_ok());
        assert!(ensure_raster_within_budget(1, u32::MAX, "test").is_err());
    }

    #[test]
    fn budget_rejects_above_the_ceiling_with_actionable_message() {
        // A4 @ 300 dpi @ 5x: the motivating OOM case.
        let error = ensure_raster_within_budget(12_400, 17_540, "PNG export of page p1")
            .expect_err("218 MP must exceed the budget");
        assert_eq!(error.code, "raster.budget_exceeded");
        assert!(error.message.contains("12400x17540"));
        assert!(error.message.contains("lower the profile's raster scale or dpi"));
        assert!(u64::from(12_400_u32) * u64::from(17_540_u32) > MAX_RASTER_PIXELS);
    }
}

/// Paints one scene page directly to pixels. Implementations consume the
/// same computed geometry the SVG exporter consumes; text must be laid out
/// by the same shaping source injected for measurement (single source of
/// truth for line breaks).
pub trait PageRasterizer: fmt::Debug + Send + Sync {
    fn rasterize_page(
        &self,
        scene: &Scene,
        page_id: &PageId,
        width_px: u32,
        height_px: u32,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<RasterizedPage, RasterizeError>;
}

/// One rendered PDF page's accounting, returned so callers (and tests) can
/// verify the geometry that went into the document. `width_px`/`height_px`
/// report the raster dimensions for flattened renderers and the effective
/// dpi-scaled dimensions for vector renderers.
#[derive(Clone, Debug, PartialEq)]
pub struct RenderedPdfPage {
    pub page_id: PageId,
    pub width_pt: f32,
    pub height_pt: f32,
    pub width_px: u32,
    pub height_px: u32,
}

#[derive(Clone, Debug)]
pub struct RenderedPdf {
    pub bytes: Vec<u8>,
    pub diagnostics: Vec<Diagnostic>,
    pub pages: Vec<RenderedPdfPage>,
}

/// Renders scene pages into a PDF document (page boxes sized in points;
/// with `include_bleed`, the bleed rect becomes the page box — the L2
/// render-clips-at-bleed contract). Implementations: the raster-flattening
/// renderer (print W0, image-per-page) and the vector Skia-PDF renderer
/// (print W2, embedded fonts + live text). Same seam pattern as
/// [`PageRasterizer`]: the trait lives here so `lumen-export` stays free of
/// native renderer dependencies, and the native implementation is injected
/// at the composition point (`lumen-api-helper`).
/// Render options for a PDF export, resolved from the profile by the
/// adapter (one struct instead of a growing positional-bool list).
#[derive(Clone, Debug)]
pub struct PdfRenderOptions {
    /// Raster density (flattened renderer) / effect-rasterization density
    /// (vector renderer).
    pub dpi: u16,
    pub include_bleed: bool,
    pub include_marks: bool,
    /// Print W4: render 2-up duplex saddle-stitch sheets instead of
    /// reader-order pages.
    pub booklet: bool,
    /// Print W7: proof mode — Some(label) draws marks, a slug line
    /// ("label · page n/N · PROOF — not for production"), and an sRGB
    /// control strip in a margin around every page. The label carries
    /// document + profile identity; the renderer appends page numbering.
    pub proof_label: Option<String>,
}

pub trait ScenePdfRenderer: fmt::Debug + Send + Sync {
    fn render_pdf(
        &self,
        scene: &Scene,
        page_ids: &[PageId],
        options: &PdfRenderOptions,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<RenderedPdf, RasterizeError>;
}
