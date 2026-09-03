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
//! - `LUMW06xx` — template derivation (personalization)

pub mod classes;
pub mod derive;
pub mod doc;
pub mod fragment;
pub mod ingest;
pub mod inline;
pub mod ops;
pub mod rich_text;
pub mod render;
pub mod runtime;
pub mod theme;
pub mod util;
pub mod validate;

pub use classes::{extend_deduping_advice, lint_classes, ClassLintContext};
pub use derive::{
    derive_web_doc, personalization_key_is_valid, web_slot_key_is_valid, DeriveWebOptions,
    DerivedWebDoc, UnboundEntry, WebBoundValue, WebDeriveCoverage,
};
pub use doc::{
    calendly_url_is_valid, custom_component_artifact_id_is_valid,
    custom_component_prop_name_is_valid, custom_component_props_issue,
    custom_component_slug_is_valid, fragment_id_is_valid, fragment_slot_key_is_valid,
    fragment_slots_issue, fragment_wrapper_class, ButtonAction, ButtonCommand, ButtonVariant,
    ComponentSpec, CustomComponentValue, EmbedProvider, FragmentSlotValue, MarqueeDirection,
    SectionTag,
    TextVariant, WebDoc, WebNode, WebNodeKind, WebPage, WebThemeRef,
    MAX_CUSTOM_COMPONENT_PROPS, MAX_CUSTOM_COMPONENT_PROP_STRING_BYTES,
    WEB_SCHEMA_VERSION,
};
pub use ingest::{
    ingest_html, ingest_html_into_page, ingest_html_into_page_with, ingest_html_with,
    IngestOptions, IngestOutcome,
};
pub use ops::{apply_operations, apply_operations_checked, WebOpError, WebOperation};
pub use rich_text::{
    RichTextAlignment, RichTextBlock, RichTextDocument, RichTextInline, RichTextLink,
    RichTextListItem, RichTextListType, RichTextMarks, RICH_TEXT_SCHEMA_VERSION,
};
pub use render::{
    page_fragment_ids, render_page, CustomComponentRuntimeFrame, FragmentContent, FragmentSlotKind,
    RenderMode, RenderOptions, RenderOutput,
};
pub use runtime::{PLATFORM_CSS, PLATFORM_RUNTIME_JS, PLATFORM_RUNTIME_VERSION};
pub use theme::{compile_web_theme, WebTheme, WebThemeOptions};
pub use validate::{route_is_valid, validate_web_doc};
