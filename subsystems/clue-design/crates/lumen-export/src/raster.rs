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
pub trait ScenePdfRenderer: fmt::Debug + Send + Sync {
    fn render_pdf(
        &self,
        scene: &Scene,
        page_ids: &[PageId],
        dpi: u16,
        include_bleed: bool,
        resolver: Option<&dyn AssetByteResolver>,
    ) -> Result<RenderedPdf, RasterizeError>;
}
