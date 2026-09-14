//! Native-only Skia integration for the Lumen design engine (Wave 1 Track A).
//!
//! This crate binds native C++ Skia via `skia-safe` and therefore must never
//! become a dependency of `lumen-core` (wasm-clean) or enter `lumen-export`'s
//! portable surface. Composition happens in `lumen-api-helper`, mirroring how
//! Phase E composed `lumen-assets`.
//!
//! Surface:
//! - [`FontManager`]: deterministic byte-loaded fonts (repo `fonts/` dir is
//!   the cross-runtime parity contract with the Wave 3 CanvasKit editor).
//! - `SkiaTextMeasurer` (slice A2): SkParagraph-backed [`lumen_core::TextMeasurer`].
//! - `SkiaSceneRenderer` (slice A3): direct scene→Skia PNG rasterization.

//! - `raster_flattened_pdf` (slice G7): bulk print V0 per the B3 verdict —
//!   Skia raster pages flattened into PDF, never native-PDF text or fonts.
//! - [`rasterize_svg_thumbnail`] (W1.2): one standalone SVG asset → a PNG
//!   thumbnail, so vector assets are visible to every pixels-only consumer.

pub mod embed;
pub mod fonts;
pub mod measure;
pub mod pdf_flatten;
pub mod pdf_impose;
pub mod pdf_vector;
pub mod render;
mod svg_dom;
pub mod svg_raster;

pub use embed::SkiaFontFaceResolver;
pub use fonts::{FamilyResolution, FontLoadError, FontManager, DEFAULT_FONT_FAMILY};
pub use lumen_export::{RenderedPdf, RenderedPdfPage};
pub use measure::SkiaTextMeasurer;
pub use pdf_flatten::raster_flattened_pdf;
pub use pdf_impose::{flattened_booklet_pdf, vector_booklet_pdf};
pub use pdf_vector::{vector_pdf, SkiaVectorPdfRenderer};
pub use render::SkiaSceneRenderer;
pub use svg_raster::rasterize_svg_thumbnail;
