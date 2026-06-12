//! Asset runtime adapters for the ABM Design Engine.
//!
//! This crate owns byte-touching asset logic: content-addressed storage,
//! MIME sniffing, the ingest pipeline, and (in later slices) processing,
//! sanitization, thumbnails, and deterministic generation providers.
//!
//! Boundary rules: `lumen-core` stays free of storage knowledge and asset
//! bytes never enter the `Scene`. This crate depends only on `lumen-core`;
//! it does not depend on `lumen-export` — the API helper composes the two
//! (a store-backed implementation of `lumen_export::AssetByteResolver`
//! over this crate's `AssetStore`).

pub mod ingest;
pub mod mime;
pub mod probe;
pub mod sanitize;
pub mod store;
pub mod thumbs;

pub use ingest::{ingest, IngestError, IngestOutput, IngestRequest, DEFAULT_MAX_BYTES};
pub use mime::{default_kind_for_mime, mime_compatible, sniff_mime};
pub use probe::{parse_jpeg_dpi, parse_png_dpi, probe_raster};
pub use sanitize::{sanitize_svg, SanitizeError, SanitizeOutput};
pub use store::{
    digest_relative_path, sha256_hex, AssetStore, AssetStoreError, LocalAssetStore, StoredObject,
};
pub use thumbs::{derive_raster_thumbnail, ThumbnailArtifact, THUMBNAIL_MAX_DIMENSION};
