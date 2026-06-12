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

pub mod fonts;
pub mod measure;

pub use fonts::{FamilyResolution, FontLoadError, FontManager, DEFAULT_FONT_FAMILY};
pub use measure::SkiaTextMeasurer;
