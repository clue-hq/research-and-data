//! Web document engine for website mode.
//!
//! Tree-canonical web document: the agent authors constrained HTML which is
//! ingested into a typed node tree (the document of record); a Tailwind
//! utility class string per node is THE style layer; the theme is compiled
//! from the brand kit; the browser renders. One renderer, two targets
//! (instrumented editor / clean delivery).
//!
//! Diagnostics use the shared `lumen_core::Diagnostic` type with
//! `Phase::Web` and the `LUMW` code space:
//! - `LUMW00xx` — schema / structural validation
//! - `LUMW01xx` — constrained-HTML ingestion
//! - `LUMW02xx` — class grammar lint
//! - `LUMW03xx` — theme compilation
//! - `LUMW04xx` — rendering
//! - `LUMW05xx` — operations

pub mod classes;
pub mod doc;
pub mod ingest;
pub mod inline;
pub mod ops;
pub mod render;
pub mod theme;
pub mod util;
pub mod validate;

pub use classes::{lint_classes, ClassLintContext};
pub use doc::{
    ButtonVariant, SectionTag, TextVariant, WebDoc, WebNode, WebNodeKind, WebPage, WebThemeRef,
    WEB_SCHEMA_VERSION,
};
pub use ingest::{ingest_html_into_page, IngestOutcome};
pub use ops::{apply_operations, apply_operations_checked, WebOpError, WebOperation};
pub use render::{render_page, RenderMode, RenderOptions, RenderOutput};
pub use theme::{compile_web_theme, WebTheme, WebThemeOptions};
pub use validate::validate_web_doc;
